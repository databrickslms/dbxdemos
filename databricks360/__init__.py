"""Lakehouse Academy — install Databricks course lab environments.

Run inside a Databricks notebook:

    %pip install databricks360
    dbutils.library.restartPython()

    import databricks360 as academy
    academy.list_courses()
    academy.install('genie-agents')

`install` writes the lab notebooks into your workspace. You then run them in
order. Nothing is executed for you: generating the data is real work on your
warehouse, and watching it happen is part of the lesson.
"""

from __future__ import annotations

from ._catalog import Course, available_courses, get_course
from ._install import Installation, build_notebook_source, install
from ._layout import Layout, resolve as resolve_layout

__version__ = "0.6.3"
__all__ = [
    "install",
    "list_courses",
    "get_course",
    "available_courses",
    "build_notebook_source",
    "Course",
    "Installation",
    "Layout",
    "resolve_layout",
    "__version__",
]


def list_courses() -> None:
    """Print the available course labs."""
    courses = available_courses()
    if not courses:
        print("No courses bundled in this build.")
        return

    for course in courses:
        print(f"\n{course.id}")
        print(f"  {course.title}")
        if course.description:
            for line in _wrap(course.description, 76):
                print(f"    {line}")
        required = sum(1 for n in course.notebooks if n.required)
        where = course.default_schema or "core / ref / staging"
        naming = f"{where}.{course.default_table_prefix}<group>_*" if course.default_table_prefix else where
        print(f"  objects:   {naming}")
        print(f"  notebooks: {len(course.notebooks)} ({required} required)")
        if course.tiers:
            print("  tiers:")
            for name, tier in course.tiers.items():
                marker = " (default)" if name == course.default_tier else ""
                print(f"    {name}{marker} — {tier.description}")
    print(f"\nInstall with: academy.install('{courses[0].id}')\n")


def _wrap(text: str, width: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        if len(current) + len(word) + 1 > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines
