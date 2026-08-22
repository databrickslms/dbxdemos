#!/usr/bin/env python3
"""Release preflight for databricks360.

Every check here exists because something went wrong once:

  - a stale dist/ nearly published an old version
  - a spoiler survived in generated DDL that the test suite never built
  - PyPI already had a version we were about to reuse, and PyPI is immutable
  - pyproject and __init__ drifted apart

Read-only. Exits non-zero on the first blocking problem.

    python3 scripts/preflight.py            # check
    python3 scripts/preflight.py --json     # machine-readable
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = "databricks360"

problems: list[str] = []
warnings: list[str] = []
facts: dict[str, object] = {}


def fail(msg: str) -> None:
    problems.append(msg)


def warn(msg: str) -> None:
    warnings.append(msg)


def run(*args: str) -> str:
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()


# ── version agreement ────────────────────────────────────────────────────────
pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
version = m.group(1) if m else None
if not version:
    fail("could not read version from pyproject.toml")

init = (ROOT / PKG / "__init__.py").read_text(encoding="utf-8")
m2 = re.search(r'__version__\s*=\s*"([^"]+)"', init)
init_version = m2.group(1) if m2 else None
facts["version"] = version
if version and init_version and version != init_version:
    fail(f"version mismatch: pyproject {version} vs __init__ {init_version}")

# ── already on PyPI? PyPI versions are immutable ──────────────────────────────
published: list[str] = []
try:
    req = urllib.request.Request(
        f"https://pypi.org/simple/{PKG}/",
        headers={"Accept": "application/vnd.pypi.simple.v1+json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        published = json.load(resp).get("versions", [])
except urllib.error.HTTPError as exc:
    if exc.code == 404:
        warn(f"{PKG} is not on PyPI yet — this would be the first release")
    else:
        warn(f"could not reach PyPI ({exc.code}); skipping the duplicate check")
except Exception as exc:  # network unavailable
    warn(f"could not reach PyPI ({exc}); skipping the duplicate check")

facts["published"] = published
if version and version in published:
    fail(
        f"{version} is already on PyPI. Versions are immutable — bump "
        f"pyproject.toml and {PKG}/__init__.py, then re-run."
    )

# ── git state ────────────────────────────────────────────────────────────────
branch = run("git", "branch", "--show-current")
dirty = run("git", "status", "--porcelain")
facts["branch"] = branch
if branch and branch != "main":
    warn(f"on branch {branch!r}, not main")
if dirty:
    fail(f"{len(dirty.splitlines())} uncommitted change(s) — commit before releasing")

run("git", "fetch", "-q", "origin")
local = run("git", "rev-parse", "HEAD")
remote = run("git", "rev-parse", "origin/main")
if local and remote and local != remote:
    fail("HEAD differs from origin/main — push first, or the tag will point elsewhere")
facts["head"] = local[:7]

if version and run("git", "tag", "-l", f"v{version}"):
    warn(f"tag v{version} already exists locally")

# ── stale build artifacts ────────────────────────────────────────────────────
dist = ROOT / "dist"
stale = [p.name for p in dist.glob("*") if version and version not in p.name] if dist.exists() else []
facts["dist"] = sorted(p.name for p in dist.glob("*")) if dist.exists() else []
if stale:
    fail(f"dist/ holds artifacts for another version: {', '.join(stale)}. Run: rm -rf dist")

# ── tests ────────────────────────────────────────────────────────────────────
proc = subprocess.run(
    [sys.executable, "run_tests.py"], cwd=ROOT, capture_output=True, text=True
)
tail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "no output"
facts["tests"] = tail
if proc.returncode != 0:
    fail(f"tests failing: {tail}")

# ── spoiler sweep across every layout ────────────────────────────────────────
# The notebooks must not name the planted flaws. This duplicates a unit test on
# purpose: the unit test once only built one layout and missed a spoiler.
sys.path.insert(0, str(ROOT))
try:
    from databricks360._catalog import get_course  # noqa: E402
    from databricks360._install import build_notebook_source  # noqa: E402
    from databricks360._layout import resolve  # noqa: E402

    SPOILERS = [
        "flaw", "never sum", "do not sum", "enable entity matching",
        "ask which one the user means", "deliberate", "on purpose",
        "teaching dataset", "the scariest",
    ]
    LAYOUTS = [
        dict(),
        dict(catalog="main"),
        dict(catalog="mfg", create_catalog=True),
        dict(schema="genie_agent"),
        dict(schema="genie_agent", table_prefix="mfg_"),
        dict(catalog="main", create_volume=False),
    ]
    hits: list[str] = []
    for course in ("genie-agents",):
        c = get_course(course)
        for kw in LAYOUTS:
            layout = resolve(**kw)
            for nb in c.notebooks:
                src = build_notebook_source(
                    c, nb, catalog=kw.get("catalog"), tier="small", layout=layout
                ).lower()
                hits += [f"{nb.sql}: {s!r}" for s in SPOILERS if s in src]
    if hits:
        fail("notebooks reveal the planted flaws: " + "; ".join(sorted(set(hits))[:4]))
    facts["spoiler_sweep"] = f"{len(LAYOUTS)} layouts clean"
except Exception as exc:
    fail(f"spoiler sweep could not run: {exc}")

# ── report ───────────────────────────────────────────────────────────────────
if "--json" in sys.argv:
    print(json.dumps({"ok": not problems, "facts": facts,
                      "problems": problems, "warnings": warnings}, indent=2))
    raise SystemExit(1 if problems else 0)

print(f"\n  databricks360 {version}")
print(f"  head            {facts.get('head')} on {branch or '?'}")
print(f"  on PyPI         {', '.join(published) or 'nothing yet'}")
print(f"  tests           {facts.get('tests')}")
print(f"  spoiler sweep   {facts.get('spoiler_sweep', 'not run')}")
if facts["dist"]:
    print(f"  dist/           {', '.join(facts['dist'])}")

for w in warnings:
    print(f"\n  ! {w}")
if problems:
    print("\n  BLOCKED:")
    for p in problems:
        print(f"    ✗ {p}")
    print()
    raise SystemExit(1)

print(f"\n  ready to publish {version}\n")
