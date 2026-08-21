-- ============================================================================
-- Meridian Financial Group — 02. Dimensions
--
-- Plants four of the nine flaws:
--   #2  fiscal year starts 1 October          -> dim_date
--   #3  region and state are CODES, not names -> dim_branch
--   #5  two competing product hierarchies     -> dim_product
--   #8  PII columns present and unmasked      -> dim_customer
--   #9  multi-currency needs as-of-date FX    -> dim_fx_rate
--
-- All values derive from hash() of the row key, never rand(), so every learner
-- gets byte-identical data and benchmark ground-truth SQL stays valid.
--
-- ANCHOR DATE: 2026-09-30 (last day of FY2026). Ages and tenures are computed
-- from this fixed date rather than current_date, or the data would drift and
-- benchmark answers would rot.
-- ============================================================================


-- ============================================================================
-- dim_date  —  FLAW #2: fiscal year begins 1 October
-- FY2025 = 2024-10-01 .. 2025-09-30
-- FY2026 = 2025-10-01 .. 2026-09-30
-- Two complete fiscal years, so "this year vs last year" questions work.
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_date
COMMENT 'Calendar with Meridian fiscal attributes. Meridian fiscal year starts 1 October: FY2026 = 2025-10-01 to 2026-09-30. Fiscal and calendar columns are both present and will disagree.'
AS
WITH d AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS date_key
),
calc AS (
  SELECT
    date_key,
    year(date_key)  AS cal_y,
    month(date_key) AS cal_m,
    -- Oct-Dec belong to the NEXT fiscal year
    year(date_key) + CASE WHEN month(date_key) >= 10 THEN 1 ELSE 0 END AS fy_num,
    -- Fiscal quarter: Q1=Oct-Dec, Q2=Jan-Mar, Q3=Apr-Jun, Q4=Jul-Sep
    (pmod(month(date_key) + 2, 12) DIV 3) + 1 AS fq_num,
    -- Fiscal month 1..12 where 1 = October
    pmod(month(date_key) + 2, 12) + 1 AS fm_num
  FROM d
)
SELECT
  date_key,
  concat('FY', cast(fy_num AS STRING))                                AS fiscal_year,
  concat('FY', cast(fy_num AS STRING), '-Q', cast(fq_num AS STRING))   AS fiscal_quarter,
  fm_num                                                              AS fiscal_month,
  cal_y                                                               AS calendar_year,
  cal_m                                                               AS calendar_month,
  date_format(date_key, 'EEEE')                                       AS day_name,
  -- Approximate US banking calendar: weekends plus the fixed-date federal
  -- holidays. Good enough to make "business days" a meaningful filter; not a
  -- substitute for a real holiday calendar.
  CASE
    WHEN dayofweek(date_key) IN (1, 7) THEN false
    WHEN date_format(date_key, 'MM-dd') IN
         ('01-01','06-19','07-04','11-11','12-25') THEN false
    ELSE true
  END                                                                 AS is_business_day
FROM calc;

ALTER TABLE {{CATALOG}}.core.dim_date ALTER COLUMN date_key
  COMMENT 'Calendar date. One row per day.';
ALTER TABLE {{CATALOG}}.core.dim_date ALTER COLUMN fiscal_year
  COMMENT 'Meridian fiscal year, format FY2026. The fiscal year STARTS 1 OCTOBER, so FY2026 runs 2025-10-01 to 2026-09-30. "Last year" means the prior FISCAL year unless the user says "calendar year".';
ALTER TABLE {{CATALOG}}.core.dim_date ALTER COLUMN fiscal_quarter
  COMMENT 'Meridian fiscal quarter, format FY2026-Q3. Q1 = Oct-Dec, Q2 = Jan-Mar, Q3 = Apr-Jun, Q4 = Jul-Sep.';
ALTER TABLE {{CATALOG}}.core.dim_date ALTER COLUMN calendar_year
  COMMENT 'Calendar year. Use ONLY when the user explicitly asks for calendar periods; otherwise use fiscal_year.';
ALTER TABLE {{CATALOG}}.core.dim_date ALTER COLUMN is_business_day
  COMMENT 'False for weekends and fixed-date US federal holidays.';


-- ============================================================================
-- dim_branch  —  FLAW #3: region and state are stored as CODES
-- Users say "Northeast", "the West Coast", "California".
-- The table holds NE, WEST, CA. Without entity matching, Genie filters on the
-- spoken form, matches nothing, and returns a confident zero.
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_branch
COMMENT 'Meridian branch network, 340 branches. Region and state are stored as SHORT CODES, not the names people say out loud.'
AS
WITH b AS (SELECT id AS n FROM range(1, 341)),
assigned AS (
  SELECT
    n,
    -- Deterministic region assignment, weighted toward NE and WEST
    CASE pmod(hash(concat('branch-region-', n)), 10)
      WHEN 0 THEN 'NE' WHEN 1 THEN 'NE' WHEN 2 THEN 'NE'
      WHEN 3 THEN 'SE' WHEN 4 THEN 'SE'
      WHEN 5 THEN 'MW' WHEN 6 THEN 'MW'
      ELSE 'WEST'
    END AS region,
    pmod(hash(concat('branch-state-', n)), 4)   AS state_pick,
    pmod(hash(concat('branch-chan-', n)), 10)   AS chan_pick,
    pmod(hash(concat('branch-open-', n)), 7300) AS open_offset
  FROM b
)
SELECT
  concat('BR', lpad(cast(n AS STRING), 4, '0')) AS branch_id,
  concat('Branch ', lpad(cast(n AS STRING), 4, '0')) AS branch_name,
  region,
  -- States are real US codes, mapped to their actual region
  CASE region
    WHEN 'NE'   THEN element_at(array('NY','MA','NJ','PA'), state_pick + 1)
    WHEN 'SE'   THEN element_at(array('FL','GA','NC','TN'), state_pick + 1)
    WHEN 'MW'   THEN element_at(array('IL','OH','MI','MN'), state_pick + 1)
    ELSE             element_at(array('CA','WA','AZ','CO'), state_pick + 1)
  END AS state,
  CASE WHEN chan_pick < 7 THEN 'RETAIL'
       WHEN chan_pick < 9 THEN 'COMMERCIAL'
       ELSE 'PRIVATE_CLIENT' END AS channel,
  date_add(DATE'2006-01-01', open_offset) AS opened_date
FROM assigned;

ALTER TABLE {{CATALOG}}.core.dim_branch ALTER COLUMN region
  COMMENT 'Sales region CODE. Values: NE, SE, MW, WEST. Users say "Northeast" (NE), "Southeast" (SE), "Midwest" (MW), "the West" or "West Coast" (WEST).';
ALTER TABLE {{CATALOG}}.core.dim_branch ALTER COLUMN state
  COMMENT 'Two-letter US state CODE, e.g. CA, NY, TX. Users say the full state name ("California"). Enable entity matching on this column.';
ALTER TABLE {{CATALOG}}.core.dim_branch ALTER COLUMN channel
  COMMENT 'Branch servicing model. Values: RETAIL, COMMERCIAL, PRIVATE_CLIENT.';


-- ============================================================================
-- dim_product  —  FLAW #5: two competing hierarchies
-- product_category   = how the business talks about products
-- regulatory_product_class = how they roll up for Basel/regulatory reporting
-- Both are correct. Leaving both visible produces two different answers to
-- "revenue by product", and nobody can tell which one they got.
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_product
COMMENT 'Product master. Carries TWO hierarchies that do not align: product_category (business view) and regulatory_product_class (Basel reporting view). Expose only one to an agent.'
AS
SELECT * FROM VALUES
  ('P01','Everyday Checking',            'DEPOSITS','RETAIL_DEPOSIT'),
  ('P02','Premier Checking',             'DEPOSITS','RETAIL_DEPOSIT'),
  ('P03','High-Yield Savings',           'DEPOSITS','RETAIL_DEPOSIT'),
  ('P04','12-Month CD',                  'DEPOSITS','RETAIL_DEPOSIT'),
  ('P05','Money Market',                 'DEPOSITS','RETAIL_DEPOSIT'),
  ('P06','Business Checking',            'DEPOSITS','CORPORATE'),
  ('P07','Rewards Credit Card',          'CARDS','QUALIFYING_REVOLVING'),
  ('P08','Cashback Credit Card',         'CARDS','QUALIFYING_REVOLVING'),
  ('P09','Secured Credit Card',          'CARDS','OTHER_RETAIL'),
  ('P10','Debit Card',                   'CARDS','RETAIL_DEPOSIT'),
  ('P11','Commercial Card',              'CARDS','CORPORATE'),
  ('P12','30-Year Fixed Mortgage',       'LENDING','RESIDENTIAL_MORTGAGE'),
  ('P13','15-Year Fixed Mortgage',       'LENDING','RESIDENTIAL_MORTGAGE'),
  ('P14','HELOC',                        'LENDING','RESIDENTIAL_MORTGAGE'),
  ('P15','Auto Loan',                    'LENDING','OTHER_RETAIL'),
  ('P16','Personal Loan',                'LENDING','OTHER_RETAIL'),
  ('P17','Small Business Term Loan',     'LENDING','CORPORATE'),
  ('P18','Managed Portfolio',            'WEALTH','OFF_BALANCE_SHEET'),
  ('P19','Advisory Account',             'WEALTH','OFF_BALANCE_SHEET'),
  ('P20','Traditional IRA',              'WEALTH','OFF_BALANCE_SHEET')
AS t(product_id, product_name, product_category, regulatory_product_class);

ALTER TABLE {{CATALOG}}.core.dim_product ALTER COLUMN product_category
  COMMENT 'BUSINESS product hierarchy. Values: DEPOSITS, CARDS, LENDING, WEALTH. This is the one business users mean by "product". Prefer this and hide regulatory_product_class.';
ALTER TABLE {{CATALOG}}.core.dim_product ALTER COLUMN regulatory_product_class
  COMMENT 'REGULATORY (Basel) product hierarchy used for capital reporting. Does NOT align with product_category - a Debit Card is CARDS here but RETAIL_DEPOSIT there. Never mix the two in one rollup.';


-- ============================================================================
-- dim_customer  —  FLAW #8: PII columns, deliberately unprotected
-- ssn_last4, email, dob and annual_income all sit here in the clear so that
-- Module 6 can demonstrate column masks doing real work, and demonstrate a
-- text instruction ("never show PII") failing to.
--
-- Every value is synthetic. Emails use example.com (RFC 2606 reserved) and
-- ssn_last4 is a hashed 4-digit string, not derived from anything real.
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_customer
COMMENT 'Retail and commercial customers, 2.1M rows. CONTAINS PII: ssn_last4, email, dob, annual_income. All values are synthetic. Protect with Unity Catalog column masks, never with agent instructions.'
AS
WITH c AS (SELECT id AS n FROM range(1, 2100001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('cust-seg-',    n)), 100)  AS seg_pick,
    pmod(hash(concat('cust-tenure-', n)), 240)  AS tenure_m,
    pmod(hash(concat('cust-branch-', n)), 340)  AS branch_n,
    pmod(hash(concat('cust-ssn-',    n)), 10000) AS ssn4,
    pmod(hash(concat('cust-age-',    n)), 67)   AS age_offset,
    pmod(hash(concat('cust-inc-',    n)), 240)  AS inc_pick
  FROM c
)
SELECT
  concat('C', lpad(cast(n AS STRING), 8, '0')) AS customer_id,
  CASE WHEN seg_pick < 62 THEN 'MASS'
       WHEN seg_pick < 84 THEN 'AFFLUENT'
       WHEN seg_pick < 94 THEN 'PRIVATE'
       ELSE 'COMMERCIAL' END                   AS segment,
  tenure_m                                     AS tenure_months,
  concat('BR', lpad(cast(branch_n + 1 AS STRING), 4, '0')) AS home_branch_id,
  lpad(cast(ssn4 AS STRING), 4, '0')           AS ssn_last4,
  concat('customer', cast(n AS STRING), '@example.com')    AS email,
  -- Ages 18-84 as of the 2026-09-30 anchor
  date_add(DATE'2026-09-30', -1 * ((18 + age_offset) * 365 + pmod(hash(concat('cust-dob-', n)), 365))) AS dob,
  cast(25000 + inc_pick * 1250 AS DECIMAL(12,2)) AS annual_income
FROM calc;

ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN segment
  COMMENT 'Customer segment. Values: MASS, AFFLUENT, PRIVATE, COMMERCIAL.';
ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN tenure_months
  COMMENT 'Months since the customer relationship began, as of 2026-09-30.';
ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN ssn_last4
  COMMENT 'PII. Last four digits of tax identifier (synthetic). Must be masked. Never expose in an answer.';
ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN email
  COMMENT 'PII. Contact email (synthetic, example.com). Must be masked. Never expose in an answer.';
ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN dob
  COMMENT 'PII. Date of birth (synthetic). Must be masked. Use age bands for analysis instead.';
ALTER TABLE {{CATALOG}}.core.dim_customer ALTER COLUMN annual_income
  COMMENT 'PII. Self-reported annual income in USD (synthetic). Restricted - finance roles only.';


-- ============================================================================
-- dim_account  —  the join hub
-- Every fact joins to a dimension THROUGH this table. Getting its cardinality
-- wrong is how "revenue by region" quietly multiplies (Module 9).
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_account
COMMENT 'Account master, ~2.9M rows. The join hub: transactions and balances reach customer, branch and product through this table.'
AS
WITH a AS (SELECT id AS n FROM range(1, 2900001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('acct-cust-',   n)), 2100000) AS cust_n,
    pmod(hash(concat('acct-prod-',   n)), 20)      AS prod_n,
    pmod(hash(concat('acct-branch-', n)), 340)     AS branch_n,
    pmod(hash(concat('acct-open-',   n)), 5475)    AS open_offset,
    pmod(hash(concat('acct-status-', n)), 100)     AS status_pick
  FROM a
)
SELECT
  concat('A', lpad(cast(n AS STRING), 9, '0'))               AS account_id,
  concat('C', lpad(cast(cust_n + 1 AS STRING), 8, '0'))      AS customer_id,
  concat('P', lpad(cast(prod_n + 1 AS STRING), 2, '0'))      AS product_id,
  concat('BR', lpad(cast(branch_n + 1 AS STRING), 4, '0'))   AS branch_id,
  date_add(DATE'2011-10-01', open_offset)                    AS opened_date,
  CASE WHEN status_pick < 8
       THEN date_add(DATE'2011-10-01', open_offset + 400 + pmod(hash(concat('acct-close-', n)), 1500))
       ELSE NULL END                                         AS closed_date,
  CASE WHEN status_pick < 8 THEN 'CLOSED' ELSE 'OPEN' END    AS status
FROM calc;

ALTER TABLE {{CATALOG}}.core.dim_account ALTER COLUMN status
  COMMENT 'Account status. Values: OPEN, CLOSED. Roughly 8% are CLOSED. Exclude CLOSED accounts from "active customer" style questions.';
ALTER TABLE {{CATALOG}}.core.dim_account ALTER COLUMN closed_date
  COMMENT 'Date the account was closed, NULL while open.';


-- ============================================================================
-- dim_fx_rate  —  FLAW #9: multi-currency needs an as-of-date join
-- Commercial transactions settle in CAD and GBP. Summing amount across
-- currencies without converting produces a number that does not tie to finance.
-- ============================================================================
CREATE OR REPLACE TABLE {{CATALOG}}.core.dim_fx_rate
COMMENT 'Daily FX rates to USD. Transactions in CAD or GBP must be converted using the rate AS OF the transaction date, not the latest rate.'
AS
WITH d AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS rate_date
),
cur AS (SELECT explode(array('USD','CAD','GBP')) AS currency)
SELECT
  cur.currency,
  d.rate_date,
  CASE cur.currency
    WHEN 'USD' THEN cast(1.0 AS DECIMAL(12,6))
    -- Small deterministic drift around a plausible central rate
    WHEN 'CAD' THEN cast(0.730 + (pmod(hash(concat('fx-cad-', d.rate_date)), 40) - 20) / 2000.0 AS DECIMAL(12,6))
    ELSE            cast(1.265 + (pmod(hash(concat('fx-gbp-', d.rate_date)), 60) - 30) / 2000.0 AS DECIMAL(12,6))
  END AS usd_rate
FROM d CROSS JOIN cur;

ALTER TABLE {{CATALOG}}.core.dim_fx_rate ALTER COLUMN usd_rate
  COMMENT 'Multiply a native-currency amount by this to get USD. Join on BOTH currency AND the transaction date.';


-- ----------------------------------------------------------------------------
-- Row counts
-- ----------------------------------------------------------------------------
SELECT 'dim_date'     AS table_name, count(*) AS rows FROM {{CATALOG}}.core.dim_date
UNION ALL SELECT 'dim_branch',   count(*) FROM {{CATALOG}}.core.dim_branch
UNION ALL SELECT 'dim_product',  count(*) FROM {{CATALOG}}.core.dim_product
UNION ALL SELECT 'dim_customer', count(*) FROM {{CATALOG}}.core.dim_customer
UNION ALL SELECT 'dim_account',  count(*) FROM {{CATALOG}}.core.dim_account
UNION ALL SELECT 'dim_fx_rate',  count(*) FROM {{CATALOG}}.core.dim_fx_rate
ORDER BY table_name;
