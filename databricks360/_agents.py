"""Create a course's Genie Agents from checked-in definitions.

Create Genie Space takes `warehouse_id` and the whole `serialized_space` in one
call, so an agent never has to be built by hand first. Each course ships its
agents as JSON under `courses/<course>/agents/`, which keeps the configuration
reviewable source rather than something captured out of the UI.

Unlike the SQL notebooks, this does create objects — a Genie Agent is metadata,
not data, so nothing here consumes a warehouse until someone asks the agent a
question. Run it with dry_run=True first to see what it would do.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources

from ._catalog import get_course
from ._layout import resolve
from ._notebook import render_template, unresolved_placeholders


@dataclass(frozen=True)
class CreatedAgent:
    name: str
    title: str
    space_id: str
    tables: int

    def __repr__(self) -> str:
        return f"{self.name} ({self.tables} objects) -> {self.space_id}"


@dataclass
class AgentRun:
    course_id: str
    catalog: str
    warehouse_id: str
    created: list
    missing: dict

    def __repr__(self) -> str:
        lines = [f"Genie Agents for '{self.course_id}'",
                 f"  catalog:   {self.catalog}",
                 f"  warehouse: {self.warehouse_id}"]
        if self.missing:
            lines.append("")
            lines.append("  Not created — these objects do not exist yet:")
            for agent, tables in self.missing.items():
                lines.append(f"    {agent}:")
                lines += [f"      {t}" for t in tables]
            lines.append("")
            lines.append("  Run the notebooks that create them, then call this again.")
        for a in self.created:
            lines.append(f"  created  {a.title}  ({a.tables} objects)  {a.space_id}")
        return "\n".join(lines)


def _definitions(course) -> dict:
    """Every agent definition shipped with the course, by name."""
    try:
        folder = resources.files(course.package) / "agents"
        entries = sorted(p.name for p in folder.iterdir()
                         if p.name.endswith(".geniespace.json"))
    except (FileNotFoundError, NotADirectoryError):
        return {}
    return {name[: -len(".geniespace.json")]: (folder / name).read_text(encoding="utf-8")
            for name in entries}


def _titles(course_id: str, name: str) -> tuple:
    """Title and description per agent. Kept here so the JSON stays pure config."""
    known = {
        "broken": ("Meridian Wealth (uncurated)",
                   "Every base object, one prose instruction block, no join specs. "
                   "Used in Module 7's demo and Module 13's latency lab."),
        "curated": ("Meridian Wealth & Distribution",
                    "Month-end AUM and net flows over seven curated objects. "
                    "The prepared agent from Module 7."),
    }
    return known.get(name, (f"{course_id}: {name}", ""))


def create_agents(
    course_id: str,
    *,
    catalog: str | None = None,
    schema: str | None = None,
    table_prefix: str | None = None,
    warehouse_id: str | None = None,
    only: str | None = None,
    dry_run: bool = False,
) -> AgentRun:
    """Create the Genie Agents a course's modules need.

        create_agents('genie-agents')                  # both, current catalog
        create_agents('genie-agents', dry_run=True)    # check, create nothing
        create_agents('genie-agents', only='curated')  # just one

    Object names render from the same {{CORE}}/{{STAGING}} placeholders as the
    notebooks, so the agents follow whichever layout the lab was installed with.
    """
    from databricks.sdk import WorkspaceClient

    course = get_course(course_id)
    defs = _definitions(course)
    if not defs:
        raise ValueError(f"{course_id} ships no agent definitions")
    if only:
        if only not in defs:
            raise ValueError(f"unknown agent {only!r}. Available: {', '.join(sorted(defs))}")
        defs = {only: defs[only]}

    w = WorkspaceClient()
    schema = schema or course.default_schema
    table_prefix = table_prefix or course.default_table_prefix

    # A Genie data source has no session, so it cannot resolve current_catalog()
    # the way the notebook SQL does. Its identifier must be three-level.
    if catalog is None:
        found = []
        for c in w.catalogs.list():
            try:
                if any(sc.name == schema for sc in w.schemas.list(c.name)):
                    found.append(c.name)
            except Exception:
                continue
        if len(found) != 1:
            raise ValueError(
                f"schema {schema!r} found in {found or 'no catalog'} — pass catalog="
            )
        catalog = found[0]

    if warehouse_id is None:
        warehouses = list(w.warehouses.list())
        if not warehouses:
            raise ValueError("no SQL warehouse in this workspace — pass warehouse_id=")
        warehouse_id = warehouses[0].id

    layout = resolve(catalog=catalog, schema=schema, table_prefix=table_prefix,
                     create_catalog=False, create_schema=None, create_volume=False)
    values = {"CORE": layout.core, "REF": layout.ref, "STAGING": layout.staging}

    spaces = {}
    for name, raw in defs.items():
        rendered = render_template(raw, values)
        left = unresolved_placeholders(rendered)
        if left:
            raise ValueError(f"{name}: unresolved placeholders {left}")
        spaces[name] = json.loads(rendered)

    # An agent pointed at a table that does not exist fails on every question, and
    # the failure reads as a Genie problem rather than a notebook that was skipped.
    missing = {}
    for name, space in spaces.items():
        gone = []
        for t in space["data_sources"]["tables"]:
            try:
                w.tables.get(t["identifier"])
            except Exception:
                gone.append(t["identifier"])
        if gone:
            missing[name] = gone

    run = AgentRun(course_id=course_id, catalog=catalog, warehouse_id=warehouse_id,
                   created=[], missing=missing)
    if missing or dry_run:
        return run

    for name, space in spaces.items():
        title, description = _titles(course_id, name)
        created = w.api_client.do("POST", "/api/2.0/genie/spaces", body={
            "warehouse_id": warehouse_id,
            "title": title,
            "description": description,
            "serialized_space": json.dumps(space),
        })
        run.created.append(CreatedAgent(
            name=name, title=title, space_id=created.get("space_id", "?"),
            tables=len(space["data_sources"]["tables"]),
        ))
    return run
