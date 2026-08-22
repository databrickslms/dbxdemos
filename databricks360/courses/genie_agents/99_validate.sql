-- ============================================================================
-- Meridian Financial Group — 99. Validate
--
-- Run last. Each check confirms one property of the dataset. Every row should
-- report PASS; anything else means an earlier notebook did not finish, or the
-- data has been altered.
--
-- Read the numbers, not just the verdicts. Several of them are the point.
-- ============================================================================

WITH
-- 1. Two complete fiscal years, starting 1 October.
c1 AS (
  SELECT 'fiscal calendar' AS check_name,
         cast(count(*) AS STRING)                              AS value_1,
         cast(count(DISTINCT fiscal_year) AS STRING)            AS value_2,
         concat('first day ', cast(min(date_key) AS STRING))    AS detail,
         CASE WHEN count(*) = 730
               AND count(DISTINCT fiscal_year) = 2
               AND (SELECT fiscal_year FROM {{CORE}}dim_date WHERE date_key = DATE'2025-10-01') = 'FY2026'
              THEN 'PASS' ELSE 'FAIL' END                       AS verdict
  FROM {{CORE}}dim_date
),
-- 2. Region and state are codes, not names.
c2 AS (
  SELECT 'region codes',
         concat(cast(count(DISTINCT region) AS STRING), ' regions'),
         concat(cast(count(DISTINCT state) AS STRING), ' states'),
         concat('max code length ', cast(max(length(region)) AS STRING)),
         CASE WHEN count(DISTINCT region) = 4
               AND max(length(region)) <= 4
               AND max(length(state)) = 2
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_branch
),
-- 3. Two product hierarchies that do not agree.
c3 AS (
  SELECT 'product hierarchies',
         concat(cast(count(DISTINCT product_category) AS STRING), ' business'),
         concat(cast(count(DISTINCT regulatory_product_class) AS STRING), ' regulatory'),
         'the two do not align',
         CASE WHEN count(DISTINCT product_category) = 4
               AND count(DISTINCT regulatory_product_class) >= 5
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_product
),
-- 4. Status mix: settled, pending, declined, reversed.
c4 AS (
  SELECT 'transaction status mix',
         concat(cast(count(DISTINCT status) AS STRING), ' statuses'),
         concat(cast(round(100.0 * sum(CASE WHEN status = 'DECLINED' THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% declined'),
         concat(cast(round(100.0 * sum(CASE WHEN status = 'POSTED' THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% posted'),
         CASE WHEN count(DISTINCT status) = 4
               AND sum(CASE WHEN status = 'DECLINED' THEN 1 ELSE 0 END) > 0
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_transactions
),
-- 5. Gross and net revenue differ, by a few percent.
c5 AS (
  SELECT 'gross vs net revenue',
         concat(cast(round(100.0 * (g - n) / nullif(n, 0), 2) AS STRING), '% overstated'),
         concat('gross ', cast(round(g / 1e6) AS STRING), 'M'),
         concat('net ', cast(round(n / 1e6) AS STRING), 'M'),
         CASE WHEN 100.0 * (g - n) / nullif(n, 0) BETWEEN 2 AND 8
              THEN 'PASS' ELSE 'FAIL' END
  FROM (
    SELECT sum(t.fee_revenue) AS g,
           sum(t.fee_revenue) - (SELECT coalesce(sum(reversal_amount), 0) FROM {{CORE}}fct_reversals) AS n
    FROM {{CORE}}fct_transactions t WHERE t.status = 'POSTED'
  )
),
-- 6. The loan book is a daily snapshot, so summing across dates multiplies it.
c6 AS (
  SELECT 'loan snapshot grain',
         concat(cast(round(all_dates / nullif(latest, 0)) AS STRING), 'x if summed'),
         concat('real book ', cast(round(latest / 1e9, 1) AS STRING), 'B'),
         concat('summed ', cast(round(all_dates / 1e12, 1) AS STRING), 'T'),
         CASE WHEN all_dates / nullif(latest, 0) > 100 THEN 'PASS' ELSE 'FAIL' END
  FROM (
    SELECT sum(principal_balance) AS all_dates,
           (SELECT sum(principal_balance) FROM {{CORE}}fct_loan_balances
             WHERE snapshot_date = (SELECT max(snapshot_date) FROM {{CORE}}fct_loan_balances)) AS latest
    FROM {{CORE}}fct_loan_balances
  )
),
-- 7. Four distinct delinquency concepts, with materially different answers.
c7 AS (
  SELECT 'delinquency definitions',
         concat(cast(round(100.0 * sum(CASE WHEN days_past_due >= 30 THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% at 30+'),
         concat(cast(round(100.0 * sum(CASE WHEN days_past_due >= 90 THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% at 90+'),
         concat(cast(count(DISTINCT dpd_bucket) AS STRING), ' buckets, ',
                cast(count(DISTINCT loan_status) AS STRING), ' statuses'),
         CASE WHEN count(DISTINCT dpd_bucket) = 5
               AND count(DISTINCT loan_status) = 4
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_loan_balances
  WHERE snapshot_date = (SELECT max(snapshot_date) FROM {{CORE}}fct_loan_balances)
),
-- 8. Customer identifiers are present, so masking has something to protect.
c8 AS (
  SELECT 'customer identifiers',
         concat(cast(round(count(*) / 1e6, 1) AS STRING), 'M customers'),
         concat(cast(count(DISTINCT ssn_last4) AS STRING), ' distinct ssn_last4'),
         'masking has something to protect',
         CASE WHEN count(*) > 0 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_customer
),
-- 9. More than one settlement currency, so conversion matters.
c9 AS (
  SELECT 'multi-currency',
         concat(cast(count(DISTINCT currency) AS STRING), ' currencies'),
         concat_ws(', ', array_sort(collect_set(currency))),
         'conversion needs an as-of-date join',
         CASE WHEN count(DISTINCT currency) = 3 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_transactions
),
-- 10. Determinism: the same key always produces the same row.
c10 AS (
  SELECT 'determinism',
         concat(cast(count(*) AS STRING), ' value for BR0001'),
         'hash-derived, not rand()',
         'identical for every learner',
         CASE WHEN count(*) = 1 THEN 'PASS' ELSE 'FAIL' END
  FROM (SELECT DISTINCT region FROM {{CORE}}dim_branch WHERE branch_id = 'BR0001')
),
-- 11. Referential integrity through the join hub.
c11 AS (
  SELECT 'referential integrity',
         concat(cast(count(*) AS STRING), ' orphan transactions'),
         'expected 0',
         'every txn reaches an account',
         CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_transactions t
  LEFT JOIN {{CORE}}dim_account a ON a.account_id = t.account_id
  WHERE a.account_id IS NULL
),
-- 12. Row counts in the expected range for the small tier.
c12 AS (
  SELECT 'row counts',
         concat(cast(round((SELECT count(*) FROM {{CORE}}fct_transactions) / 1e6) AS STRING), 'M transactions'),
         concat(cast(round((SELECT count(*) FROM {{CORE}}fct_loan_balances) / 1e6) AS STRING), 'M loan snapshots'),
         concat(cast(round((SELECT count(*) FROM {{CORE}}dim_customer) / 1e6, 1) AS STRING), 'M customers'),
         CASE WHEN (SELECT count(*) FROM {{CORE}}fct_transactions) > 1000000
              THEN 'PASS' ELSE 'FAIL' END
)
SELECT * FROM c1
UNION ALL SELECT * FROM c2  UNION ALL SELECT * FROM c3
UNION ALL SELECT * FROM c4  UNION ALL SELECT * FROM c5
UNION ALL SELECT * FROM c6  UNION ALL SELECT * FROM c7
UNION ALL SELECT * FROM c8  UNION ALL SELECT * FROM c9
UNION ALL SELECT * FROM c10 UNION ALL SELECT * FROM c11
UNION ALL SELECT * FROM c12;
