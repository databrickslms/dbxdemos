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
-- vw_aum_reporting  —  AUM at each month-end reporting date, in USD
-- One row per account per reporting date, converted, with the discretionary
-- split made explicit so the three AUM definitions stop being ambiguous.
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}vw_aum_reporting
COMMENT 'AUM per account at each month-end reporting date, converted to USD. One row per account per reporting date, so SUM over a period is a real balance rather than a repeated one. Use this instead of fct_aum_snapshot for anything aggregated.'
AS
SELECT
  s.account_id,
  a.client_id,
  s.portfolio_id,
  s.fund_id,
  s.snapshot_date                                                   AS as_of_date,
  d.fiscal_year,
  d.fiscal_quarter,
  d.calendar_quarter,
  s.local_currency,
  cast(s.market_value_local * fx.usd_rate AS DECIMAL(18,2))         AS managed_value_usd,
  cast(s.held_away_value_local * fx.usd_rate AS DECIMAL(18,2))      AS held_away_value_usd,
  cast((s.market_value_local + s.held_away_value_local) * fx.usd_rate
       AS DECIMAL(18,2))                                            AS total_advised_value_usd,
  coalesce(p.is_discretionary, true)                                AS is_discretionary,
  coalesce(p.asset_class_code, f.asset_class_code)                   AS asset_class_code
FROM {{CORE}}fct_aum_snapshot s
JOIN {{CORE}}dim_date d
  ON d.date_key = s.snapshot_date AND d.is_reporting_date
JOIN {{CORE}}dim_fx_rate fx
  ON fx.currency = s.local_currency AND fx.rate_date = s.snapshot_date
JOIN {{CORE}}dim_account a
  ON a.account_id = s.account_id
LEFT JOIN {{CORE}}dim_portfolio p ON p.portfolio_id = s.portfolio_id
LEFT JOIN {{CORE}}dim_fund      f ON f.fund_id      = s.fund_id;

ALTER VIEW {{CORE}}vw_aum_reporting ALTER COLUMN managed_value_usd
  COMMENT 'Assets Meridian manages, in USD. This is what "AUM" means at Meridian unless someone says otherwise.';
ALTER VIEW {{CORE}}vw_aum_reporting ALTER COLUMN held_away_value_usd
  COMMENT 'Assets Meridian reports on but does not manage. Excluded from AUM. Include only when the question says "advised" or "AUA".';
ALTER VIEW {{CORE}}vw_aum_reporting ALTER COLUMN total_advised_value_usd
  COMMENT 'Managed plus held-away. This is assets under advisement, not AUM. The two differ by roughly a fifth of accounts.';
ALTER VIEW {{CORE}}vw_aum_reporting ALTER COLUMN as_of_date
  COMMENT 'Month-end reporting date, the last business day of the month. Not the last calendar day.';
ALTER VIEW {{CORE}}vw_aum_reporting ALTER COLUMN is_discretionary
  COMMENT 'True where Meridian has investment discretion. Advisory-only mandates are excluded from discretionary AUM.';


-- ============================================================================
-- vw_net_flows  —  settled money movement, with the netting made explicit
-- Exchanges move money between Meridian products, so counting them as sales
-- and redemptions inflates both sides and leaves net flows unchanged.
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}vw_net_flows
COMMENT 'Settled client flows in USD, with external and internal movement separated. Use this rather than fct_flows: it excludes unsettled and cancelled instructions, and keeps exchanges out of the sales and redemption figures.'
AS
SELECT
  fl.flow_id,
  fl.account_id,
  a.client_id,
  fl.settlement_date                                                AS as_of_date,
  d.fiscal_year,
  d.fiscal_quarter,
  fl.flow_type,
  cast(fl.amount_local * fx.usd_rate AS DECIMAL(18,2))              AS amount_usd,
  -- External money entering or leaving Meridian.
  CASE WHEN fl.flow_type IN ('SUBSCRIPTION','TRANSFER_IN')  THEN 1
       WHEN fl.flow_type IN ('REDEMPTION','TRANSFER_OUT')   THEN -1
       ELSE 0 END                                                   AS external_sign,
  -- Movement between Meridian products, which nets to zero overall.
  fl.flow_type IN ('EXCHANGE_IN','EXCHANGE_OUT')                    AS is_internal
FROM {{CORE}}fct_flows fl
JOIN {{CORE}}dim_date d
  ON d.date_key = fl.settlement_date
JOIN {{CORE}}dim_fx_rate fx
  ON fx.currency = fl.local_currency AND fx.rate_date = fl.settlement_date
JOIN {{CORE}}dim_account a
  ON a.account_id = fl.account_id
WHERE fl.status = 'SETTLED';

ALTER VIEW {{CORE}}vw_net_flows ALTER COLUMN external_sign
  COMMENT 'Multiply amount_usd by this and sum to get net new money: +1 for subscriptions and transfers in, -1 for redemptions and transfers out, 0 for exchanges.';
ALTER VIEW {{CORE}}vw_net_flows ALTER COLUMN is_internal
  COMMENT 'True for exchanges between Meridian products. These are not sales or redemptions and must not be counted as either.';
ALTER VIEW {{CORE}}vw_net_flows ALTER COLUMN as_of_date
  COMMENT 'Settlement date, which is when the money actually moved. Trade date is when the instruction was placed and is usually one to three days earlier.';


-- ============================================================================
-- dim_client_safe  —  client attributes without the identifiers
-- ============================================================================
CREATE OR REPLACE VIEW {{CORE}}dim_client_safe
COMMENT 'Client attributes with all direct identifiers removed. Point agents here rather than at dim_client.'
AS
SELECT
  client_id,
  client_segment,
  advisor_id,
  domicile,
  tenure_months,
  CASE WHEN tenure_months < 12 THEN 'New'
       WHEN tenure_months < 60 THEN 'Established'
       ELSE 'Long-tenured' END                              AS tenure_band,
  floor(datediff(DATE'2026-09-30', dob) / 365.25)            AS age_years,
  CASE WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 35 THEN 'Under 35'
       WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 55 THEN '35-54'
       WHEN floor(datediff(DATE'2026-09-30', dob) / 365.25) < 70 THEN '55-69'
       ELSE '70+' END                                       AS age_band
FROM {{CORE}}dim_client;


-- ============================================================================
-- Unity Catalog functions — verified logic, reusable and shareable
-- ============================================================================

-- Discretionary AUM by asset class at a reporting date.
CREATE OR REPLACE FUNCTION {{CORE}}aum_by_asset_class(
  as_of DATE COMMENT 'A month-end reporting date. Use the latest if unsure.'
)
RETURNS TABLE (asset_class_name STRING, aum_usd DECIMAL(20,2), pct_of_total DOUBLE)
COMMENT 'Discretionary AUM by asset class in USD at a reporting date. Excludes held-away assets and advisory-only mandates. Owner: Wealth Analytics.'
RETURN
  SELECT
    ac.asset_class_name,
    cast(sum(v.managed_value_usd) AS DECIMAL(20,2))                       AS aum_usd,
    sum(v.managed_value_usd) / nullif(sum(sum(v.managed_value_usd)) OVER (), 0) AS pct_of_total
  FROM {{CORE}}vw_aum_reporting v
  JOIN {{CORE}}dim_asset_class ac ON ac.asset_class_code = v.asset_class_code
  WHERE v.as_of_date = as_of AND v.is_discretionary
  GROUP BY ac.asset_class_name;

-- Net new money over a period, excluding internal exchanges.
CREATE OR REPLACE FUNCTION {{CORE}}net_flows(
  from_date DATE COMMENT 'Inclusive start, on settlement date.',
  to_date   DATE COMMENT 'Inclusive end, on settlement date.'
)
RETURNS TABLE (gross_sales_usd DECIMAL(20,2), redemptions_usd DECIMAL(20,2), net_flows_usd DECIMAL(20,2))
COMMENT 'Net new money between two settlement dates. Excludes exchanges between Meridian products and anything not settled. Owner: Wealth Analytics.'
RETURN
  SELECT
    cast(sum(CASE WHEN external_sign =  1 THEN amount_usd ELSE 0 END) AS DECIMAL(20,2)),
    cast(sum(CASE WHEN external_sign = -1 THEN amount_usd ELSE 0 END) AS DECIMAL(20,2)),
    cast(sum(external_sign * amount_usd) AS DECIMAL(20,2))
  FROM {{CORE}}vw_net_flows
  WHERE as_of_date BETWEEN from_date AND to_date;

-- Convert a native amount to USD at the rate for a given date.
CREATE OR REPLACE FUNCTION {{CORE}}to_usd(
  amount DECIMAL(18,2) COMMENT 'Amount in its native currency.',
  from_currency STRING COMMENT 'USD, EUR, GBP, JPY or CAD.',
  on_date DATE         COMMENT 'The date of the value, not today.'
)
RETURNS DECIMAL(18,2)
COMMENT 'Converts to USD using the rate as of the given date. Owner: FP&A.'
RETURN
  amount * (SELECT usd_rate FROM {{CORE}}dim_fx_rate
            WHERE currency = from_currency AND rate_date = on_date);

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
SELECT 'vw_aum_reporting' AS object, count(*) AS rows FROM {{CORE}}vw_aum_reporting
UNION ALL SELECT 'vw_net_flows',   count(*) FROM {{CORE}}vw_net_flows
UNION ALL SELECT 'dim_client_safe', count(*) FROM {{CORE}}dim_client_safe;

-- The three AUM figures, side by side, at the latest reporting date.
SELECT
  cast(sum(CASE WHEN is_discretionary THEN managed_value_usd ELSE 0 END) / 1e9 AS DECIMAL(12,2)) AS discretionary_aum_bn,
  cast(sum(managed_value_usd)        / 1e9 AS DECIMAL(12,2)) AS managed_aum_bn,
  cast(sum(total_advised_value_usd)  / 1e9 AS DECIMAL(12,2)) AS advised_aua_bn
FROM {{CORE}}vw_aum_reporting
WHERE as_of_date = (SELECT max(as_of_date) FROM {{CORE}}vw_aum_reporting);
