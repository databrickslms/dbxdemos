---
name: publish
description: Release the databricks360 package to PyPI. Runs preflight checks, builds, and publishes via a version tag (Trusted Publishing) or twine. Use when asked to publish, release, ship, or cut a version of databricks360 — or after bumping its version.
---

# Publish databricks360

Releases the lab-provisioner package to PyPI.

**PyPI versions are immutable.** A wrong number can only be yanked, never replaced.
Every check below exists because something went wrong once — do not skip them to
save a minute.

## 1. Preflight

```bash
python3 scripts/preflight.py
```

Blocks on: version disagreement between `pyproject.toml` and `__init__.py`, a
version already on PyPI, uncommitted changes, `HEAD` out of sync with
`origin/main`, stale artifacts in `dist/`, failing tests, and any spoiler text
reaching the generated notebooks across all six catalog layouts.

Fix everything it reports before continuing. If it says the version is already
published, bump both files rather than trying to overwrite.

## 2. Decide the version

Read the commits since the last release:

```bash
git log --oneline "$(git describe --tags --abbrev=0 2>/dev/null || echo HEAD~10)"..HEAD
```

- **patch** — a fix that changes no interface. A spoiler removed, a comment reworded.
- **minor** — new capability, or a changed default. `current_catalog()` becoming the
  default was minor: additive in code, but it changed what an existing call does.
- **major** — only once there are real users to break.

Bump in **both** `pyproject.toml` and `databricks360/__init__.py`. Preflight
enforces that they agree.

## 3. Publish

Prefer the tag route. It needs no credential.

### Trusted Publishing (no token)

```bash
git tag "v$(grep -m1 '^version' pyproject.toml | cut -d'"' -f2)"
git push origin --tags
```

GitHub Actions runs the tests, builds, verifies the tag matches `pyproject.toml`,
and publishes over OIDC.

One-time setup, if `publish.yml` has never run: on PyPI → Your account →
Publishing, add a pending publisher — project `databricks360`, owner
`databrickslms`, repository `dbxdemos`, workflow `publish.yml`, environment
`pypi`. Then create a GitHub environment named `pypi`.

### twine (needs the user's token)

**Never ask the user to paste a PyPI token into the conversation, and never read
one from their keychain.** A PyPI token publishes code under their name to an
index other people install from. Build the artifacts and hand them the command.

```bash
rm -rf dist && python3 -m build && python3 -m twine check dist/*
```

Then give them, to run themselves:

```bash
python3 -m twine upload dist/*
```

Username `__token__`, password their token.

## 4. Confirm it landed

```bash
python3 - <<'PY'
import json, urllib.request
req = urllib.request.Request(
    "https://pypi.org/simple/databricks360/",
    headers={"Accept": "application/vnd.pypi.simple.v1+json"})
print(json.load(urllib.request.urlopen(req))["versions"])
PY
```

Use the **simple index**, not `/pypi/<pkg>/json` — the aggregate endpoint serves a
stale cache and has reported a release missing minutes after it went live.

## 5. Tell the user two things

**`%pip`, not `!pip`.** `!pip` shells out and Databricks may keep importing the old
version.

**`overwrite=True` or nothing changes.** Upgrading the package does not touch
notebooks already in the workspace:

```python
%pip install --upgrade databricks360
dbutils.library.restartPython()
```

```python
import databricks360 as academy
academy.install('genie-agents', overwrite=True)
```

This is the single most common source of "I already fixed that" confusion.

## Notes

- If the course content changed, check whether Module 0 in the LMS repo
  (`content/courses/genie-agents/plan.md`, §0.5) still describes the current
  install call, and whether `README.md` examples match.
- `dist/` is gitignored. Always `rm -rf dist` before building; a stale wheel from a
  previous version has nearly been published once.
