"""Materialise a course's lab notebooks into a Databricks workspace.

Designed to run from inside a Databricks notebook, where databricks-sdk picks up
the notebook's own identity — no host, token or profile to configure. It also
works from a laptop if a Databricks CLI profile is present.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ._catalog import Course, Notebook, read_sql
from ._layout import Layout, resolve as resolve_layout, schema_list_sql, setup_ddl
from ._notebook import render_template, sql_to_notebook, unresolved_placeholders


@dataclass
class InstalledNotebook:
    order: int
    name: str
    path: str
    slow: bool
    requires_admin: bool


@dataclass
class Installation:
    course_id: str
    folder: str
    catalog: str
    tier: str
    notebooks: list[InstalledNotebook]
    layout: Layout | None = None

    def __repr__(self) -> str:  # what a notebook cell shows
        lines = [
            f"Installed '{self.course_id}' → {self.folder}",
            f"  tier: {self.tier}",
        ]
        if self.layout:
            lines.append(f"  {self.layout.describe()}")
            skipped = [
                label for label, on in (
                    # Not "skipped" when no catalog was named — describe() already
                    # says we are using current_catalog(), and there is nothing to skip.
                    ("CREATE CATALOG", self.layout.create_catalog or self.layout.uses_current_catalog),
                    ("CREATE SCHEMA", self.layout.create_schema),
                    ("CREATE VOLUME", self.layout.create_volume),
                ) if not on
            ]
            if skipped:
                lines.append(f"  skipping: {', '.join(skipped)}")
        lines += ["", "  Run these in order:"]
        for nb in self.notebooks:
            flags = []
            if nb.slow:
                flags.append("slow")
            if nb.requires_admin:
                flags.append("needs admin")
            suffix = f"   ({', '.join(flags)})" if flags else ""
            lines.append(f"    {nb.order}. {nb.name}{suffix}")
        return "\n".join(lines)


def _workspace_client():
    try:
        from databricks.sdk import WorkspaceClient
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "databricks-sdk is required. Inside a Databricks notebook run:\n"
            "    %pip install databricks360\n"
            "    dbutils.library.restartPython()"
        ) from exc
    return WorkspaceClient()


def _default_folder(client, course: Course) -> str:
    """Default to the caller's home folder, matching how dbdemos behaves."""
    try:
        user = client.current_user.me().user_name
    except Exception:  # pragma: no cover - offline / unauthenticated
        user = None
    base = f"/Workspace/Users/{user}" if user else "/Workspace/Shared"
    return f"{base}/databricks360/{course.id}"


def build_notebook_source(
    course: Course,
    notebook: Notebook,
    *,
    catalog: str,
    tier: str,
    layout: Layout | None = None,
) -> str:
    """Render one notebook's source. Pure — no workspace calls, so it is testable."""
    if tier not in course.tiers and course.tiers:
        known = ", ".join(sorted(course.tiers))
        raise ValueError(f"Unknown tier {tier!r} for {course.id}. Available: {known}")

    layout = layout or resolve_layout(catalog=catalog)

    values = {
        "CATALOG": layout.catalog or "current_catalog()",
        "INFO_SCHEMA": (
            "information_schema" if layout.catalog is None
            else f"{layout.catalog}.information_schema"
        ),
        "CORE": layout.core,
        "REF": layout.ref,
        "STAGING": layout.staging,
        "SCHEMA_LIST": schema_list_sql(layout),
        "SETUP_DDL": setup_ddl(layout),
        "TIER": tier,
    }
    if course.tiers:
        values.update(course.tiers[tier].values)

    sql = render_template(read_sql(course, notebook.sql), values)
    intro = render_template(notebook.intro, values)
    source = sql_to_notebook(sql, title=notebook.title, intro=intro or None)

    leftover = unresolved_placeholders(source)
    if leftover:
        raise ValueError(
            f"{notebook.sql}: unresolved placeholders {leftover}. "
            "Add them to the tier values in manifest.json, or fix the typo."
        )
    return source


def install(
    course_id: str,
    *,
    path: str | None = None,
    catalog: str | None = None,
    schema: str | None = None,
    tier: str | None = None,
    create_catalog: bool = False,
    create_schema: bool | None = None,
    create_volume: bool = True,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Installation:
    """Create the lab notebooks for a course in the workspace.

    Notebooks are written but never executed. Data generation is deliberate work
    on the learner's warehouse, and Module 0 of the course is partly about
    watching it happen rather than having it appear.

    By default the lab lands in the session's current catalog and nothing is
    created above schema level, which is what a governed workspace normally allows:

        install('genie-agents')                              # current_catalog()
        install('genie-agents', catalog='main')              # a catalog you were granted
        install('genie-agents', catalog='mfg', create_catalog=True)
        install('genie-agents', schema='training_you')       # one schema you own

    Passing `schema` puts every object in that one schema and assumes you cannot
    create it either, since that is why you would reach for it.
    """
    from ._catalog import get_course

    course = get_course(course_id)
    tier = tier or course.default_tier
    # catalog=None means the session's current catalog. The manifest's
    # default_catalog is only a suggestion for people who can create one.
    layout = resolve_layout(
        catalog=catalog,
        schema=schema,
        create_catalog=create_catalog,
        create_schema=create_schema,
        create_volume=create_volume,
    )

    client = None if dry_run else _workspace_client()
    folder = path or (
        f"/Workspace/Shared/databricks360/{course.id}"
        if dry_run
        else _default_folder(client, course)
    )
    folder = folder.rstrip("/")

    installed: list[InstalledNotebook] = []

    if not dry_run:
        from databricks.sdk.service.workspace import ImportFormat, Language

        client.workspace.mkdirs(folder)

    for nb in course.notebooks:
        source = build_notebook_source(course, nb, catalog=catalog, tier=tier, layout=layout)
        target = f"{folder}/{nb.name}"

        if not dry_run:
            client.workspace.import_(
                path=target,
                content=base64.b64encode(source.encode("utf-8")).decode("ascii"),
                format=ImportFormat.SOURCE,
                language=Language.SQL,
                overwrite=overwrite,
            )

        installed.append(
            InstalledNotebook(
                order=nb.order, name=nb.name, path=target,
                slow=nb.slow, requires_admin=nb.requires_admin,
            )
        )

    return Installation(
        course_id=course.id, folder=folder,
        catalog=layout.catalog or "current_catalog()",
        tier=tier, notebooks=installed, layout=layout,
    )
