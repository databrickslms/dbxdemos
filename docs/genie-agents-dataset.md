# Meridian Financial Group — lab dataset

The substrate for every lab in the **Genie Agents** course. Nine flaws are planted
deliberately (see `plan.md` §0.3); **do not "fix" the data** — each flaw is the raw material
for a specific module.

## Run order

| File | What it does | Runs on |
|---|---|---|
| `01_catalog_and_schemas.sql` | catalog, schemas, volume | SQL warehouse |
| `02_dimensions.sql` | `dim_date`, `dim_branch`, `dim_product`, `dim_customer`, `dim_account`, `dim_fx_rate` | SQL warehouse |
| `03_facts.sql` | `fct_transactions`, `fct_reversals`, `fct_loan_balances`, `fct_applications`, `fct_fraud_cases` | SQL warehouse |
| `04_decoys.sql` | `fct_transactions_raw` (380 cols), `fct_txn_legacy` — for Modules 7 and 13 | SQL warehouse |
| `05_governance.sql` | row filter, column masks, groups | SQL warehouse (needs metastore admin) |
| `06_curated.sql` | the "after" layer: `vw_transactions_net`, `vw_loan_book_eop`, `dim_customer_safe`, UC functions | SQL warehouse |
| `07_metric_view.sql` | `mv_banking_metrics` | SQL warehouse |
| `99_validate.sql` | one check per planted flaw — run last | SQL warehouse |

Every script is idempotent (`CREATE OR REPLACE`), so re-running is safe.

## Data tiers

Scale is controlled by one variable at the top of `03_facts.sql`:

| Tier | `txn_count` | Use |
|---|---|---|
| **Small** | 20,000,000 | default — all accuracy modules (0–12, 14–17) |
| **Large** | 900,000,000 | Module 13 only (latency). Leave `fct_transactions` unclustered on purpose |

Start Small. Module 13 is the only place that needs Large, and it needs it precisely because
you cannot measure query time on a toy dataset.

## Determinism matters

All synthetic values derive from `hash()` of the row key, never `rand()`. Two consequences:

- Every learner gets **byte-identical data**, so a benchmark's ground-truth SQL returns the
  same answer for everyone. Non-deterministic seeding would silently break Module 11.
- Re-running a script reproduces the same rows rather than a new random draw.

If you change a seed salt, regenerate everything downstream and re-run `99_validate.sql`.

## Prerequisites

- Unity Catalog enabled, and permission to create a catalog (or edit `01_…` to use an existing one)
- A **Pro or serverless** SQL warehouse
- For `05_governance.sql`: authority to create groups, or hand that file to an admin

## Where the flaws live

| # | Flaw | Planted in |
|---|---|---|
| 1 | gross vs net fee revenue | `03_facts.sql` — `fee_revenue` excludes reversals |
| 2 | fiscal year starts Oct 1 | `02_dimensions.sql` — `dim_date` |
| 3 | region/state are codes, not names | `02_dimensions.sql` — `dim_branch` |
| 4 | `DECLINED` rows inflate counts | `03_facts.sql` — `status` distribution |
| 5 | two competing product hierarchies | `02_dimensions.sql` — `dim_product` |
| 6 | daily snapshot invites `SUM()` fan-out | `03_facts.sql` — `fct_loan_balances` |
| 7 | four meanings of "delinquent" | `03_facts.sql` — `days_past_due` / `dpd_bucket` |
| 8 | real-shaped PII columns | `02_dimensions.sql` — `dim_customer` |
| 9 | multi-currency needs as-of FX | `02_dimensions.sql` + `03_facts.sql` |
