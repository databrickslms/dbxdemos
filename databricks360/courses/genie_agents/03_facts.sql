-- ============================================================================
-- Meridian Financial Group — 03. Facts
--
-- fct_aum_snapshot, fct_flows, fct_performance.
--
-- TIER: the line marked  -- << TIER >>  controls row volume.
--   Small  20000000   default.
--   Large  900000000  for the performance module.
-- ============================================================================


-- ============================================================================
-- fct_aum_snapshot  —  market value per account per day
-- Roughly 1.5M rows per month.
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}fct_aum_snapshot
COMMENT 'Account market value snapshot.'
AS
WITH managed AS (
  -- The managed book: a stratified sample of accounts carried daily.
  SELECT a.account_id, a.opened_date, a.portfolio_id, a.fund_id
  FROM {{CORE}}dim_account a
  WHERE pmod(hash(concat('aum-pick-', a.account_id)), 1000) < 18
),
days AS (
  SELECT explode(sequence(DATE'2024-10-01', DATE'2026-09-30', INTERVAL 1 DAY)) AS snapshot_date
),
grid AS (
  SELECT
    m.account_id,
    m.portfolio_id,
    m.fund_id,
    d.snapshot_date,
    datediff(d.snapshot_date, DATE'2024-10-01')                        AS day_n,
    pmod(hash(concat('aum-base-',  m.account_id)), 900)                AS base_pick,
    pmod(hash(concat('aum-drift-', m.account_id)), 200)                AS drift_pick,
    pmod(hash(concat('aum-away-',  m.account_id)), 100)                AS away_pick,
    pmod(hash(concat('aum-cur-',   m.account_id)), 100)                AS cur_pick
  FROM managed m CROSS JOIN days d
  WHERE d.snapshot_date >= m.opened_date
)
SELECT
  account_id,
  portfolio_id,
  fund_id,
  snapshot_date,
  CASE WHEN cur_pick < 80 THEN 'USD'
       WHEN cur_pick < 89 THEN 'EUR'
       WHEN cur_pick < 95 THEN 'GBP'
       ELSE 'JPY' END                                                  AS local_currency,
  -- Base value grows with a per-account drift plus a market-wide cycle.
  cast(round(
        (25000 + base_pick * 4200)
        * (1 + (drift_pick - 100) / 20000.0 * day_n / 100.0)
        * (1 + sin(day_n / 58.0) / 22.0)
      , 2) AS DECIMAL(18,2))                                           AS market_value_local,
  -- Assets Meridian reports on but does not manage. Present for roughly a
  -- fifth of accounts and zero elsewhere.
  cast(CASE WHEN away_pick < 21
            THEN round((25000 + base_pick * 4200) * (away_pick / 40.0), 2)
            ELSE 0 END AS DECIMAL(18,2))                               AS held_away_value_local,
  cast(1000 + pmod(hash(concat('aum-units-', account_id)), 90000) AS DECIMAL(18,4)) AS units
FROM grid;

ALTER TABLE {{CORE}}fct_aum_snapshot ALTER COLUMN market_value_local
  COMMENT 'Market value in the account local currency.';
ALTER TABLE {{CORE}}fct_aum_snapshot ALTER COLUMN held_away_value_local
  COMMENT 'Value of assets reported on but not managed by Meridian.';
ALTER TABLE {{CORE}}fct_aum_snapshot ALTER COLUMN local_currency
  COMMENT 'Currency of the values on this row.';
ALTER TABLE {{CORE}}fct_aum_snapshot ALTER COLUMN units
  COMMENT 'Units or shares held.';


-- ============================================================================
-- fct_flows  —  subscriptions, redemptions, exchanges and transfers
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}fct_flows
COMMENT 'Client money movement events.'
AS
WITH f AS (
  SELECT id AS n FROM range(1, {{TXN_COUNT}} + 1)   -- << TIER >> set by the tier in manifest.json
),
calc AS (
  SELECT
    n,
    pmod(hash(concat('fl-acct-', n)), 2900000) AS acct_n,
    pmod(hash(concat('fl-day-',  n)), 730)     AS day_off,
    pmod(hash(concat('fl-amt-',  n)), 100000)  AS amt_pick,
    pmod(hash(concat('fl-type-', n)), 1000)    AS type_pick,
    pmod(hash(concat('fl-stat-', n)), 1000)    AS stat_pick,
    pmod(hash(concat('fl-lag-',  n)), 3)       AS settle_lag
  FROM f
),
shaped AS (
  SELECT
    n,
    concat('FL', lpad(cast(n AS STRING), 12, '0'))            AS flow_id,
    concat('AC', lpad(cast(acct_n + 1 AS STRING), 9, '0'))    AS account_id,
    date_add(DATE'2024-10-01', day_off)                       AS trade_date,
    date_add(DATE'2024-10-01', day_off + 1 + settle_lag)      AS settlement_date,
    cast(
      CASE WHEN amt_pick < 72000 THEN 250   + amt_pick / 90.0
           WHEN amt_pick < 96000 THEN 4000  + amt_pick / 12.0
           ELSE                       40000 + amt_pick / 2.0
      END AS DECIMAL(18,2))                                   AS amount_local,
    CASE WHEN type_pick < 360 THEN 'SUBSCRIPTION'
         WHEN type_pick < 640 THEN 'REDEMPTION'
         WHEN type_pick < 760 THEN 'EXCHANGE_IN'
         WHEN type_pick < 880 THEN 'EXCHANGE_OUT'
         WHEN type_pick < 945 THEN 'TRANSFER_IN'
         ELSE                      'TRANSFER_OUT'
    END                                                       AS flow_type,
    CASE WHEN stat_pick < 930 THEN 'SETTLED'
         WHEN stat_pick < 975 THEN 'PENDING'
         ELSE                      'CANCELLED'
    END                                                       AS status
  FROM calc
)
SELECT
  s.flow_id,
  s.account_id,
  s.trade_date,
  s.settlement_date,
  s.flow_type,
  s.amount_local,
  coalesce(p.base_currency, 'USD')                            AS local_currency,
  s.status
FROM shaped s
JOIN {{CORE}}dim_account   a ON a.account_id = s.account_id
LEFT JOIN {{CORE}}dim_portfolio p ON p.portfolio_id = a.portfolio_id;

ALTER TABLE {{CORE}}fct_flows ALTER COLUMN flow_type
  COMMENT 'Type of money movement.';
ALTER TABLE {{CORE}}fct_flows ALTER COLUMN status
  COMMENT 'Settlement status.';
ALTER TABLE {{CORE}}fct_flows ALTER COLUMN trade_date
  COMMENT 'Date the instruction was placed.';
ALTER TABLE {{CORE}}fct_flows ALTER COLUMN settlement_date
  COMMENT 'Date the money moved.';
ALTER TABLE {{CORE}}fct_flows ALTER COLUMN amount_local
  COMMENT 'Amount in the local currency of this row.';


-- ============================================================================
-- fct_performance  —  returns by portfolio and period
-- ============================================================================
CREATE OR REPLACE TABLE {{CORE}}fct_performance
COMMENT 'Portfolio return measures by period.'
AS
WITH reporting AS (
  SELECT date_key AS as_of_date FROM {{CORE}}dim_date WHERE is_reporting_date
),
periods AS (
  SELECT explode(array('MTD','QTD','YTD','1Y','3Y','SI')) AS period_type
),
grid AS (
  SELECT
    p.portfolio_id,
    p.benchmark_id,
    r.as_of_date,
    pd.period_type,
    pmod(hash(concat('pf-ret-', p.portfolio_id, r.as_of_date, pd.period_type)), 2000) AS ret_pick,
    pmod(hash(concat('pf-fee-', p.portfolio_id)), 90)                                 AS fee_pick,
    pmod(hash(concat('pf-cf-',  p.portfolio_id, pd.period_type)), 120)                AS cf_pick
  FROM {{CORE}}dim_portfolio p
  CROSS JOIN reporting r
  CROSS JOIN periods pd
  WHERE r.as_of_date >= p.inception_date
)
SELECT
  portfolio_id,
  benchmark_id,
  as_of_date,
  period_type,
  -- Gross of fees, time weighted.
  cast((ret_pick - 700) / 10000.0 AS DECIMAL(10,6))                          AS twr_gross,
  -- Net of fees: gross less the annual expense ratio for the period.
  cast(((ret_pick - 700) / 10000.0) - ((10 + fee_pick) / 10000.0)
       AS DECIMAL(10,6))                                                     AS twr_net,
  -- Money weighted: differs from time weighted whenever cash moved.
  cast(((ret_pick - 700) / 10000.0) + ((cf_pick - 60) / 12000.0)
       AS DECIMAL(10,6))                                                     AS mwr,
  cast((pmod(hash(concat('bm-', benchmark_id, as_of_date, period_type)), 1800) - 620) / 10000.0
       AS DECIMAL(10,6))                                                     AS benchmark_return
FROM grid;

ALTER TABLE {{CORE}}fct_performance ALTER COLUMN twr_gross
  COMMENT 'Time weighted return, gross of fees.';
ALTER TABLE {{CORE}}fct_performance ALTER COLUMN twr_net
  COMMENT 'Time weighted return, net of fees.';
ALTER TABLE {{CORE}}fct_performance ALTER COLUMN mwr
  COMMENT 'Money weighted return.';
ALTER TABLE {{CORE}}fct_performance ALTER COLUMN benchmark_return
  COMMENT 'Return of the assigned benchmark for the same period.';
ALTER TABLE {{CORE}}fct_performance ALTER COLUMN period_type
  COMMENT 'Return period.';


-- ----------------------------------------------------------------------------
-- Row counts
-- ----------------------------------------------------------------------------
SELECT 'fct_aum_snapshot' AS table_name, count(*) AS rows FROM {{CORE}}fct_aum_snapshot
UNION ALL SELECT 'fct_flows',       count(*) FROM {{CORE}}fct_flows
UNION ALL SELECT 'fct_performance', count(*) FROM {{CORE}}fct_performance
ORDER BY table_name;
