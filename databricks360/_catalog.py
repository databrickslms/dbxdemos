"""Course discovery: reads the manifests bundled with the package."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any


@dataclass(frozen=True)
class Notebook:
    """One notebook in a course's lab, in run order."""

    order: int
    name: str
    sql: str
    title: str
    intro: str = ""
    requires_admin: bool = False
    slow: bool = False
    required: bool = True
    needed_for: str = ""
    depends_on: str = ""


@dataclass(frozen=True)
class Tier:
    name: str
    values: dict
    description: str = ""


@dataclass(frozen=True)
class Course:
    id: str
    title: str
    description: str
    # The course's own naming. install() uses these unless overridden, so the
    # plain call produces the layout the course actually expects.
    default_schema: str | None
    default_table_prefix: str | None
    notebooks: list = field(default_factory=list)
    tiers: dict = field(default_factory=dict)
    default_tier: str = "small"

    @property
    def package(self) -> str:
        return f"databricks360.courses.{self.id.replace('-', '_')}"


def _course_packages() -> list:
    root = resources.files("databricks360.courses")
    return sorted(
        p.name
        for p in root.iterdir()
        if p.is_dir() and not p.name.startswith("_") and (p / "manifest.json").is_file()
    )


def _load(pkg_name: str) -> Course:
    raw: dict = json.loads(
        (resources.files(f"databricks360.courses.{pkg_name}") / "manifest.json")
        .read_text(encoding="utf-8")
    )
    return Course(
        id=raw["id"],
        title=raw["title"],
        description=raw.get("description", ""),
        default_schema=raw.get("default_schema"),
        default_table_prefix=raw.get("default_table_prefix"),
        default_tier=raw.get("default_tier", "small"),
        notebooks=[
            Notebook(
                order=n["order"],
                name=n["name"],
                sql=n["sql"],
                title=n["title"],
                intro=n.get("intro", ""),
                requires_admin=n.get("requires_admin", False),
                slow=n.get("slow", False),
                required=n.get("required", True),
                needed_for=n.get("needed_for", ""),
                depends_on=n.get("depends_on", ""),
            )
            for n in sorted(raw["notebooks"], key=lambda n: n["order"])
        ],
        tiers={
            name: Tier(name=name, values=t["values"], description=t.get("description", ""))
            for name, t in raw.get("tiers", {}).items()
        },
    )


def available_courses() -> list:
    return [_load(p) for p in _course_packages()]


def get_course(course_id: str) -> Course:
    wanted = course_id.replace("-", "_")
    for pkg in _course_packages():
        if pkg == wanted:
            return _load(pkg)
    known = ", ".join(c.id for c in available_courses()) or "none"
    raise ValueError(f"Unknown course {course_id!r}. Available: {known}")


def read_sql(course: Course, filename: str) -> str:
    return (resources.files(course.package) / filename).read_text(encoding="utf-8")
