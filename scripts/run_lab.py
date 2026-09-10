#!/usr/bin/env python3
"""Execute a course's lab SQL against a real workspace, before publishing it.

The test suite renders SQL but never runs it, so a column that does not exist or
a metadata lookup that matches nothing gets through. This runs the statements for
real and reports the first failure in each file with its statement text.

    export DATABRICKS_HOST=... DATABRICKS_TOKEN=...
    python3 scripts/run_lab.py --list
    python3 scripts/run_lab.py 06_curated 07_metric_view --catalog workspace
    python3 scripts/run_lab.py --all --stop-on-error

Nothing here is part of the package. It is a release check.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from databricks360._catalog import get_course, read_sql        # noqa: E402
from databricks360._layout import resolve, setup_ddl, schema_list_sql  # noqa: E402
from databricks360._notebook import render_template, unresolved_placeholders  # noqa: E402


def split_statements(sql: str) -> list[str]:
    """Split on semicolons, respecting $$-quoted bodies (the metric view YAML)."""
    out, buf, in_dollar = [], [], False
    for line in sql.splitlines():
        if line.count("$$") % 2 == 1:
            in_dollar = not in_dollar
        buf.append(line)
        if not in_dollar and line.rstrip().endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt.strip(";").strip():
                out.append(stmt.rstrip(";").strip())
            buf = []
    tail = "\n".join(buf).strip()
    if tail.strip(";").strip():
        out.append(tail.rstrip(";").strip())
    # Comment-only fragments are not statements.
    return [s for s in out if not all(
        not l.strip() or l.strip().startswith("--") for l in s.splitlines())]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("notebooks", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--catalog")
    ap.add_argument("--schema")
    ap.add_argument("--table-prefix")
    ap.add_argument("--tier", default="small")
    ap.add_argument("--warehouse-id")
    ap.add_argument("--bare", action="store_true")
    ap.add_argument("--stop-on-error", action="store_true")
    args = ap.parse_args()

    course = get_course("genie-agents")
    if args.list:
        for nb in course.notebooks:
            print(f"  {nb.name:26} {nb.language:6} {'required' if nb.required else nb.needed_for}")
        return

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState
    w = WorkspaceClient()

    warehouse = args.warehouse_id or next(iter(w.warehouses.list())).id
    # --bare selects the multi-schema layout (core / ref / staging, no prefix),
    # which is what a governed workspace normally gets. Without it the course's
    # own single-schema naming applies, and that is the only shape ever tested.
    if args.bare:
        schema, prefix = None, None
    else:
        schema = args.schema or course.default_schema
        prefix = args.table_prefix or course.default_table_prefix
    layout = resolve(catalog=args.catalog, schema=schema, table_prefix=prefix,
                     create_catalog=False, create_schema=None, create_volume=False)
    values = {
        "CATALOG": layout.catalog or "current_catalog()",
        "INFO_SCHEMA": ("information_schema" if layout.catalog is None
                        else f"{layout.catalog}.information_schema"),
        "CORE": layout.core, "REF": layout.ref, "STAGING": layout.staging,
        "SCHEMA_LIST": schema_list_sql(layout), "SETUP_DDL": setup_ddl(layout),
        "TIER": args.tier,
    }
    values.update(course.tiers[args.tier].values)

    wanted = [nb for nb in course.notebooks
              if nb.language == "sql" and (args.all or nb.name in args.notebooks)]
    if not wanted:
        sys.exit("nothing selected — name notebooks or pass --all (see --list)")

    failures = 0
    for nb in wanted:
        sql = render_template(read_sql(course, nb.sql), values)
        left = unresolved_placeholders(sql)
        if left:
            print(f"  {nb.name}: unresolved placeholders {left}")
            failures += 1
            continue
        statements = split_statements(sql)
        print(f"\n  {nb.name}  ({len(statements)} statements)")
        for i, stmt in enumerate(statements, 1):
            r = w.statement_execution.execute_statement(
                warehouse_id=warehouse, statement=stmt, wait_timeout="50s",
            )
            state = r.status.state
            if state == StatementState.SUCCEEDED:
                print(f"    {i:3}. ok")
                continue
            failures += 1
            msg = (r.status.error.message if r.status and r.status.error else state)
            head = "\n".join(stmt.splitlines()[:6])
            print(f"    {i:3}. FAILED — {msg}")
            print("         " + head.replace("\n", "\n         "))
            if args.stop_on_error:
                sys.exit(f"\n  stopped on first failure in {nb.name}")

    print(f"\n  {'all statements succeeded' if not failures else f'{failures} failure(s)'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
