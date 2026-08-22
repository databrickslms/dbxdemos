-- ============================================================================
-- Meridian Financial Group — 07. Metric view
--
-- One definition of each headline metric, in Unity Catalog, consumed by every
-- agent and dashboard that needs it. Defining "net fee revenue" separately in
-- five places is how five teams end up with five numbers.
--
-- Metric views separate measures from dimensions: the measure is declared once
-- and stays correct however it is grouped or filtered at query time.
-- ============================================================================

CREATE OR REPLACE VIEW {{CORE}}mv_banking_metrics
WITH METRICS
LANGUAGE YAML
COMMENT 'Headline banking metrics. Definitive source for net fee revenue, transaction volume and average transaction value.'
AS $$
version: 0.1

source: {{CORE}}vw_transactions_net

joins:
  - name: account
    source: {{CORE}}dim_account
    on: source.account_id = account.account_id
  - name: branch
    source: {{CORE}}dim_branch
    on: account.branch_id = branch.branch_id
  - name: product
    source: {{CORE}}dim_product
    on: account.product_id = product.product_id
  - name: customer
    source: {{CORE}}dim_customer_safe
    on: account.customer_id = customer.customer_id
  - name: date
    source: {{CORE}}dim_date
    on: source.txn_date = date.date_key

dimensions:
  - name: Fiscal Year
    expr: date.fiscal_year
    synonyms: [fy, financial year]
  - name: Fiscal Quarter
    expr: date.fiscal_quarter
  - name: Transaction Date
    expr: source.txn_date
  - name: Region
    expr: branch.region
    synonyms: [sales region, area]
  - name: State
    expr: branch.state
  - name: Channel
    expr: branch.channel
  - name: Product Category
    expr: product.product_category
    synonyms: [product, product line]
  - name: Merchant Category
    expr: source.merchant_category
    synonyms: [mcc, merchant type]
  - name: Customer Segment
    expr: customer.segment
    synonyms: [segment]
  - name: Tenure Band
    expr: customer.tenure_band
  - name: Currency
    expr: source.currency

measures:
  - name: Net Fee Revenue
    expr: SUM(source.net_fee_revenue_usd)
    synonyms: [revenue, net revenue, fee income, top line]
    format: currency
  - name: Gross Fee Revenue
    expr: SUM(source.gross_fee_revenue)
    synonyms: [gross revenue]
    format: currency
  - name: Reversed Amount
    expr: SUM(source.gross_fee_revenue - source.net_fee_revenue)
    synonyms: [chargebacks, reversals]
    format: currency
  - name: Transaction Volume
    expr: COUNT(1)
    synonyms: [transactions, txn count, volume]
  - name: Reversal Rate
    expr: SUM(CASE WHEN source.was_reversed THEN 1 ELSE 0 END) / NULLIF(COUNT(1), 0)
    synonyms: [chargeback rate]
    format: percent
  - name: Average Transaction Value
    expr: SUM(source.amount_usd) / NULLIF(COUNT(1), 0)
    synonyms: [atv, average ticket]
    format: currency
  - name: Interchange
    expr: SUM(source.interchange)
    format: currency
$$;


-- ----------------------------------------------------------------------------
-- Verify — the same measure, three groupings, no redefinition
-- ----------------------------------------------------------------------------
SELECT `Fiscal Year`, `Net Fee Revenue`, `Transaction Volume`
FROM {{CORE}}mv_banking_metrics
GROUP BY ALL
ORDER BY `Fiscal Year`;

SELECT `Region`, `Net Fee Revenue`, `Reversal Rate`
FROM {{CORE}}mv_banking_metrics
GROUP BY ALL
ORDER BY `Net Fee Revenue` DESC;

SELECT `Product Category`, `Average Transaction Value`
FROM {{CORE}}mv_banking_metrics
GROUP BY ALL
ORDER BY `Average Transaction Value` DESC;
