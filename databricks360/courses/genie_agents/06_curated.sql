-- ============================================================================
-- Meridian Financial Group — 06. Curated layer
--
-- The objects a Genie Agent should actually be pointed at, and the metadata a
-- data steward writes to make them usable.
--
-- Run this AFTER attempting the curation exercise yourself. It is the worked
-- answer: opening it first turns an exercise into a reading task.
-- ============================================================================


-- ============================================================================
-- vw_transactions_net  —  one row per transaction, revenue already net
-- Pre-joins reversals and excludes anything that is not settled, so the two
-- easiest mistakes in this dataset cannot be made downstream.
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}vw_transactions_net
COMMENT 'Settled transactions with revenue already net of reversals. One row per transaction. Use this rather than fct_transactions unless you specifically need gross figures or non-settled rows.'
AS
SELECT
  t.txn_id,
  t.account_id,
  t.txn_date,
  t.merchant_category,
  t.currency,
  t.amount                                                        AS amount_native,
  cast(t.amount * fx.usd_rate AS DECIMAL(14,2))                   AS amount_usd,
  t.fee_revenue                                                   AS gross_fee_revenue,
  cast(t.fee_revenue - coalesce(r.reversal_amount, 0)
       AS DECIMAL(14,2))                                          AS net_fee_revenue,
  cast((t.fee_revenue - coalesce(r.reversal_amount, 0)) * fx.usd_rate
       AS DECIMAL(14,2))                                          AS net_fee_revenue_usd,
  t.interchange,
  r.reversal_amount IS NOT NULL                                   AS was_reversed,
  r.reason_code                                                   AS reversal_reason
FROM {{CORE}}fct_transactions t
LEFT JOIN {{CORE}}fct_reversals r
       ON r.txn_id = t.txn_id
JOIN {{CORE}}dim_fx_rate fx
  ON fx.currency = t.currency
 AND fx.rate_date = t.txn_date
WHERE t.status = 'POSTED';

ALTER VIEW {{CORE}}vw_transactions_net ALTER COLUMN net_fee_revenue
  COMMENT 'Fee revenue after deducting reversals, in the transaction currency. This is what "revenue" means at Meridian unless someone says "gross".';
ALTER VIEW {{CORE}}vw_transactions_net ALTER COLUMN net_fee_revenue_usd
  COMMENT 'Net fee revenue converted to USD at the rate for the transaction date. Use this when totalling across currencies.';
ALTER VIEW {{CORE}}vw_transactions_net ALTER COLUMN amount_usd
  COMMENT 'Transaction amount in USD. Always prefer this over amount_native when aggregating.';


-- ============================================================================
-- vw_loan_book_eop  —  the loan book at a point in time
-- Collapses the daily snapshot to month-end, so a period total is a balance
-- rather than a sum of balances.
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}vw_loan_book_eop
COMMENT 'Loan balances at month end. One row per account per month end, so SUM over a period is a real balance rather than a repeated one. Use this instead of fct_loan_balances for anything aggregated.'
AS
WITH month_ends AS (
  SELECT account_id, snapshot_date, principal_balance, interest_accrued,
         days_past_due, dpd_bucket, loan_status
  FROM {{CORE}}fct_loan_balances
  WHERE snapshot_date = last_day(snapshot_date)
)
SELECT
  m.account_id,
  m.snapshot_date                       AS as_of_date,
  d.fiscal_year,
  d.fiscal_quarter,
  m.principal_balance,
  m.interest_accrued,
  m.days_past_due,
  m.dpd_bucket,
  m.loan_status,
  m.days_past_due >= 30                  AS is_delinquent,
  m.days_past_due >= 90                  AS is_seriously_delinquent,
  m.loan_status = 'CHARGED_OFF'          AS is_charged_off
FROM month_ends m
JOIN {{CORE}}dim_date d ON d.date_key = m.snapshot_date;

ALTER VIEW {{CORE}}vw_loan_book_eop ALTER COLUMN is_delinquent
  COMMENT 'Meridian definition: 30 or more days past due.';
ALTER VIEW {{CORE}}vw_loan_book_eop ALTER COLUMN is_seriously_delinquent
  COMMENT 'Meridian definition: 90 or more days past due. Not the same as delinquent, and not the same as default.';
ALTER VIEW {{CORE}}vw_loan_book_eop ALTER COLUMN is_charged_off
  COMMENT 'An accounting event, not a days-past-due threshold. Distinct from both delinquency measures.';


-- ============================================================================
-- dim_customer_safe  —  customer attributes without the identifiers
-- Column masks already protect the base table. This view removes the columns
-- entirely, so an agent pointed here has nothing to leak by accident.
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}dim_customer_safe
COMMENT 'Customer attributes with all direct identifiers removed. Point agents here rather than at dim_customer.'
AS
SELECT
  customer_id,
  segment,
  tenure_months,
  CASE WHEN tenure_months < 12 THEN 'New'
       WHEN tenure_months < 60 THEN 'Established'
       ELSE 'Long-tenured' END                          AS tenure_band,
  home_branch_id,
  floor(datediff(DATE'2026-09-30', dob) / 365.25)       AS age_years,
  CASE WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 30 THEN 'Under 30'
       WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 50 THEN '30-49'
       WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 65 THEN '50-64'
       ELSE '65+' END                                   AS age_band
FROM {{CORE}}dim_customer;


-- ============================================================================
-- Unity Catalog functions — verified logic, reusable and shareable
-- ============================================================================

-- Balance-weighted delinquency rate at the latest month end.
CREATE OR REPLACE FUNCTION {{CORE}}delinquency_rate(
  dpd_threshold INT COMMENT 'Days past due. 30 for delinquent, 90 for seriously delinquent.'
)
RETURNS TABLE (product_category STRING, delinquency_rate DOUBLE, balance DECIMAL(20,2))
COMMENT 'Balance-weighted delinquency rate by product category, at the latest month end. Owner: Credit Risk.'
RETURN
  SELECT
    p.product_category,
    sum(CASE WHEN l.days_past_due >= dpd_threshold THEN l.principal_balance ELSE 0 END)
      / nullif(sum(l.principal_balance), 0)               AS delinquency_rate,
    cast(sum(l.principal_balance) AS DECIMAL(20,2))       AS balance
  FROM {{CORE}}vw_loan_book_eop l
  JOIN {{CORE}}dim_account a ON a.account_id = l.account_id
  JOIN {{CORE}}dim_product p ON p.product_id = a.product_id
  WHERE l.as_of_date = (SELECT max(as_of_date) FROM {{CORE}}vw_loan_book_eop)
  GROUP BY p.product_category;

-- Convert a native amount to USD at the rate for a given date.
CREATE OR REPLACE FUNCTION {{CORE}}to_usd(
  amount DECIMAL(14,2) COMMENT 'Amount in its native currency.',
  currency STRING      COMMENT 'USD, CAD or GBP.',
  on_date DATE         COMMENT 'The transaction date, not today.'
)
RETURNS DECIMAL(14,2)
COMMENT 'Converts to USD using the rate as of the given date. Owner: FP&A.'
RETURN
  amount * (SELECT usd_rate FROM {{CORE}}dim_fx_rate
            WHERE currency = currency AND rate_date = on_date);

-- Resolve a Meridian fiscal period label to its date range.
CREATE OR REPLACE FUNCTION {{CORE}}fiscal_period(
  label STRING COMMENT "Either 'FY2026' or 'FY2026-Q3'."
)
RETURNS TABLE (from_date DATE, to_date DATE)
COMMENT 'Date range for a Meridian fiscal year or quarter. The fiscal year starts 1 October. Owner: FP&A.'
RETURN
  SELECT min(date_key) AS from_date, max(date_key) AS to_date
  FROM {{CORE}}dim_date
  WHERE fiscal_year = label OR fiscal_quarter = label;


-- ----------------------------------------------------------------------------
-- Verify
-- ----------------------------------------------------------------------------
SELECT 'vw_transactions_net' AS object, count(*) AS rows FROM {{CORE}}vw_transactions_net
UNION ALL SELECT 'vw_loan_book_eop', count(*) FROM {{CORE}}vw_loan_book_eop
UNION ALL SELECT 'dim_customer_safe', count(*) FROM {{CORE}}dim_customer_safe;

-- The two delinquency definitions, side by side.
SELECT 'delinquent (30+)' AS definition, * FROM {{CORE}}delinquency_rate(30)
UNION ALL
SELECT 'seriously delinquent (90+)', * FROM {{CORE}}delinquency_rate(90)
ORDER BY definition, product_category;
