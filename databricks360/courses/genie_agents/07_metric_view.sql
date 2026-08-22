-- ============================================================================
-- Meridian Financial Group — 07. Metric view
--
-- One definition of each headline metric, in Unity Catalog, consumed by every
-- agent and dashboard that needs it. Defining "AUM" separately in five places
-- is how five teams end up with five numbers.
--
-- Metric views separate measures from dimensions: the measure is declared once
-- and stays correct however it is grouped or filtered at query time.
-- ============================================================================

CREATE OR REPLACE VIEW {{CORE}}mv_wealth_metrics
WITH METRICS
LANGUAGE YAML
COMMENT 'Headline wealth metrics. Definitive source for AUM, assets under advisement and net flows.'
AS $$
version: 0.1

source: {{CORE}}vw_aum_reporting

joins:
  - name: client
    source: {{CORE}}dim_client_safe
    on: source.client_id = client.client_id
  - name: advisor
    source: {{CORE}}dim_advisor
    on: client.advisor_id = advisor.advisor_id
  - name: asset_class
    source: {{CORE}}dim_asset_class
    on: source.asset_class_code = asset_class.asset_class_code
  - name: portfolio
    source: {{CORE}}dim_portfolio
    on: source.portfolio_id = portfolio.portfolio_id

dimensions:
  - name: Fiscal Year
    expr: source.fiscal_year
    synonyms: [fy, financial year]
  - name: Fiscal Quarter
    expr: source.fiscal_quarter
  - name: Calendar Quarter
    expr: source.calendar_quarter
  - name: Reporting Date
    expr: source.as_of_date
    synonyms: [as of date, month end]
  - name: Asset Class
    expr: asset_class.asset_class_name
    synonyms: [asset classes, allocation]
  - name: Investment Class
    expr: asset_class.investment_class
  - name: Strategy
    expr: portfolio.strategy
  - name: Client Segment
    expr: client.client_segment
    synonyms: [segment, channel]
  - name: Region
    expr: advisor.region
    synonyms: [coverage region, area]
  - name: State
    expr: advisor.state
  - name: Discretionary
    expr: source.is_discretionary
  - name: Currency
    expr: source.local_currency

measures:
  - name: AUM
    expr: SUM(CASE WHEN source.is_discretionary THEN source.managed_value_usd ELSE 0 END)
    synonyms: [assets under management, discretionary aum, managed assets]
    format: currency
  - name: Assets Under Advisement
    expr: SUM(source.total_advised_value_usd)
    synonyms: [aua, advised assets, total assets]
    format: currency
  - name: Held Away Assets
    expr: SUM(source.held_away_value_usd)
    synonyms: [held away, unmanaged assets]
    format: currency
  - name: Account Count
    expr: COUNT(DISTINCT source.account_id)
    synonyms: [accounts, funded accounts]
  - name: Client Count
    expr: COUNT(DISTINCT source.client_id)
    synonyms: [clients, investors]
  - name: Average Account Value
    expr: SUM(source.managed_value_usd) / NULLIF(COUNT(DISTINCT source.account_id), 0)
    synonyms: [average balance, average account size]
    format: currency
$$;


-- ----------------------------------------------------------------------------
-- Verify — the same measure, three groupings, no redefinition
-- ----------------------------------------------------------------------------
SELECT `Fiscal Quarter`, `AUM`, `Assets Under Advisement`
FROM {{CORE}}mv_wealth_metrics
GROUP BY ALL
ORDER BY `Fiscal Quarter`;

SELECT `Asset Class`, `AUM`, `Account Count`
FROM {{CORE}}mv_wealth_metrics
GROUP BY ALL
ORDER BY `AUM` DESC;

SELECT `Region`, `Client Segment`, `AUM`
FROM {{CORE}}mv_wealth_metrics
GROUP BY ALL
ORDER BY `AUM` DESC
LIMIT 20;
