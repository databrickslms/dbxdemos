# lakehouse-academy

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

Once published, that becomes `%pip install lakehouse-academy`.

To pin a version, append a tag or commit:

```python
%pip install git+https://github.com/databrickslms/dbxdemos.git@v0.1.0
```

## Usage

```python
import lakehouse_academy as academy

academy.list_courses()
academy.install('genie-agents')
```

`install` writes the lab notebooks into your workspace and prints the run order.
Then you open them and run each in turn.

```
Installed 'genie-agents' → /Workspace/Users/you@corp.com/lakehouse-academy/genie-agents
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

## Tiers

| Tier | Transactions | Use |
|---|---|---|
| `small` | 20M | default. Every module except 13 |
| `large` | 900M | Module 13 (latency) only. Left unclustered on purpose |

Start small. The large tier exists because you cannot measure query latency on a
toy dataset, and nowhere else needs it.

## Adding a course

Each course is a subpackage under `lakehouse_academy/courses/`:

```
lakehouse_academy/courses/<course_id>/
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
   | PyPI Project Name | `lakehouse-academy` |
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
