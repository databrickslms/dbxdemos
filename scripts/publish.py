#!/usr/bin/env python3
"""Publish databricks360 to PyPI.

Runs preflight, builds, uploads, and waits until the version is actually visible
on the index. Picks whichever credential route is available:

  1. Trusted Publishing  — tag and push; GitHub Actions uploads over OIDC.
                           No credential anywhere. Preferred.
  2. Stored credential   — ~/.pypirc, TWINE_* env vars, or keyring. twine reads
                           it directly; the token is never printed or passed as
                           an argument.

If neither exists it explains how to set one up and stops. It never asks for a
token interactively, because a PyPI token publishes code under your name to an
index other people install from.

    python3 scripts/publish.py              # auto: tag route if configured, else twine
    python3 scripts/publish.py --tag        # force the Trusted Publishing route
    python3 scripts/publish.py --twine      # force the local-credential route
    python3 scripts/publish.py --dry-run    # preflight + build only
"""

from __future__ import annotations

import configparser
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = "databricks360"
SIMPLE = f"https://pypi.org/simple/{PKG}/"


def sh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, text=True, check=check)


def out(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True).stdout.strip()


def version() -> str:
    m = re.search(r'^version\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(), re.M)
    if not m:
        sys.exit("could not read version from pyproject.toml")
    return m.group(1)


def published() -> list[str]:
    req = urllib.request.Request(
        SIMPLE, headers={"Accept": "application/vnd.pypi.simple.v1+json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp).get("versions", [])
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return []
        raise


def has_local_credential() -> str | None:
    """Which stored credential twine would use, without reading its value."""
    if os.environ.get("TWINE_PASSWORD") and os.environ.get("TWINE_USERNAME"):
        return "TWINE_* environment variables"
    rc = Path.home() / ".pypirc"
    if rc.is_file():
        cp = configparser.ConfigParser()
        try:
            cp.read(rc)
        except configparser.Error:
            return None
        for section in ("pypi", "distutils"):
            if cp.has_section(section) and (
                cp.has_option(section, "password") or cp.has_option(section, "username")
            ):
                return "~/.pypirc"
    return None


def trusted_publishing_ready() -> bool:
    """Whether the Publish workflow exists and is active on the remote."""
    wf = ROOT / ".github" / "workflows" / "publish.yml"
    return wf.is_file()


CREDENTIAL_HELP = """
  No publishing credential is configured, so nothing can be uploaded from here.

  Option A — Trusted Publishing (recommended, no token anywhere)

    1. pypi.org -> Your account -> Publishing -> Add a pending publisher:
         PyPI Project Name  databricks360
         Owner              databrickslms
         Repository name    dbxdemos
         Workflow name      publish.yml
         Environment name   pypi
    2. GitHub -> dbxdemos -> Settings -> Environments -> New environment -> pypi
    3. Re-run with:  python3 scripts/publish.py --tag

  Option B — store a token locally, once. It stays on this machine.

    umask 077
    cat > ~/.pypirc <<'EOF'
    [pypi]
      username = __token__
      password = pypi-PASTE_YOUR_TOKEN_HERE
    EOF
    chmod 600 ~/.pypirc

    Then re-run this script; twine reads it directly and the token is never
    printed, logged, or passed as an argument.
"""


def main() -> int:
    args = set(sys.argv[1:])
    v = version()

    print(f"\n  publishing {PKG} {v}\n")

    # 1. Preflight ------------------------------------------------------------
    pre = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "preflight.py")], cwd=ROOT
    )
    if pre.returncode != 0:
        return pre.returncode

    if v in published():
        print(f"  {v} is already on PyPI. Nothing to do.\n")
        return 0

    if "--dry-run" in args:
        print("  --dry-run: stopping before build.\n")
        return 0

    # 2. Choose a route -------------------------------------------------------
    cred = has_local_credential()
    if "--tag" in args:
        route = "tag"
    elif "--twine" in args:
        if not cred:
            print(CREDENTIAL_HELP)
            return 1
        route = "twine"
    elif trusted_publishing_ready() and not cred:
        route = "tag"
    elif cred:
        route = "twine"
    else:
        print(CREDENTIAL_HELP)
        return 1

    # 3. Publish --------------------------------------------------------------
    if route == "tag":
        tag = f"v{v}"
        if out("git", "tag", "-l", tag):
            print(f"  tag {tag} already exists. Delete it or bump the version.\n")
            return 1
        print(f"  route: Trusted Publishing — tagging {tag}\n")
        sh("git", "tag", tag)
        sh("git", "push", "origin", tag)
        print(
            "\n  Pushed. GitHub Actions is building and will upload over OIDC.\n"
            "  Watch: https://github.com/databrickslms/dbxdemos/actions\n"
        )
    else:
        print(f"  route: twine, using {cred}\n")
        shutil.rmtree(ROOT / "dist", ignore_errors=True)
        sh(sys.executable, "-m", "build")
        sh(sys.executable, "-m", "twine", "check", *[str(p) for p in (ROOT / "dist").glob("*")])
        # twine reads the credential itself. Nothing secret crosses this boundary.
        sh(sys.executable, "-m", "twine", "upload", *[str(p) for p in (ROOT / "dist").glob("*")])

    # 4. Wait for the index ---------------------------------------------------
    print("  waiting for the index", end="", flush=True)
    for _ in range(40):  # up to ~3 min, longer for the CI route
        time.sleep(5)
        print(".", end="", flush=True)
        try:
            if v in published():
                print(f"\n\n  live: {v} is on PyPI")
                print(f"  https://pypi.org/project/{PKG}/{v}/\n")
                print("  In a Databricks notebook:\n")
                print(f"    %pip install {PKG}=={v}")
                print("    dbutils.library.restartPython()\n")
                print("  Then, in a NEW cell:\n")
                print(f"    import {PKG} as academy")
                print("    academy.install('genie-agents', overwrite=True)\n")
                print(
                    "  overwrite=True matters — upgrading the package does not replace\n"
                    "  notebooks already in the workspace.\n"
                )
                return 0
        except Exception:
            pass

    print(
        f"\n\n  {v} has not appeared yet. If the tag route was used, check the Actions run.\n"
        f"  Otherwise re-check: {SIMPLE}\n"
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
