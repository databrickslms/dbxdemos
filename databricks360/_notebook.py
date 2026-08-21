"""Turn a plain .sql file into Databricks notebook source.

Databricks notebooks are stored as a flat source file: a header comment naming
the language, cells separated by a magic delimiter, and markdown cells prefixed
with a MAGIC marker. Generating that here means the SQL files stay ordinary,
runnable SQL that anyone can open in a text editor or paste into an editor tab.
"""

from __future__ import annotations

import re

CELL_DELIMITER = "-- COMMAND ----------"
SQL_HEADER = "-- Databricks notebook source"

# A run of dashes at least this long marks a section heading in the SQL files.
_BANNER = re.compile(r"^-- =={2,}\s*$")


def _md_cell(lines: list[str]) -> str:
    """Render markdown as a %md cell."""
    body = "\n".join(f"-- MAGIC {line}" if line else "-- MAGIC" for line in lines)
    return f"-- MAGIC %md\n{body}"


def split_sql_sections(sql: str) -> list[tuple[str, str]]:
    """Split a lab SQL file into (title, body) sections on its banner comments.

    The lab files use a banner of the form:

        -- ====================================
        -- dim_date  —  FLAW #2: ...
        -- more description
        -- ====================================

    Each banner starts a new notebook cell, with the banner text becoming a
    markdown cell above the SQL. Files without banners return a single section.
    """
    lines = sql.splitlines()
    sections: list[tuple[str, list[str]]] = []
    current_title = ""
    current_body: list[str] = []
    i = 0

    while i < len(lines):
        if _BANNER.match(lines[i]):
            # Collect the comment block until the closing banner.
            j = i + 1
            header: list[str] = []
            while j < len(lines) and not _BANNER.match(lines[j]):
                header.append(re.sub(r"^--\s?", "", lines[j]))
                j += 1
            if j < len(lines):  # closing banner found
                if current_body or current_title:
                    sections.append((current_title, current_body))
                current_title = "\n".join(header).strip()
                current_body = []
                i = j + 1
                continue
        current_body.append(lines[i])
        i += 1

    if current_body or current_title:
        sections.append((current_title, current_body))

    return [(t, "\n".join(b).strip()) for t, b in sections]


def sql_to_notebook(
    sql: str,
    *,
    title: str,
    intro: str | None = None,
) -> str:
    """Build Databricks SQL notebook source from a lab SQL file."""
    cells: list[str] = []

    heading = [f"# {title}"]
    if intro:
        heading += ["", *intro.splitlines()]
    cells.append(_md_cell(heading))

    for section_title, body in split_sql_sections(sql):
        if section_title:
            first, *rest = section_title.splitlines()
            md = [f"## {first.strip()}"]
            if rest:
                md += ["", *[line.strip() for line in rest]]
            cells.append(_md_cell(md))
        if body:
            cells.append(body)

    return f"{SQL_HEADER}\n" + f"\n\n{CELL_DELIMITER}\n\n".join(cells) + "\n"


def render_template(sql: str, values: dict[str, str]) -> str:
    """Substitute {{PLACEHOLDER}} tokens. Unknown tokens are left untouched so a
    typo shows up in the notebook rather than silently becoming an empty string."""
    out = sql
    for key, value in values.items():
        out = out.replace(f"{{{{{key}}}}}", str(value))
    return out


def unresolved_placeholders(text: str) -> list[str]:
    """Any {{TOKEN}} left after substitution — a bug worth failing loudly on."""
    return sorted(set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", text)))
