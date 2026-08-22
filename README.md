# databricks360

Installs Databricks course lab environments — notebooks, catalogs, datasets and
governance objects — into your own workspace.

Modelled on `dbdemos`: you run it **inside a Databricks notebook**, so
`databricks-sdk` picks up the notebook's own identity. There is no host, token or
profile to configure.

## Install

Not on PyPI yet, so install from the repo. In a **Databricks notebook**:

```python
%pip install git+https://github.com/databrickslms/dbxdemos.git
dbutils.library.restartPython()
```

Once published, that becomes `%pip install databricks360`.

To pin a version, append a tag or commit:

```python
%pip install git+https://github.com/databrickslms/dbxdemos.git@v0.1.0
```

## Usage

```python
import databricks360 as academy

academy.list_courses()
academy.install('genie-agents')
```

`install` writes the lab notebooks into your workspace and prints the run order.
Then you open them and run each in turn.

```
Installed 'genie-agents' → /Workspace/Users/you@corp.com/databricks360/genie-agents
  catalog: mfg    tier: small

  Run these in order:
    1. 01_catalog_and_schemas
    2. 02_dimensions
    3. 03_facts   (slow)
```

### Options

```python
academy.install(
    'genie-agents',
    path='/Workspace/Shared/labs',   # default: your home folder
    catalog='training_v2',           # default: the course's own catalog
    tier='large',                    # default: 'small'
    overwrite=True,                  # replace existing notebooks
)
```

## Why it does not run the notebooks for you

`dbdemos` starts a job and loads the data on your behalf. This deliberately does
not. Generating the data is the substance of Module 0 — the point is to watch a
warehouse chew through 20M rows and see the flaws appear, not to have a finished
catalog materialise. It also means nothing consumes your DBUs without you asking.

## Regulated environments

A locked-down Unity Catalog is normal in a governed organisation, so **the default
assumes the least privilege that can still work**: the lab lands in whatever
`current_catalog()` returns, and nothing is created above schema level.

Notebook 01 opens by showing you exactly where that is:

```sql
SELECT current_catalog() AS default_catalog, current_schema() AS default_schema;
```

### The four shapes

```python
# 1. Default — current catalog, schemas core / ref / staging.
#    No CREATE CATALOG attempted. Table names are two-level (core.dim_date),
#    so SQL resolves the catalog itself.
academy.install('genie-agents')

# 2. A specific catalog you were granted. Adds USE CATALOG, still creates no catalog.
academy.install('genie-agents', catalog='main')

# 3. Create a catalog — opt in, only if you hold the privilege.
academy.install('genie-agents', catalog='mfg', create_catalog=True)

# 4. One schema you already own. Everything lands there.
academy.install('genie-agents', schema='training_you')
academy.install('genie-agents', catalog='main', schema='training_you')
```

`create_catalog` is **off** by default and raises if you pass it without a catalog
name — `current_catalog()` exists by definition, so there would be nothing to create.

Passing `schema` assumes you cannot create that schema either, since that is the
reason to reach for it. Override with `create_schema=True` if you can.

### One schema shared with other content

If your schema also holds other things, prefix the object names so their
provenance is visible:

```python
academy.install('genie-agents', schema='genie_agent', table_prefix='mfg_')
```

The logical group folds into the name:

| Default | With `table_prefix='mfg_'` |
|---|---|
| `core.dim_date` | `genie_agent.mfg_core_dim_date` |
| `ref.documents` | `genie_agent.mfg_ref_documents` |
| `staging.fct_txn_legacy` | `genie_agent.mfg_staging_fct_txn_legacy` |

The prefix names objects, never the schema. `table_prefix` requires `schema` —
without one, the schemas already namespace the objects and a prefix would just be
noise.

> **Worth weighing before you use it.** Genie reads table and column names as
> context, and Module 7 of the course is partly about *removing* noise so an agent
> has less to wade through. `mfg_core_dim_date` is measurably noisier than
> `dim_date`. Use a prefix when the schema is genuinely shared and provenance
> matters more; skip it when the schema is yours.

### No CREATE VOLUME either

```python
academy.install('genie-agents', schema='training_you', create_volume=False)
```

The volume only serves Agent mode over unstructured files (Modules 3 and 16).
Skipping it costs those exercises and nothing else, and the notebook says so.

### Why the single-schema case renames nothing

`core` holds the dimensions and facts, `ref` holds only the documents volume, and
`staging` holds only the two decoy tables. The three sets of object names do not
overlap, so collapsing them into one schema is safe — and notebooks 02 onward
resolve their own paths, so they need no changes whichever layout you chose.

### What you get back

`install` reports the resolved layout and anything it declined to create, so a
restricted install is visible rather than quietly partial:

```
Installed 'genie-agents' → /Workspace/Users/you@corp.com/databricks360/genie-agents
  tier: small
  single schema: current_catalog().training_you
  skipping: CREATE SCHEMA, CREATE VOLUME
```

> **Unity Catalog is required.** Genie Agents read Unity Catalog objects, so
> `hive_metastore` will not work as the target catalog.

## Tiers

| Tier | Transactions | Use |
|---|---|---|
| `small` | 20M | default. Every module except 13 |
| `large` | 900M | Module 13 (latency) only. Left unclustered on purpose |

Start small. The large tier exists because you cannot measure query latency on a
toy dataset, and nowhere else needs it.

## Adding a course

Each course is a subpackage under `databricks360/courses/`:

```
databricks360/courses/<course_id>/
  __init__.py
  manifest.json      # title, default catalog, tiers, notebooks in run order
  *.sql              # synced from content/courses/<id>/assets/lab/
```

Placeholders available in the SQL: `{{CATALOG}}`, plus anything declared under a
tier's `values` (currently `{{TXN_COUNT}}`). An unresolved placeholder raises rather
than silently rendering empty.

Dataset documentation lives in [`docs/`](docs/).

## Publishing

Releases go to PyPI via **Trusted Publishing** — GitHub Actions authenticates to
PyPI with a short-lived OIDC identity, so no API token exists in repo secrets or on
anyone's laptop. A leaked token is the usual way a package supply chain gets
compromised; the safest token is one that was never created.

### One-time PyPI setup

1. Sign in at [pypi.org](https://pypi.org) → **Your account → Publishing**
2. Under *Add a new pending publisher*, choose **GitHub** and enter exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `databricks360` |
   | Owner | `databrickslms` |
   | Repository name | `dbxdemos` |
   | Workflow name | `publish.yml` |
   | Environment name | `pypi` |

3. In GitHub → **Settings → Environments → New environment** → name it `pypi`.
   Add yourself as a required reviewer if you want to approve each release.

"Pending" publisher is correct — the project does not exist on PyPI yet, and the
first successful run creates it.

### Cutting a release

```bash
# bump version in pyproject.toml, commit, then:
git tag v0.1.0
git push origin v0.1.0
```

The workflow runs the tests, builds, checks the tag matches `pyproject.toml`, and
publishes. A mismatched tag fails before anything reaches the index — versions on
PyPI are immutable, so a wrong number cannot be taken back, only yanked.

### Publishing by hand instead

```bash
python -m pip install build twine
python -m build
twine check dist/*
twine upload dist/*          # prompts for an API token
```

Test it against TestPyPI first if you want a dry run:
`twine upload --repository testpypi dist/*`.

## Tests

```bash
python3 run_tests.py
```

Eleven tests, no workspace required: manifest loading, notebook cell structure,
catalog substitution, tier switching, unresolved-placeholder detection, and a
`dry_run` install. It also asserts the flaw-teaching column comments survive into
the generated notebooks — those comments are the curriculum, so losing them in
rendering would be a silent failure.
