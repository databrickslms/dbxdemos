-- ============================================================================
-- Meridian Financial Group — 02. Dimensions
--
-- dim_date, dim_asset_class, dim_benchmark, dim_portfolio, dim_fund,
-- dim_advisor, dim_client, dim_account, dim_fx_rate.
--
-- All values derive from hash() of the row key rather than rand(), so the data
-- is identical for everyone and reproducible on re-run.
--
-- ANCHOR DATE: 2026-09-30. Ages and tenures are computed from this fixed date
-- rather than current_date, so the dataset does not drift over time.
-- ============================================================================


-- ============================================================================
-- dim_date  —  calendar with Meridian fiscal and reporting attributes
-- Covers 2024-10-01 to 2026-09-30.
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_date
COMMENT 'Date dimension with fiscal, calendar and reporting attributes.'
AS
WITH d AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS date_key
),
calc AS (
  SELECT
    date_key,
    year(date_key)  AS cal_y,
    month(date_key) AS cal_m,
    year(date_key) + CASE WHEN month(date_key) >= 10 THEN 1 ELSE 0 END AS fy_num,
    (pmod(month(date_key) + 2, 12) DIV 3) + 1 AS fq_num,
    pmod(month(date_key) + 2, 12) + 1         AS fm_num,
    CASE
      WHEN dayofweek(date_key) IN (1, 7) THEN false
      WHEN date_format(date_key, 'MM-dd') IN ('01-01','06-19','07-04','11-11','12-25') THEN false
      ELSE true
    END AS is_bd
  FROM d
),
reporting AS (
  -- Last business day of each month, computed once rather than per row.
  SELECT last_day(date_key) AS month_end, max(date_key) AS reporting_date
  FROM calc WHERE is_bd GROUP BY last_day(date_key)
)
SELECT
  c.date_key,
  concat('FY', cast(c.fy_num AS STRING))                              AS fiscal_year,
  concat('FY', cast(c.fy_num AS STRING), '-Q', cast(c.fq_num AS STRING)) AS fiscal_quarter,
  c.fm_num                                                            AS fiscal_month,
  c.cal_y                                                             AS calendar_year,
  c.cal_m                                                             AS calendar_month,
  concat(cast(c.cal_y AS STRING), '-Q', cast(quarter(c.date_key) AS STRING)) AS calendar_quarter,
  date_format(c.date_key, 'EEEE')                                     AS day_name,
  c.is_bd                                                             AS is_business_day,
  c.date_key = last_day(c.date_key)                                   AS is_month_end,
  c.date_key = r.reporting_date                                       AS is_reporting_date
FROM calc c
JOIN reporting r ON r.month_end = last_day(c.date_key);

ALTER TABLE {{CORE}}dim_date ALTER COLUMN fiscal_year
  COMMENT 'Fiscal year label.';
ALTER TABLE {{CORE}}dim_date ALTER COLUMN fiscal_quarter
  COMMENT 'Fiscal quarter label.';
ALTER TABLE {{CORE}}dim_date ALTER COLUMN calendar_quarter
  COMMENT 'Calendar quarter label.';
ALTER TABLE {{CORE}}dim_date ALTER COLUMN is_reporting_date
  COMMENT 'Last business day of the month.';
ALTER TABLE {{CORE}}dim_date ALTER COLUMN is_month_end
  COMMENT 'Last calendar day of the month.';


-- ============================================================================
-- dim_asset_class  —  asset classification
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_asset_class
COMMENT 'Asset class reference.'
AS
SELECT * FROM VALUES
  ('EQ_US',   'US Equity',              'EQUITY',      'EQUITY'),
  ('EQ_INTL', 'International Equity',   'EQUITY',      'EQUITY'),
  ('EQ_EM',   'Emerging Markets Equity','EQUITY',      'EQUITY'),
  ('FI_GOV',  'Government Bonds',       'FIXED_INCOME','DEBT'),
  ('FI_CORP', 'Corporate Bonds',        'FIXED_INCOME','DEBT'),
  ('FI_HY',   'High Yield',             'FIXED_INCOME','DEBT'),
  ('FI_MUNI', 'Municipal Bonds',        'FIXED_INCOME','DEBT'),
  ('MM_CASH', 'Cash and Equivalents',   'MONEY_MARKET','DEBT'),
  ('ALT_RE',  'Real Estate',            'ALTERNATIVE', 'POOLED_VEHICLE'),
  ('ALT_PE',  'Private Equity',         'ALTERNATIVE', 'POOLED_VEHICLE'),
  ('ALT_HF',  'Hedge Funds',            'ALTERNATIVE', 'POOLED_VEHICLE'),
  ('MULTI',   'Multi-Asset',            'MULTI_ASSET', 'POOLED_VEHICLE')
AS t(asset_class_code, asset_class_name, investment_class, regulatory_class);

ALTER TABLE {{CORE}}dim_asset_class ALTER COLUMN asset_class_code
  COMMENT 'Asset class code.';
ALTER TABLE {{CORE}}dim_asset_class ALTER COLUMN investment_class
  COMMENT 'Investment grouping.';
ALTER TABLE {{CORE}}dim_asset_class ALTER COLUMN regulatory_class
  COMMENT 'Regulatory reporting grouping.';


-- ============================================================================
-- dim_benchmark
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_benchmark
COMMENT 'Benchmark reference.'
AS
SELECT * FROM VALUES
  ('BM01','US Large Cap Index',        'EQ_US'),
  ('BM02','US Small Cap Index',        'EQ_US'),
  ('BM03','Developed ex-US Index',     'EQ_INTL'),
  ('BM04','Emerging Markets Index',    'EQ_EM'),
  ('BM05','Aggregate Bond Index',      'FI_CORP'),
  ('BM06','Government Bond Index',     'FI_GOV'),
  ('BM07','High Yield Index',          'FI_HY'),
  ('BM08','Municipal Bond Index',      'FI_MUNI'),
  ('BM09','Cash Benchmark',            'MM_CASH'),
  ('BM10','Global Real Estate Index',  'ALT_RE'),
  ('BM11','Balanced 60/40 Index',      'MULTI'),
  ('BM12','Target Allocation Index',   'MULTI')
AS t(benchmark_id, benchmark_name, asset_class_code);


-- ============================================================================
-- dim_portfolio  —  managed portfolios and mandates
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_portfolio
COMMENT 'Portfolio and mandate master.'
AS
WITH p AS (SELECT id AS n FROM range(1, 4501)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('pf-ac-',    n)), 12)   AS ac_pick,
    pmod(hash(concat('pf-disc-',  n)), 100)  AS disc_pick,
    pmod(hash(concat('pf-cur-',   n)), 100)  AS cur_pick,
    pmod(hash(concat('pf-incep-', n)), 7300) AS incep_off,
    pmod(hash(concat('pf-strat-', n)), 4)    AS strat_pick,
    pmod(hash(concat('pf-status-',n)), 100)  AS status_pick
  FROM p
)
SELECT
  concat('PF', lpad(cast(n AS STRING), 6, '0'))              AS portfolio_id,
  concat('Portfolio ', lpad(cast(n AS STRING), 6, '0'))      AS portfolio_name,
  element_at(array('EQ_US','EQ_INTL','EQ_EM','FI_GOV','FI_CORP','FI_HY','FI_MUNI',
                   'MM_CASH','ALT_RE','ALT_PE','ALT_HF','MULTI'), ac_pick + 1) AS asset_class_code,
  concat('BM', lpad(cast(ac_pick + 1 AS STRING), 2, '0'))    AS benchmark_id,
  element_at(array('ACTIVE','INDEX','ENHANCED_INDEX','MULTI_MANAGER'), strat_pick + 1) AS strategy,
  -- Roughly 72% of portfolios are discretionary; the rest are advisory only.
  CASE WHEN disc_pick < 72 THEN true ELSE false END          AS is_discretionary,
  CASE WHEN cur_pick < 78 THEN 'USD'
       WHEN cur_pick < 88 THEN 'EUR'
       WHEN cur_pick < 95 THEN 'GBP'
       ELSE 'JPY' END                                        AS base_currency,
  date_add(DATE'2006-01-01', incep_off)                      AS inception_date,
  CASE WHEN status_pick < 4 THEN 'CLOSED' ELSE 'OPEN' END    AS status
FROM calc;

ALTER TABLE {{CORE}}dim_portfolio ALTER COLUMN is_discretionary
  COMMENT 'True where Meridian has discretion over the assets.';
ALTER TABLE {{CORE}}dim_portfolio ALTER COLUMN strategy
  COMMENT 'Management strategy.';
ALTER TABLE {{CORE}}dim_portfolio ALTER COLUMN base_currency
  COMMENT 'Portfolio reporting currency.';
ALTER TABLE {{CORE}}dim_portfolio ALTER COLUMN status
  COMMENT 'Portfolio status.';


-- ============================================================================
-- dim_fund  —  pooled vehicles and share classes
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_fund
COMMENT 'Fund and share class master.'
AS
WITH f AS (SELECT id AS n FROM range(1, 181)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('fd-ac-',  n)), 12)  AS ac_pick,
    pmod(hash(concat('fd-veh-', n)), 100) AS veh_pick,
    pmod(hash(concat('fd-sc-',  n)), 5)   AS sc_pick,
    pmod(hash(concat('fd-fee-', n)), 90)  AS fee_pick
  FROM f
)
SELECT
  concat('FD', lpad(cast(n AS STRING), 4, '0'))            AS fund_id,
  concat('Meridian Fund ', lpad(cast(n AS STRING), 4, '0')) AS fund_name,
  element_at(array('A','C','F','I','R'), sc_pick + 1)      AS share_class,
  element_at(array('EQ_US','EQ_INTL','EQ_EM','FI_GOV','FI_CORP','FI_HY','FI_MUNI',
                   'MM_CASH','ALT_RE','ALT_PE','ALT_HF','MULTI'), ac_pick + 1) AS asset_class_code,
  CASE WHEN veh_pick < 58 THEN 'MUTUAL_FUND'
       WHEN veh_pick < 78 THEN 'ETF'
       WHEN veh_pick < 92 THEN 'SMA'
       ELSE 'CIT' END                                      AS vehicle_type,
  cast((10 + fee_pick) / 10000.0 AS DECIMAL(6,4))          AS expense_ratio
FROM calc;

ALTER TABLE {{CORE}}dim_fund ALTER COLUMN share_class
  COMMENT 'Share class.';
ALTER TABLE {{CORE}}dim_fund ALTER COLUMN vehicle_type
  COMMENT 'Vehicle type.';
ALTER TABLE {{CORE}}dim_fund ALTER COLUMN expense_ratio
  COMMENT 'Annual expense ratio as a decimal.';


-- ============================================================================
-- dim_advisor  —  distribution relationships
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_advisor
COMMENT 'Advisor and distribution relationship master.'
AS
WITH a AS (SELECT id AS n FROM range(1, 3401)),
calc AS (
  SELECT
    n,
    CASE pmod(hash(concat('ad-reg-', n)), 10)
      WHEN 0 THEN 'NE' WHEN 1 THEN 'NE' WHEN 2 THEN 'NE'
      WHEN 3 THEN 'SE' WHEN 4 THEN 'SE'
      WHEN 5 THEN 'MW' WHEN 6 THEN 'MW'
      ELSE 'WEST' END                        AS region,
    pmod(hash(concat('ad-st-', n)), 4)       AS state_pick,
    pmod(hash(concat('ad-ch-', n)), 100)     AS ch_pick,
    pmod(hash(concat('ad-on-', n)), 5475)    AS on_off
  FROM a
)
SELECT
  concat('AD', lpad(cast(n AS STRING), 5, '0'))  AS advisor_id,
  concat('Advisor ', lpad(cast(n AS STRING), 5, '0')) AS advisor_name,
  region,
  CASE region
    WHEN 'NE'   THEN element_at(array('NY','MA','NJ','PA'), state_pick + 1)
    WHEN 'SE'   THEN element_at(array('FL','GA','NC','TN'), state_pick + 1)
    WHEN 'MW'   THEN element_at(array('IL','OH','MI','MN'), state_pick + 1)
    ELSE             element_at(array('CA','WA','AZ','CO'), state_pick + 1)
  END AS state,
  CASE WHEN ch_pick < 44 THEN 'INTERMEDIARY'
       WHEN ch_pick < 68 THEN 'INSTITUTIONAL'
       WHEN ch_pick < 88 THEN 'RETIREMENT'
       ELSE 'PRIVATE_CLIENT' END                 AS channel,
  date_add(DATE'2011-10-01', on_off)             AS onboarded_date
FROM calc;

ALTER TABLE {{CORE}}dim_advisor ALTER COLUMN region
  COMMENT 'Coverage region code.';
ALTER TABLE {{CORE}}dim_advisor ALTER COLUMN state
  COMMENT 'State code.';
ALTER TABLE {{CORE}}dim_advisor ALTER COLUMN channel
  COMMENT 'Distribution channel.';


-- ============================================================================
-- dim_client  —  investors and institutions
-- All values are synthetic. Emails use example.com (RFC 2606 reserved) and
-- ssn_last4 is a hashed 4-digit string derived from nothing real.
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_client
COMMENT 'Client master. Synthetic data.'
AS
WITH c AS (SELECT id AS n FROM range(1, 2100001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('cl-seg-',  n)), 100)   AS seg_pick,
    pmod(hash(concat('cl-ten-',  n)), 240)   AS tenure_m,
    pmod(hash(concat('cl-adv-',  n)), 3400)  AS adv_n,
    pmod(hash(concat('cl-ssn-',  n)), 10000) AS ssn4,
    pmod(hash(concat('cl-age-',  n)), 67)    AS age_off,
    pmod(hash(concat('cl-inc-',  n)), 240)   AS inc_pick,
    pmod(hash(concat('cl-dom-',  n)), 100)   AS dom_pick
  FROM c
)
SELECT
  concat('CL', lpad(cast(n AS STRING), 8, '0'))  AS client_id,
  CASE WHEN seg_pick < 52 THEN 'INTERMEDIARY'
       WHEN seg_pick < 74 THEN 'RETIREMENT'
       WHEN seg_pick < 90 THEN 'INSTITUTIONAL'
       ELSE 'PRIVATE_CLIENT' END                 AS client_segment,
  concat('AD', lpad(cast(adv_n + 1 AS STRING), 5, '0')) AS advisor_id,
  CASE WHEN dom_pick < 86 THEN 'US'
       WHEN dom_pick < 93 THEN 'CA'
       WHEN dom_pick < 97 THEN 'GB'
       ELSE 'JP' END                             AS domicile,
  tenure_m                                       AS tenure_months,
  lpad(cast(ssn4 AS STRING), 4, '0')             AS ssn_last4,
  concat('client', cast(n AS STRING), '@example.com') AS email,
  date_add(DATE'2026-09-30', -1 * ((18 + age_off) * 365 + pmod(hash(concat('cl-dob-', n)), 365))) AS dob,
  cast(50000 + inc_pick * 3750 AS DECIMAL(14,2)) AS annual_income
FROM calc;

ALTER TABLE {{CORE}}dim_client ALTER COLUMN client_segment
  COMMENT 'Client segment.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN domicile
  COMMENT 'Country of domicile.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN tenure_months
  COMMENT 'Relationship tenure in months.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN ssn_last4
  COMMENT 'Last four digits of tax identifier.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN email
  COMMENT 'Contact email.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN dob
  COMMENT 'Date of birth.';
ALTER TABLE {{CORE}}dim_client ALTER COLUMN annual_income
  COMMENT 'Reported annual income, USD.';


-- ============================================================================
-- dim_account  —  the join hub
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_account
COMMENT 'Account master.'
AS
WITH a AS (SELECT id AS n FROM range(1, 2900001)),
calc AS (
  SELECT
    n,
    pmod(hash(concat('ac-cl-',  n)), 2100000) AS cl_n,
    pmod(hash(concat('ac-pf-',  n)), 4500)    AS pf_n,
    pmod(hash(concat('ac-fd-',  n)), 180)     AS fd_n,
    pmod(hash(concat('ac-veh-', n)), 100)     AS veh_pick,
    pmod(hash(concat('ac-op-',  n)), 5475)    AS op_off,
    pmod(hash(concat('ac-st-',  n)), 100)     AS st_pick
  FROM a
)
SELECT
  concat('AC', lpad(cast(n AS STRING), 9, '0'))            AS account_id,
  concat('CL', lpad(cast(cl_n + 1 AS STRING), 8, '0'))     AS client_id,
  -- Accounts hold either a separately managed portfolio or a pooled fund.
  CASE WHEN veh_pick < 34
       THEN concat('PF', lpad(cast(pf_n + 1 AS STRING), 6, '0')) ELSE NULL END AS portfolio_id,
  CASE WHEN veh_pick >= 34
       THEN concat('FD', lpad(cast(fd_n + 1 AS STRING), 4, '0')) ELSE NULL END AS fund_id,
  date_add(DATE'2011-10-01', op_off)                       AS opened_date,
  CASE WHEN st_pick < 7
       THEN date_add(DATE'2011-10-01', op_off + 400 + pmod(hash(concat('ac-cd-', n)), 1500))
       ELSE NULL END                                       AS closed_date,
  CASE WHEN st_pick < 7 THEN 'CLOSED' ELSE 'OPEN' END      AS status
FROM calc;

ALTER TABLE {{CORE}}dim_account ALTER COLUMN portfolio_id
  COMMENT 'Separately managed portfolio, NULL for pooled-vehicle accounts.';
ALTER TABLE {{CORE}}dim_account ALTER COLUMN fund_id
  COMMENT 'Pooled vehicle, NULL for separately managed accounts.';
ALTER TABLE {{CORE}}dim_account ALTER COLUMN status
  COMMENT 'Account status.';


-- ============================================================================
-- dim_fx_rate  —  daily rates to USD
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}dim_fx_rate
COMMENT 'Daily FX rates to USD.'
AS
WITH d AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS rate_date
),
cur AS (SELECT explode(array('USD','EUR','GBP','JPY','CAD')) AS currency)
SELECT
  cur.currency,
  d.rate_date,
  CASE cur.currency
    WHEN 'USD' THEN cast(1.0 AS DECIMAL(12,6))
    WHEN 'EUR' THEN cast(1.085 + (pmod(hash(concat('fx-eur-', d.rate_date)), 40) - 20) / 2000.0 AS DECIMAL(12,6))
    WHEN 'GBP' THEN cast(1.265 + (pmod(hash(concat('fx-gbp-', d.rate_date)), 60) - 30) / 2000.0 AS DECIMAL(12,6))
    WHEN 'JPY' THEN cast(0.0066 + (pmod(hash(concat('fx-jpy-', d.rate_date)), 20) - 10) / 200000.0 AS DECIMAL(12,6))
    ELSE            cast(0.730 + (pmod(hash(concat('fx-cad-', d.rate_date)), 40) - 20) / 2000.0 AS DECIMAL(12,6))
  END AS usd_rate
FROM d CROSS JOIN cur;

ALTER TABLE {{CORE}}dim_fx_rate ALTER COLUMN usd_rate
  COMMENT 'Rate to USD.';


-- ----------------------------------------------------------------------------
-- Row counts
-- ----------------------------------------------------------------------------
SELECT 'dim_date' AS table_name, count(*) AS rows FROM {{CORE}}dim_date
UNION ALL SELECT 'dim_asset_class', count(*) FROM {{CORE}}dim_asset_class
UNION ALL SELECT 'dim_benchmark',   count(*) FROM {{CORE}}dim_benchmark
UNION ALL SELECT 'dim_portfolio',   count(*) FROM {{CORE}}dim_portfolio
UNION ALL SELECT 'dim_fund',        count(*) FROM {{CORE}}dim_fund
UNION ALL SELECT 'dim_advisor',     count(*) FROM {{CORE}}dim_advisor
UNION ALL SELECT 'dim_client',      count(*) FROM {{CORE}}dim_client
UNION ALL SELECT 'dim_account',     count(*) FROM {{CORE}}dim_account
UNION ALL SELECT 'dim_fx_rate',     count(*) FROM {{CORE}}dim_fx_rate
ORDER BY table_name;
