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
c1 AS (
  SELECT 'fiscal calendar' AS check_name,
         cast(count(*) AS STRING)                                    AS value_1,
         cast(count(DISTINCT fiscal_year) AS STRING)                  AS value_2,
         concat('first day ', cast(min(date_key) AS STRING))          AS detail,
         CASE WHEN count(*) = 730
               AND count(DISTINCT fiscal_year) = 2
               AND (SELECT fiscal_year FROM {{CORE}}dim_date WHERE date_key = DATE'2025-10-01') = 'FY2026'
              THEN 'PASS' ELSE 'FAIL' END                            AS verdict
  FROM {{CORE}}dim_date
),
c2 AS (
  SELECT 'reporting dates',
         concat(cast(count(*) AS STRING), ' reporting dates'),
         concat(cast((SELECT count(*) FROM {{CORE}}dim_date WHERE is_month_end) AS STRING), ' month ends'),
         'last business day, not last calendar day',
         CASE WHEN count(*) = 24 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_date WHERE is_reporting_date
),
c3 AS (
  SELECT 'asset class hierarchies',
         concat(cast(count(DISTINCT investment_class) AS STRING), ' investment'),
         concat(cast(count(DISTINCT regulatory_class) AS STRING), ' regulatory'),
         'the two do not align',
         CASE WHEN count(DISTINCT investment_class) = 5
               AND count(DISTINCT regulatory_class) = 3
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_asset_class
),
c4 AS (
  SELECT 'advisor region codes',
         concat(cast(count(DISTINCT region) AS STRING), ' regions'),
         concat(cast(count(DISTINCT state) AS STRING), ' states'),
         concat(cast(count(DISTINCT channel) AS STRING), ' channels'),
         CASE WHEN count(DISTINCT region) = 4 AND max(length(region)) <= 4
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_advisor
),
c5 AS (
  SELECT 'discretionary split',
         concat(cast(round(100.0 * sum(CASE WHEN is_discretionary THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% discretionary'),
         concat(cast(round(100.0 * sum(CASE WHEN NOT is_discretionary THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% advisory only'),
         'AUM and AUA differ by this',
         CASE WHEN sum(CASE WHEN NOT is_discretionary THEN 1 ELSE 0 END) > 0
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_portfolio
),
c6 AS (
  SELECT 'aum snapshot grain',
         concat(cast(round(all_dates / nullif(latest, 0)) AS STRING), 'x if summed'),
         concat('real book ', cast(round(latest / 1e9, 1) AS STRING), 'B'),
         concat('summed ', cast(round(all_dates / 1e12, 1) AS STRING), 'T'),
         CASE WHEN all_dates / nullif(latest, 0) > 100 THEN 'PASS' ELSE 'FAIL' END
  FROM (
    SELECT sum(market_value_local) AS all_dates,
           (SELECT sum(market_value_local) FROM {{CORE}}fct_aum_snapshot
             WHERE snapshot_date = (SELECT max(snapshot_date) FROM {{CORE}}fct_aum_snapshot)) AS latest
    FROM {{CORE}}fct_aum_snapshot
  )
),
c7 AS (
  SELECT 'held away assets',
         concat(cast(round(100.0 * sum(CASE WHEN held_away_value_local > 0 THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% of rows'),
         concat(cast(round(100.0 * sum(held_away_value_local) / nullif(sum(market_value_local), 0), 1) AS STRING), '% of managed value'),
         'the gap between AUM and AUA',
         CASE WHEN sum(held_away_value_local) > 0 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_aum_snapshot
  WHERE snapshot_date = (SELECT max(snapshot_date) FROM {{CORE}}fct_aum_snapshot)
),
c8 AS (
  SELECT 'flow types and status',
         concat(cast(count(DISTINCT flow_type) AS STRING), ' flow types'),
         concat(cast(round(100.0 * sum(CASE WHEN flow_type LIKE 'EXCHANGE%' THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% exchanges'),
         concat(cast(round(100.0 * sum(CASE WHEN status <> 'SETTLED' THEN 1 ELSE 0 END) / count(*), 1) AS STRING), '% not settled'),
         CASE WHEN count(DISTINCT flow_type) = 6 AND count(DISTINCT status) = 3
              THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_flows
),
c9 AS (
  SELECT 'return definitions',
         concat(cast(round(100.0 * avg(twr_gross), 2) AS STRING), '% avg gross'),
         concat(cast(round(100.0 * avg(twr_net), 2) AS STRING), '% avg net'),
         concat(cast(round(100.0 * avg(mwr), 2) AS STRING), '% avg money weighted'),
         CASE WHEN abs(avg(twr_gross) - avg(twr_net)) > 0.0005
              AND count(DISTINCT period_type) = 6 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_performance
),
c10 AS (
  SELECT 'client identifiers',
         concat(cast(round(count(*) / 1e6, 1) AS STRING), 'M clients'),
         concat(cast(count(DISTINCT ssn_last4) AS STRING), ' distinct ssn_last4'),
         'masking has something to protect',
         CASE WHEN count(*) > 0 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}dim_client
),
c11 AS (
  SELECT 'multi-currency',
         concat(cast(count(DISTINCT local_currency) AS STRING), ' currencies'),
         concat_ws(', ', array_sort(collect_set(local_currency))),
         'conversion needs an as-of-date join',
         CASE WHEN count(DISTINCT local_currency) >= 4 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_aum_snapshot
),
c12 AS (
  SELECT 'referential integrity',
         concat(cast(count(*) AS STRING), ' orphan snapshots'),
         'expected 0',
         'every snapshot reaches an account',
         CASE WHEN count(*) = 0 THEN 'PASS' ELSE 'FAIL' END
  FROM {{CORE}}fct_aum_snapshot s
  LEFT JOIN {{CORE}}dim_account a ON a.account_id = s.account_id
  WHERE a.account_id IS NULL
),
c13 AS (
  SELECT 'determinism',
         concat(cast(count(*) AS STRING), ' value for PF000001'),
         'hash-derived, not rand()',
         'identical for every learner',
         CASE WHEN count(*) = 1 THEN 'PASS' ELSE 'FAIL' END
  FROM (SELECT DISTINCT asset_class_code FROM {{CORE}}dim_portfolio WHERE portfolio_id = 'PF000001')
),
c14 AS (
  SELECT 'row counts',
         concat(cast(round((SELECT count(*) FROM {{CORE}}fct_flows) / 1e6) AS STRING), 'M flows'),
         concat(cast(round((SELECT count(*) FROM {{CORE}}fct_aum_snapshot) / 1e6) AS STRING), 'M snapshots'),
         concat(cast(round((SELECT count(*) FROM {{CORE}}dim_client) / 1e6, 1) AS STRING), 'M clients'),
         CASE WHEN (SELECT count(*) FROM {{CORE}}fct_flows) > 1000000
              THEN 'PASS' ELSE 'FAIL' END
)
SELECT * FROM c1
UNION ALL SELECT * FROM c2  UNION ALL SELECT * FROM c3
UNION ALL SELECT * FROM c4  UNION ALL SELECT * FROM c5
UNION ALL SELECT * FROM c6  UNION ALL SELECT * FROM c7
UNION ALL SELECT * FROM c8  UNION ALL SELECT * FROM c9
UNION ALL SELECT * FROM c10 UNION ALL SELECT * FROM c11
UNION ALL SELECT * FROM c12 UNION ALL SELECT * FROM c13
UNION ALL SELECT * FROM c14;
