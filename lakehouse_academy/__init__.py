"""Lakehouse Academy — install Databricks course lab environments.

Run inside a Databricks notebook:

    %pip install lakehouse-academy
    dbutils.library.restartPython()

    import lakehouse_academy as academy
    academy.list_courses()
    academy.install('genie-agents')

`install` writes the lab notebooks into your workspace. You then run them in
order. Nothing is executed for you: generating the data is real work on your
warehouse, and watching it happen is part of the lesson.
"""

from __future__ import annotations

from ._catalog import Course, available_courses, get_course
from ._install import Installation, build_notebook_source, install

__version__ = "0.1.0"
__all__ = [
    "install",
    "list_courses",
    "get_course",
    "available_courses",
    "build_notebook_source",
    "Course",
    "Installation",
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
        print(f"  catalog: {course.default_catalog}   notebooks: {len(course.notebooks)}")
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
