"""Materialise a course's lab notebooks into a Databricks workspace.

Designed to run from inside a Databricks notebook, where databricks-sdk picks up
the notebook's own identity — no host, token or profile to configure. It also
works from a laptop if a Databricks CLI profile is present.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass

from ._catalog import Course, Notebook, read_sql
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

    def __repr__(self) -> str:  # what a notebook cell shows
        lines = [
            f"Installed '{self.course_id}' → {self.folder}",
            f"  catalog: {self.catalog}    tier: {self.tier}",
            "",
            "  Run these in order:",
        ]
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
            "    %pip install lakehouse-academy\n"
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
    return f"{base}/lakehouse-academy/{course.id}"


def build_notebook_source(
    course: Course,
    notebook: Notebook,
    *,
    catalog: str,
    tier: str,
) -> str:
    """Render one notebook's source. Pure — no workspace calls, so it is testable."""
    if tier not in course.tiers and course.tiers:
        known = ", ".join(sorted(course.tiers))
        raise ValueError(f"Unknown tier {tier!r} for {course.id}. Available: {known}")

    values = {"CATALOG": catalog, "TIER": tier}
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
    tier: str | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> Installation:
    """Create the lab notebooks for a course in the workspace.

    Notebooks are written but never executed. Data generation is deliberate work
    on the learner's warehouse, and Module 0 of the course is partly about
    watching it happen rather than having it appear.
    """
    from ._catalog import get_course

    course = get_course(course_id)
    catalog = catalog or course.default_catalog
    tier = tier or course.default_tier

    client = None if dry_run else _workspace_client()
    folder = path or (
        f"/Workspace/Shared/lakehouse-academy/{course.id}"
        if dry_run
        else _default_folder(client, course)
    )
    folder = folder.rstrip("/")

    installed: list[InstalledNotebook] = []

    if not dry_run:
        from databricks.sdk.service.workspace import ImportFormat, Language

        client.workspace.mkdirs(folder)

    for nb in course.notebooks:
        source = build_notebook_source(course, nb, catalog=catalog, tier=tier)
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
        course_id=course.id, folder=folder, catalog=catalog,
        tier=tier, notebooks=installed,
    )
