"""Remove everything a course installed, and nothing else.

The course provisions a lot: schemas, tables, views, functions, a volume of
documents, Genie Agents, and the notebooks themselves. Leaving that behind after
a cohort finishes is how a workspace fills with objects nobody can attribute.

    academy.cleanup('genie-agents')                  # show what would go
    academy.cleanup('genie-agents', confirm=True)    # actually remove it

Dry run is the default and confirm=True is required, because this drops schemas.
It only removes what the course creates: the agents are matched by the titles the
package gives them, and the schemas by the layout it installed into. An agent
someone renamed, or a table someone else put in the lab schema, is reported
rather than deleted -- you are told, and you decide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._agents import _definitions, _titles
from ._catalog import get_course
from ._documents import volume_path
from ._layout import resolve, resolve_catalog


@dataclass
class CleanupPlan:
    course_id: str
    confirmed: bool
    agents: list = field(default_factory=list)
    schemas: list = field(default_factory=list)
    volume: str = ""
    notebooks: str = ""
    kept: list = field(default_factory=list)
    removed: list = field(default_factory=list)

    def __repr__(self) -> str:
        verb = "Removed" if self.confirmed else "Would remove"
        lines = [f"{verb}, for '{self.course_id}':"]
        for a in self.agents:
            lines.append(f"  agent      {a}")
        if self.volume:
            lines.append(f"  volume     {self.volume}")
        for s in self.schemas:
            lines.append(f"  schema     {s}  (and everything in it)")
        if self.notebooks:
            lines.append(f"  notebooks  {self.notebooks}")
        if not (self.agents or self.schemas or self.volume or self.notebooks):
            lines.append("  nothing found — already clean")
        if self.kept:
            lines.append("")
            lines.append("  Left alone, because the course did not create them:")
            lines += [f"    {k}" for k in self.kept]
        if not self.confirmed:
            lines.append("")
            lines.append("  Nothing was deleted. Re-run with confirm=True to remove the above.")
        return "\n".join(lines)


def cleanup(
    course_id: str,
    *,
    catalog: str | None = None,
    schema: str | None = None,
    table_prefix: str | None = None,
    title_suffix: str | None = None,
    keep_notebooks: bool = False,
    confirm: bool = False,
) -> CleanupPlan:
    """Remove a course's schemas, volume, agents and notebooks.

    Returns the plan without touching anything unless confirm=True.
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    course = get_course(course_id)
    w = WorkspaceClient()
    schema = schema or course.default_schema
    table_prefix = table_prefix or course.default_table_prefix
    if catalog is None:
        try:
            catalog = resolve_catalog(w, schema)
        except ValueError:
            catalog = None

    layout = resolve(catalog=catalog, schema=schema, table_prefix=table_prefix,
                     create_catalog=False, create_schema=None, create_volume=False)
    plan = CleanupPlan(course_id=course_id, confirmed=confirm)

    # Agents, matched by the titles this package gives them. Anything else is
    # someone's own work and is reported rather than removed.
    wanted = set()
    for name in _definitions(course):
        title, _ = _titles(course_id, name)
        wanted.add(f"{title} {title_suffix}" if title_suffix else title)
    for space in w.api_client.do("GET", "/api/2.0/genie/spaces").get("spaces", []):
        title = space.get("title") or ""
        if title in wanted:
            plan.agents.append(f"{title}  ({space['space_id']})")
            if confirm:
                w.api_client.do("DELETE", f"/api/2.0/genie/spaces/{space['space_id']}")
                plan.removed.append(title)
        elif title.startswith(tuple(t.split(" (")[0] for t in wanted)):
            plan.kept.append(f"agent '{title}' — name does not match what the course creates")

    # The documents volume, then the schemas it lives in.
    if catalog:
        plan.volume = volume_path(layout)
    targets = [layout.single_schema] if layout.is_single_schema else list(layout.schemas)
    for sc in targets:
        full = f"{catalog}.{sc}" if catalog else sc
        plan.schemas.append(full)
        if confirm:
            r = w.statement_execution.execute_statement(
                warehouse_id=next(iter(w.warehouses.list())).id,
                statement=f"DROP SCHEMA IF EXISTS {full} CASCADE", wait_timeout="50s")
            if r.status.state == StatementState.SUCCEEDED:
                plan.removed.append(full)
            else:
                plan.kept.append(f"schema {full} — {(r.status.error.message or '')[:80]}")

    if not keep_notebooks:
        try:
            me = w.current_user.me().user_name
            folder = f"/Workspace/Users/{me}/databricks360/{course.id}"
            w.workspace.get_status(folder)
            plan.notebooks = folder
            if confirm:
                w.workspace.delete(folder, recursive=True)
                plan.removed.append(folder)
        except Exception:
            plan.notebooks = ""

    return plan
