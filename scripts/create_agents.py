#!/usr/bin/env python3
"""Create the two Genie Agents Module 7 needs, from checked-in definitions.

Both agents are authored as `serialized_space` JSON under
`databricks360/courses/genie_agents/agents/`, so the configuration is reviewable
source rather than something captured out of the UI. Create Genie Space takes the
whole configuration in one call, so no clicking is involved:

    POST /api/2.0/genie/spaces   { warehouse_id, serialized_space, title, ... }

    python3 scripts/create_agents.py --list        # what exists now
    python3 scripts/create_agents.py --dry-run     # render and check, create nothing
    python3 scripts/create_agents.py               # create both

Object names are rendered from the same {{CORE}}/{{STAGING}} placeholders the
notebooks use, so the agents follow whichever layout the lab was installed with.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from databricks360._catalog import get_course           # noqa: E402
from databricks360._layout import resolve               # noqa: E402
from databricks360._notebook import (                   # noqa: E402
    render_template, unresolved_placeholders,
)

AGENTS = {
    "broken": ("Meridian Wealth (uncurated)",
               "Deliberately under-prepared: every base object, one wall of prose, "
               "no join specs. Used in Module 7's demo and Module 13's latency lab."),
    "curated": ("Meridian Wealth & Distribution",
                "Month-end AUM and net flows over seven curated objects. "
                "The prepared agent from Module 7."),
}


def load(name: str, values: dict) -> dict:
    path = ROOT / "databricks360/courses/genie_agents/agents" / f"{name}.geniespace.json"
    rendered = render_template(path.read_text(), values)
    left = unresolved_placeholders(rendered)
    if left:
        sys.exit(f"{path.name}: unresolved placeholders {left}")
    return json.loads(rendered)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog")
    ap.add_argument("--schema")
    ap.add_argument("--table-prefix")
    ap.add_argument("--warehouse-id", help="default: the first available warehouse")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    from databricks.sdk import WorkspaceClient
    w = WorkspaceClient()

    if args.list:
        for s in w.api_client.do("GET", "/api/2.0/genie/spaces").get("spaces", []):
            print(f"  {s['space_id']}  {s.get('title')}")
        return

    course = get_course("genie-agents")
    schema = args.schema or course.default_schema
    prefix = args.table_prefix or course.default_table_prefix
    catalog = args.catalog
    if catalog is None:
        # The notebooks leave the catalog to current_catalog(), which a SQL session
        # resolves for itself. A Genie data source has no session, so its identifier
        # must be three-level. Find the catalog holding the lab schema.
        found = []
        for c in w.catalogs.list():
            try:
                if any(sc.name == schema for sc in w.schemas.list(c.name)):
                    found.append(c.name)
            except Exception:
                continue
        if len(found) != 1:
            sys.exit(f"schema {schema!r} found in {found or 'no catalog'} — pass --catalog")
        catalog = found[0]
        print(f"  catalog:   {catalog} (resolved from schema {schema!r})")

    layout = resolve(catalog=catalog, schema=schema, table_prefix=prefix,
                     create_catalog=False, create_schema=None, create_volume=False)
    values = {"CORE": layout.core, "REF": layout.ref, "STAGING": layout.staging}

    warehouse = args.warehouse_id
    if not warehouse:
        whs = list(w.warehouses.list())
        if not whs:
            sys.exit("no SQL warehouse in this workspace — pass --warehouse-id")
        warehouse = whs[0].id
        print(f"  warehouse: {warehouse} ({whs[0].name})")

    # An agent pointed at a table that does not exist fails on every question, and
    # the failure looks like a Genie problem rather than a missing notebook. Check first.
    for name in AGENTS:
        space = load(name, values)
        tables = [t["identifier"] for t in space["data_sources"]["tables"]]
        missing = []
        for ident in tables:
            try:
                w.tables.get(ident)
            except Exception:
                missing.append(ident)
        status = f"{len(tables)} objects" + (f", MISSING {len(missing)}" if missing else "")
        print(f"  {name:9} {status}")
        for m in missing:
            print(f"      missing: {m}")
        if missing:
            sys.exit("  run the notebooks that create these first (04_staging, 06_curated, 07_metric_view)")

    if args.dry_run:
        print("\n  --dry-run: rendered and checked, nothing created.")
        return

    for name, (title, description) in AGENTS.items():
        space = load(name, values)
        created = w.api_client.do("POST", "/api/2.0/genie/spaces", body={
            "warehouse_id": warehouse,
            "title": title,
            "description": description,
            "serialized_space": json.dumps(space),
        })
        print(f"  created {name}: {created.get('space_id')}  {title}")


if __name__ == "__main__":
    main()
