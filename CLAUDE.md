# databricks360 — working notes

Installs Databricks course lab environments into a workspace: notebooks, datasets,
governance objects, documents, Genie Agents, and graded labs.

## The one rule

**Rendering is not running.** The tests render SQL and never execute it, so they cannot
catch a column that does not exist, a metadata query that matches nothing, or an API
that rejects a payload shape. Six bugs shipped in `06_curated` and `07_metric_view`
before anyone ran them.

Before any release:

```bash
export DATABRICKS_HOST=... DATABRICKS_TOKEN=...   # or DATABRICKS_CONFIG_PROFILE
python3 scripts/run_lab.py --all --catalog <catalog>
```

And read `99_validate`'s **output rows**, not just its exit status. A notebook that runs
successfully can still report `FAIL` on every check.

## Then go further: follow the labs

Executing the SQL is not enough either. Walking the labs as a learner — clean virtualenv,
`pip install databricks360`, fresh workspace — found three defects that every test and
every SQL run had missed:

- `create_documents` fell back to plain text without `fpdf`, wrote forty files Agent mode
  cannot read, and reported success
- `academy.lab()` printed an older brief than the module's numbered steps, and every
  lab's step 1 sends the reader there
- Lab 4's nine recorded failures no longer reproduce, because the model improved

None of these were visible from reading the code.

## Release

`scripts/preflight.py` blocks on: version disagreement, a version already on PyPI,
uncommitted changes, `HEAD` out of sync with `origin/main`, stale `dist/`, failing tests,
and spoiler text reaching the generated notebooks across six catalog layouts.

`scripts/publish.py` runs preflight, builds, uploads, and waits for the index.

- **PyPI versions are immutable.** A wrong number can only be yanked.
- **The index lags.** `pip install <new version>` can fail for a few minutes after
  publish says "live". Poll rather than concluding the publish failed.
- Releases happen from `main`; preflight requires it.

## Things that are not obvious

**Volume paths need three segments.** `/Volumes/<catalog>/<schema>/<volume>`. A layout with
no catalog yields two and the upload fails with `Path contains an invalid volume name`,
which does not name the cause. `resolve_catalog()` in `_layout.py` exists for this — a
notebook calls with no catalog because its session has one, and a `/Volumes` path has no
session.

**Genie payloads must be sorted.** Every list in `serialized_space` — tables by
`identifier`, everything else by `id`. Sort *after* rendering, because the layout prefix
decides the order. `_sorted_space()` handles it.

**Volumes attach as `data_sources.volumes`** with key `path` (a `/Volumes` path, not a
dotted name) and a `description` that is a **line array**, like every other text field.
Undocumented; found by probing.

**Certification is a system tag.** `system.certification_status`, values `certified` and
`deprecated`. A custom tag spelling the word `certified` is decoration. Databricks
documents a ranking effect for certified only — nothing equivalent for deprecated.

**A row filter with no matching group hides everything from everyone**, including whoever
installed the lab. `05_governance` renders the installer's name via `{{OWNER}}` for exactly
this reason. Column masks deliberately do *not* get the same exemption: a mask returns rows,
so it never bricks anything, and exempting the owner would hand them the PII the module is about.

**Notebook magics are not python.** `08_agents` and `100_cleanup` contain `%pip`. The
python-notebook test strips lines starting with `%` before compiling.

**`create_documents` requires `fpdf2`.** Agent mode reads PDF, JPG, PNG, TIFF, DOC, DOCX,
PPT, PPTX and nothing else. There is deliberately no text fallback.

**Agent-mode file reading needs a preview enabled.** A workspace admin turns on *Analyze
Files in Volumes with Genie Agents*. Without it the volume attaches, the files sit there,
and the agent says it has no document-search tool. Not a RAG pipeline; a checkbox.

## Layouts

Six shapes, all rendered by the spoiler sweep. Four have been executed end to end: the
course default (one schema, `mfg_` prefix), multi-schema (`core`/`ref`/`staging`), single
schema in a named catalog, and `create_catalog=True`. `run_lab.py --bare` selects the
multi-schema shape.

## Tiers

`small` is 20M flows and about a minute. `large` is 900M and tens of minutes — Module 13
only, and it must go in its own schema. Only `03_facts` scales.

## Cleanup

`academy.cleanup('genie-agents')` is a dry run; `confirm=True` removes. It matches agents
by the titles the package gives them, so a renamed one is reported and kept. Run it
**between cohorts**, not only at the end: the dataset is deterministic, so a stale install
looks identical to a fresh one until someone's Lab 7 is graded against a previous learner's views.
