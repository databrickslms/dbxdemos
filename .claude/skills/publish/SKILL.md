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

```bash
python3 scripts/publish.py
```

This **actually uploads**. It runs preflight, picks whichever credential route is
available, publishes, then polls the index until the version is visible and prints
the exact `%pip` line to use.

Routes, in order of preference:

| Route | Credential | Flag |
|---|---|---|
| Trusted Publishing | none — GitHub Actions authenticates over OIDC | `--tag` |
| twine | `~/.pypirc`, `TWINE_*` env vars, or keyring | `--twine` |

With no flag it takes the tag route when Trusted Publishing is set up and no local
credential exists, otherwise twine. `--dry-run` stops after preflight and build.

### If it reports no credential

The script prints setup instructions for both routes and stops. **Never offer to
take the token in conversation, and never read one from the keychain.** A PyPI
token publishes code under the user's name to an index other people install from —
it belongs in their shell or `~/.pypirc`, not in a transcript.

The env-var route, for the user to run themselves (the token is not echoed and
does not reach shell history):

```bash
umask 077 && mkdir -p ~/.config
read -rs TOKEN
printf 'export TWINE_USERNAME=__token__\nexport TWINE_PASSWORD=%s\n' "$TOKEN" > ~/.config/pypi-token.env
unset TOKEN
grep -q pypi-token.env ~/.zshrc || echo '[ -f ~/.config/pypi-token.env ] && . ~/.config/pypi-token.env' >> ~/.zshrc
```

A new shell then has it, and so does the Bash tool, which is initialised from the
user's profile. `chmod 600` on a dedicated file is narrower than exporting the
token from `.zshrc` directly, where every child process inherits it.

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
