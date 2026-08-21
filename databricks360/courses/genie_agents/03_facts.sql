-- ============================================================================
-- Meridian Financial Group — 03. Facts
--
-- Plants the four remaining flaws:
--   #1  fee_revenue is GROSS; reversals live in a separate table
--   #4  DECLINED rows inflate transaction COUNTS while contributing no revenue
--   #6  fct_loan_balances is a DAILY SNAPSHOT — SUM() across dates is ~30x wrong
--   #7  "delinquent" / "seriously delinquent" / "default" / "charge-off" are
--       four different things, all present, all defensible
--
-- TIER: the line marked  -- << TIER >>  controls scale.
--   Small  20000000   default. Every module except 13.
--   Large  900000000  Module 13 only (latency). Leave unclustered on purpose.
-- ============================================================================


-- ============================================================================
-- fct_transactions  —  FLAWS #1, #4, #9
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}.fct_transactions
COMMENT 'Transaction-level fact. fee_revenue is GROSS - it does NOT deduct reversals, which live in fct_reversals. Only status = POSTED is revenue; DECLINED rows exist and will inflate transaction counts if not excluded.'
AS
WITH t AS (
  SELECT id AS n FROM range(1, {{TXN_COUNT}} + 1)   -- << TIER >> set by the tier in manifest.json
),
calc AS (
  SELECT
    n,
    pmod(hash(concat('txn-acct-',  n)), 2900000)  AS acct_n,
    pmod(hash(concat('txn-day-',   n)), 730)      AS day_offset,
    pmod(hash(concat('txn-amt-',   n)), 100000)   AS amt_pick,
    pmod(hash(concat('txn-stat-',  n)), 1000)     AS stat_pick,
    pmod(hash(concat('txn-mcc-',   n)), 12)       AS mcc_pick,
    pmod(hash(concat('txn-cur-',   n)), 100)      AS cur_pick
  FROM t
),
shaped AS (
  SELECT
    n,
    concat('T', lpad(cast(n AS STRING), 12, '0'))              AS txn_id,
    concat('A', lpad(cast(acct_n + 1 AS STRING), 9, '0'))      AS account_id,
    date_add(DATE'2024-10-01', day_offset)                     AS txn_date,
    -- Amounts are log-ish: many small, few large
    cast(
      CASE WHEN amt_pick < 70000 THEN 5    + amt_pick / 1000.0
           WHEN amt_pick < 95000 THEN 120  + amt_pick / 200.0
           ELSE                       900  + amt_pick / 50.0
      END AS DECIMAL(14,2))                                    AS amount,
    -- FLAW #4: only POSTED is revenue, but DECLINED is 6% of rows
    CASE WHEN stat_pick < 880 THEN 'POSTED'
         WHEN stat_pick < 920 THEN 'PENDING'
         WHEN stat_pick < 980 THEN 'DECLINED'
         ELSE                      'REVERSED'
    END                                                        AS status,
    element_at(array(
      'GROCERY','RESTAURANT','FUEL','AIRLINE','HOTEL','RETAIL',
      'UTILITIES','HEALTHCARE','ENTERTAINMENT','TRANSFER','ATM','PROFESSIONAL_SERVICES'
    ), mcc_pick + 1)                                           AS merchant_category,
    cur_pick
  FROM calc
)
SELECT
  s.txn_id,
  s.account_id,
  s.txn_date,
  s.amount,
  -- FLAW #1: GROSS fee revenue. Reversals are NOT deducted here.
  -- Only POSTED transactions earn anything.
  CASE WHEN s.status = 'POSTED'
       THEN cast(round(s.amount * 0.0185, 2) AS DECIMAL(14,2))
       ELSE cast(0 AS DECIMAL(14,2)) END                        AS fee_revenue,
  CASE WHEN s.status = 'POSTED'
       THEN cast(round(s.amount * 0.0110, 2) AS DECIMAL(14,2))
       ELSE cast(0 AS DECIMAL(14,2)) END                        AS interchange,
  s.merchant_category,
  -- FLAW #9: COMMERCIAL customers settle in CAD/GBP. Everyone else is USD.
  -- Summing amount across currencies without converting is silently wrong.
  CASE WHEN c.segment = 'COMMERCIAL' AND s.cur_pick < 40
         THEN CASE WHEN s.cur_pick < 25 THEN 'CAD' ELSE 'GBP' END
       ELSE 'USD' END                                           AS currency,
  s.status
FROM shaped s
JOIN {{CORE}}.dim_account  a ON a.account_id  = s.account_id
JOIN {{CORE}}.dim_customer c ON c.customer_id = a.customer_id;

ALTER TABLE {{CORE}}.fct_transactions ALTER COLUMN fee_revenue
  COMMENT 'GROSS fee revenue in the transaction currency, before reversals and chargebacks. Do NOT sum this column alone and call it revenue - subtract fct_reversals.reversal_amount. Zero for non-POSTED rows.';
ALTER TABLE {{CORE}}.fct_transactions ALTER COLUMN status
  COMMENT 'Transaction status. Values: POSTED, PENDING, DECLINED, REVERSED. ONLY POSTED counts as revenue. DECLINED rows are ~6% of the table and will inflate transaction counts if not filtered out.';
ALTER TABLE {{CORE}}.fct_transactions ALTER COLUMN currency
  COMMENT 'Settlement currency. Values: USD, CAD, GBP. COMMERCIAL customers transact in all three. Convert with dim_fx_rate joined on currency AND txn_date before summing across currencies.';
ALTER TABLE {{CORE}}.fct_transactions ALTER COLUMN amount
  COMMENT 'Transaction amount in the settlement currency (see currency column), not USD.';
ALTER TABLE {{CORE}}.fct_transactions ALTER COLUMN merchant_category
  COMMENT 'Merchant category. 12 distinct values - a good candidate for entity matching.';


-- ============================================================================
-- fct_reversals  —  the other half of FLAW #1
-- Deliberately a SEPARATE table. If reversals were a column on
-- fct_transactions nobody would ever get gross vs net wrong.
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}.fct_reversals
COMMENT 'Reversals and chargebacks. The amount here must be SUBTRACTED from fct_transactions.fee_revenue to get net fee revenue. One row per reversed transaction.'
AS
SELECT
  t.txn_id,
  date_add(t.txn_date, 3 + pmod(hash(concat('rev-lag-', t.txn_id)), 25)) AS reversal_date,
  cast(round(t.fee_revenue, 2) AS DECIMAL(14,2))                         AS reversal_amount,
  element_at(array('DISPUTE','FRAUD','DUPLICATE','MERCHANT_ERROR','AUTHORISATION_FAIL'),
             pmod(hash(concat('rev-reason-', t.txn_id)), 5) + 1)         AS reason_code
FROM {{CORE}}.fct_transactions t
-- ~3.5% of POSTED transactions get reversed, which is why "revenue" is
-- overstated by a few percent and nobody notices.
WHERE t.status = 'POSTED'
  AND pmod(hash(concat('rev-flag-', t.txn_id)), 1000) < 35;

ALTER TABLE {{CORE}}.fct_reversals ALTER COLUMN reversal_amount
  COMMENT 'Fee revenue clawed back. Subtract the sum of this from gross fee_revenue to get NET fee revenue.';
ALTER TABLE {{CORE}}.fct_reversals ALTER COLUMN reason_code
  COMMENT 'Reversal reason. Values: DISPUTE, FRAUD, DUPLICATE, MERCHANT_ERROR, AUTHORISATION_FAIL.';


-- ============================================================================
-- fct_loan_balances  —  FLAWS #6 and #7
--
-- ONE ROW PER ACCOUNT PER DAY. This is the single most dangerous table in the
-- dataset: SUM(principal_balance) over any period longer than a day produces a
-- number that looks entirely plausible and is roughly 30x too large.
--
-- 45,000 lending accounts x 730 days ~ 32.8M rows (~1.4M per month).
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}.fct_loan_balances
COMMENT 'DAILY SNAPSHOT of the loan book: one row per account per day. NEVER SUM principal_balance across dates - use the latest snapshot for a point-in-time balance, or an average for a period. Also carries the four distinct delinquency concepts.'
AS
WITH loan_accounts AS (
  SELECT a.account_id, a.opened_date
  FROM {{CORE}}.dim_account a
  JOIN {{CORE}}.dim_product p ON p.product_id = a.product_id
  WHERE p.product_category = 'LENDING'
    AND pmod(hash(concat('loan-pick-', a.account_id)), 100) < 6   -- ~6% sample
),
days AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS snapshot_date
),
grid AS (
  SELECT
    la.account_id,
    d.snapshot_date,
    datediff(d.snapshot_date, DATE'2024-10-01')                        AS day_n,
    pmod(hash(concat('loan-orig-', la.account_id)), 400)               AS orig_pick,
    pmod(hash(concat('loan-risk-', la.account_id)), 1000)              AS risk_pick
  FROM loan_accounts la CROSS JOIN days d
  WHERE d.snapshot_date >= la.opened_date
),
shaped AS (
  SELECT
    account_id,
    snapshot_date,
    -- Original principal, amortising slowly over the window
    cast(round((15000 + orig_pick * 850) * (1 - day_n / 4000.0), 2) AS DECIMAL(14,2)) AS principal_balance,
    -- Riskier accounts accumulate days past due over time
    CASE
      WHEN risk_pick < 880 THEN 0
      WHEN risk_pick < 940 THEN pmod(day_n, 45)
      WHEN risk_pick < 980 THEN 30 + pmod(day_n, 60)
      ELSE                      90 + pmod(day_n, 120)
    END AS days_past_due
  FROM grid
)
SELECT
  account_id,
  snapshot_date,
  principal_balance,
  cast(round(principal_balance * 0.0625 / 365 * 30, 2) AS DECIMAL(14,2)) AS interest_accrued,
  days_past_due,
  -- FLAW #7, part 1: the bucket
  CASE WHEN days_past_due = 0  THEN 'CURRENT'
       WHEN days_past_due < 30 THEN '1-29'
       WHEN days_past_due < 60 THEN '30-59'
       WHEN days_past_due < 90 THEN '60-89'
       ELSE                        '90+'
  END AS dpd_bucket,
  -- FLAW #7, part 2: a SEPARATE lifecycle status. "Default" and "charge-off"
  -- are accounting events, not DPD thresholds - so "how many delinquent
  -- loans?" has four defensible answers depending on which you mean.
  CASE WHEN days_past_due = 0    THEN 'PERFORMING'
       WHEN days_past_due < 90   THEN 'DELINQUENT'
       WHEN days_past_due < 180  THEN 'DEFAULT'
       ELSE                           'CHARGED_OFF'
  END AS loan_status
FROM shaped;

ALTER TABLE {{CORE}}.fct_loan_balances ALTER COLUMN principal_balance
  COMMENT 'Outstanding principal AS OF snapshot_date. This table has ONE ROW PER ACCOUNT PER DAY - never SUM across dates. For a point-in-time loan book, filter to the latest snapshot_date.';
ALTER TABLE {{CORE}}.fct_loan_balances ALTER COLUMN days_past_due
  COMMENT 'Days past due as of snapshot_date. 0 means current.';
ALTER TABLE {{CORE}}.fct_loan_balances ALTER COLUMN dpd_bucket
  COMMENT 'Delinquency bucket. Values: CURRENT, 1-29, 30-59, 60-89, 90+. Meridian defines "delinquent" as 30+ days past due and "seriously delinquent" as 90+. Ask which one the user means.';
ALTER TABLE {{CORE}}.fct_loan_balances ALTER COLUMN loan_status
  COMMENT 'Accounting lifecycle status, DISTINCT from dpd_bucket. Values: PERFORMING, DELINQUENT, DEFAULT, CHARGED_OFF. "Default" and "charge-off" are accounting events and are NOT the same as being 30+ or 90+ days past due.';


-- ============================================================================
-- fct_applications  —  approval funnel and cycle time
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}.fct_applications
COMMENT 'Credit application funnel: submitted -> decisioned -> funded. Approval rate is decisions of APPROVED over all applications. Not every approved application is funded.'
AS
WITH ap AS (SELECT id AS n FROM range(1, 420001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('app-cust-', n)), 2100000) AS cust_n,
    pmod(hash(concat('app-prod-', n)), 20)      AS prod_n,
    pmod(hash(concat('app-day-',  n)), 730)     AS day_offset,
    pmod(hash(concat('app-dec-',  n)), 100)     AS dec_pick,
    pmod(hash(concat('app-chan-', n)), 100)     AS chan_pick,
    pmod(hash(concat('app-lag-',  n)), 14)      AS decision_lag,
    pmod(hash(concat('app-fund-', n)), 100)     AS fund_pick
  FROM ap
)
SELECT
  concat('APP', lpad(cast(n AS STRING), 8, '0'))            AS app_id,
  concat('C',   lpad(cast(cust_n + 1 AS STRING), 8, '0'))   AS customer_id,
  concat('P',   lpad(cast(prod_n + 1 AS STRING), 2, '0'))   AS product_id,
  cast(date_add(DATE'2024-10-01', day_offset) AS TIMESTAMP) AS submitted_ts,
  cast(date_add(DATE'2024-10-01', day_offset + decision_lag) AS TIMESTAMP) AS decision_ts,
  CASE WHEN dec_pick < 58 AND fund_pick < 82
       THEN cast(date_add(DATE'2024-10-01', day_offset + decision_lag + 2) AS TIMESTAMP)
       ELSE NULL END                                        AS funded_ts,
  CASE WHEN dec_pick < 58 THEN 'APPROVED'
       WHEN dec_pick < 88 THEN 'DECLINED'
       ELSE                    'WITHDRAWN' END              AS decision,
  CASE WHEN chan_pick < 46 THEN 'DIGITAL'
       WHEN chan_pick < 78 THEN 'BRANCH'
       WHEN chan_pick < 92 THEN 'CALL_CENTRE'
       ELSE                     'BROKER' END                AS channel
FROM calc;

ALTER TABLE {{CORE}}.fct_applications ALTER COLUMN decision
  COMMENT 'Underwriting decision. Values: APPROVED, DECLINED, WITHDRAWN. Approval rate = APPROVED / all applications, including WITHDRAWN.';
ALTER TABLE {{CORE}}.fct_applications ALTER COLUMN funded_ts
  COMMENT 'When the loan was actually funded. NULL if never funded - roughly 18% of APPROVED applications are never drawn down, so funded count < approved count.';
ALTER TABLE {{CORE}}.fct_applications ALTER COLUMN channel
  COMMENT 'Origination channel. Values: DIGITAL, BRANCH, CALL_CENTRE, BROKER.';


-- ============================================================================
-- fct_fraud_cases
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}.fct_fraud_cases
COMMENT 'Fraud and financial-crime cases. loss_amount is the realised loss in USD, zero for cases closed without loss.'
AS
WITH f AS (SELECT id AS n FROM range(1, 14001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('frd-acct-', n)), 2900000) AS acct_n,
    pmod(hash(concat('frd-day-',  n)), 730)     AS day_offset,
    pmod(hash(concat('frd-type-', n)), 6)       AS type_pick,
    pmod(hash(concat('frd-loss-', n)), 100)     AS loss_pick,
    pmod(hash(concat('frd-stat-', n)), 100)     AS stat_pick,
    pmod(hash(concat('frd-close-',n)), 60)      AS close_lag
  FROM f
)
SELECT
  concat('FC', lpad(cast(n AS STRING), 7, '0'))            AS case_id,
  concat('A',  lpad(cast(acct_n + 1 AS STRING), 9, '0'))   AS account_id,
  date_add(DATE'2024-10-01', day_offset)                   AS opened_date,
  CASE WHEN stat_pick < 84
       THEN date_add(DATE'2024-10-01', day_offset + close_lag)
       ELSE NULL END                                       AS closed_date,
  cast(CASE WHEN loss_pick < 38 THEN 0
            ELSE round(150 + loss_pick * 96.5, 2) END AS DECIMAL(14,2)) AS loss_amount,
  element_at(array('CARD_NOT_PRESENT','ACCOUNT_TAKEOVER','APPLICATION_FRAUD',
                   'CHECK_FRAUD','WIRE_FRAUD','FIRST_PARTY'), type_pick + 1)  AS fraud_type,
  CASE WHEN stat_pick < 84 THEN 'CLOSED' ELSE 'OPEN' END   AS status
FROM calc;

ALTER TABLE {{CORE}}.fct_fraud_cases ALTER COLUMN fraud_type
  COMMENT 'Fraud typology. Values: CARD_NOT_PRESENT, ACCOUNT_TAKEOVER, APPLICATION_FRAUD, CHECK_FRAUD, WIRE_FRAUD, FIRST_PARTY.';
ALTER TABLE {{CORE}}.fct_fraud_cases ALTER COLUMN loss_amount
  COMMENT 'Realised loss in USD. Zero for cases closed with no loss - about 38% of cases.';


-- ----------------------------------------------------------------------------
-- Row counts
-- ----------------------------------------------------------------------------
SELECT 'fct_transactions'  AS table_name, count(*) AS rows FROM {{CORE}}.fct_transactions
UNION ALL SELECT 'fct_reversals',      count(*) FROM {{CORE}}.fct_reversals
UNION ALL SELECT 'fct_loan_balances',  count(*) FROM {{CORE}}.fct_loan_balances
UNION ALL SELECT 'fct_applications',   count(*) FROM {{CORE}}.fct_applications
UNION ALL SELECT 'fct_fraud_cases',    count(*) FROM {{CORE}}.fct_fraud_cases
ORDER BY table_name;
