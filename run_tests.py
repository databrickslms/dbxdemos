#!/usr/bin/env python3
"""Run the test suite. Uses pytest when available, otherwise a minimal runner,
so `python3 run_tests.py` works on a bare interpreter."""

from __future__ import annotations

import importlib.util
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

try:
    import pytest  # noqa: F401
    raise SystemExit(__import__("pytest").main(["-q", str(ROOT / "tests")]))
except ImportError:
    pass

passed = failed = 0
for test_file in sorted((ROOT / "tests").glob("test_*.py")):
    spec = importlib.util.spec_from_file_location(test_file.stem, test_file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in sorted(n for n in dir(module) if n.startswith("test_")):
        try:
            getattr(module, name)()
            passed += 1
            print(f"  ok    {name}")
        except Exception:
            failed += 1
            print(f"  FAIL  {name}")
            print("        " + traceback.format_exc().strip().splitlines()[-1])

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
