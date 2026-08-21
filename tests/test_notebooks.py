"""Tests for notebook generation. All pure — no workspace needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lakehouse_academy as academy
from lakehouse_academy._catalog import get_course, read_sql
from lakehouse_academy._install import build_notebook_source, install
from lakehouse_academy._notebook import (
    CELL_DELIMITER, SQL_HEADER, split_sql_sections, unresolved_placeholders,
)

COURSE = get_course("genie-agents")


def test_course_loads():
    assert COURSE.id == "genie-agents"
    assert COURSE.default_catalog == "mfg"
    assert [n.order for n in COURSE.notebooks] == sorted(n.order for n in COURSE.notebooks)
    assert set(COURSE.tiers) == {"small", "large"}


def test_every_manifest_notebook_has_its_sql():
    for nb in COURSE.notebooks:
        assert read_sql(COURSE, nb.sql).strip(), f"{nb.sql} is empty or missing"


def test_notebook_has_databricks_header_and_cells():
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog="mfg", tier="small")
    assert src.startswith(SQL_HEADER)
    assert src.count(CELL_DELIMITER) >= 5, "banners should have become separate cells"
    assert "-- MAGIC %md" in src, "section banners should render as markdown"


def test_catalog_is_substituted():
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog="training_v2", tier="small")
    assert "training_v2.core.dim_date" in src
    assert "mfg.core" not in src
    assert "{{CATALOG}}" not in src


def _tier_line(src: str) -> str:
    """The one generated line that actually sets scale. The file header documents
    both tiers, so a bare substring search would match the docs, not the code."""
    return next(
        l for l in src.splitlines()
        if "<< TIER >>" in l and "range(1," in l and not l.startswith("-- MAGIC")
    )


def test_tier_controls_row_count():
    small = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="mfg", tier="small")
    large = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="mfg", tier="large")
    assert "range(1, 20000000 + 1)" in _tier_line(small)
    assert "range(1, 900000000 + 1)" in _tier_line(large)
    assert "900000000" not in _tier_line(small)


def test_no_unresolved_placeholders_anywhere():
    for nb in COURSE.notebooks:
        for tier in COURSE.tiers:
            src = build_notebook_source(COURSE, nb, catalog="mfg", tier=tier)
            assert unresolved_placeholders(src) == [], f"{nb.sql} @ {tier}"


def test_unknown_tier_is_rejected():
    try:
        build_notebook_source(COURSE, COURSE.notebooks[0], catalog="mfg", tier="enormous")
    except ValueError as exc:
        assert "enormous" in str(exc) and "small" in str(exc)
    else:
        raise AssertionError("an unknown tier should raise")


def test_unknown_course_lists_what_exists():
    try:
        academy.get_course("does-not-exist")
    except ValueError as exc:
        assert "genie-agents" in str(exc)
    else:
        raise AssertionError("an unknown course should raise")


def test_banner_splitting_finds_sections():
    sections = split_sql_sections(read_sql(COURSE, "02_dimensions.sql"))
    titles = " ".join(t for t, _ in sections)
    for expected in ["dim_date", "dim_branch", "dim_product", "dim_customer"]:
        assert expected in titles


def test_flaw_comments_survive_into_the_notebook():
    """The teaching lives in the column comments, so they must reach the notebook."""
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog="mfg", tier="small")
    assert "STARTS 1 OCTOBER" in src
    assert "users say the full state name" in src.replace("\n", " ").lower()

    facts = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="mfg", tier="small")
    assert "ONE ROW PER ACCOUNT PER DAY" in facts
    assert "never SUM" in facts


def test_dry_run_install_needs_no_workspace():
    result = install("genie-agents", dry_run=True, catalog="mfg", tier="small")
    assert result.catalog == "mfg"
    assert len(result.notebooks) == len(COURSE.notebooks)
    assert [n.order for n in result.notebooks] == [1, 2, 3]
    rendered = repr(result)
    assert "Run these in order" in rendered
    assert "slow" in rendered, "the facts notebook should be flagged slow"
