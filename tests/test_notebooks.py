"""Tests for notebook generation. All pure — no workspace needed."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import databricks360 as academy
from databricks360._catalog import get_course, read_sql
from databricks360._install import build_notebook_source, install
from databricks360._notebook import (
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


# ── Restricted Unity Catalog layouts ─────────────────────────────────────────
# A locked-down metastore is the norm in regulated environments, so all three
# shapes are covered: full control, no CREATE CATALOG, and one schema only.

from databricks360._layout import resolve as resolve_layout, setup_ddl


def test_default_uses_current_catalog_and_creates_nothing_above_schema():
    """The safe default for a governed workspace: no CREATE CATALOG at all."""
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog=None, tier="small")
    assert "CREATE CATALOG IF NOT EXISTS" not in src
    # Schema names are unqualified so SQL resolves them against current_catalog().
    assert "CREATE SCHEMA IF NOT EXISTS core" in src
    assert "CREATE SCHEMA IF NOT EXISTS ref" in src
    assert "CREATE SCHEMA IF NOT EXISTS staging" in src
    assert "CREATE VOLUME IF NOT EXISTS ref.documents" in src
    # And it shows the learner where that actually is.
    assert "SELECT current_catalog() AS default_catalog" in src


def test_default_layout_tables_are_two_level():
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog=None, tier="small")
    assert "core.dim_date" in src
    assert "mfg.core" not in src


def test_named_catalog_qualifies_and_switches_to_it():
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="main", tier="small")
    assert "USE CATALOG main;" in src
    assert "CREATE CATALOG IF NOT EXISTS" not in src
    assert "CREATE SCHEMA IF NOT EXISTS main.core" in src


def test_creating_a_catalog_is_opt_in():
    layout = resolve_layout(catalog="mfg", create_catalog=True)
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="mfg", tier="small", layout=layout)
    assert "CREATE CATALOG IF NOT EXISTS mfg" in src
    assert "CREATE SCHEMA IF NOT EXISTS mfg.core" in src


def test_create_catalog_without_a_name_is_rejected():
    try:
        resolve_layout(create_catalog=True)
    except ValueError as exc:
        assert "current_catalog()" in str(exc)
    else:
        raise AssertionError("create_catalog=True with no catalog should raise")


def test_no_create_catalog_privilege():
    layout = resolve_layout(catalog="main")
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="main", tier="small", layout=layout)
    assert "CREATE CATALOG IF NOT EXISTS" not in src
    assert "No CREATE CATALOG attempted" in src
    # Schemas are still created inside the catalog we were given.
    assert "CREATE SCHEMA IF NOT EXISTS main.core" in src


def test_single_schema_layout_collapses_everything():
    layout = resolve_layout(catalog="main", schema="training_you")
    for nb in COURSE.notebooks:
        src = build_notebook_source(COURSE, nb, catalog="main", tier="small", layout=layout)
        assert unresolved_placeholders(src) == [], nb.sql
        # No three-level path may reference a schema we were never given.
        for forbidden in ["main.core.", "main.ref.", "main.staging."]:
            assert forbidden not in src, f"{nb.sql} still references {forbidden}"

    facts = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="main", tier="small", layout=layout)
    assert "main.training_you.fct_transactions" in facts
    assert "main.training_you.dim_account" in facts


def test_single_schema_skips_ddl_it_cannot_run():
    layout = resolve_layout(catalog="main", schema="training_you")
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="main", tier="small", layout=layout)
    assert "CREATE CATALOG IF NOT EXISTS" not in src
    assert "Skipping CREATE SCHEMA" in src
    # The volume still lands in the one schema we do own.
    assert "CREATE VOLUME IF NOT EXISTS main.training_you.documents" in src


def test_create_volume_can_be_declined():
    layout = resolve_layout(catalog="main", schema="training_you", create_volume=False)
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="main", tier="small", layout=layout)
    assert "CREATE VOLUME IF NOT EXISTS" not in src
    assert "Modules 3 and 16" in src, "should say what is lost by skipping it"


def test_verify_query_lists_the_right_schemas():
    multi = build_notebook_source(COURSE, COURSE.notebooks[0], catalog="mfg", tier="small")
    assert "'core', 'ref', 'staging'" in multi
    single = build_notebook_source(
        COURSE, COURSE.notebooks[0], catalog="main", tier="small",
        layout=resolve_layout(catalog="main", schema="training_you"),
    )
    assert "'training_you'" in single


def test_qualified_names_are_rejected():
    for bad in [{"catalog": "main.core"}, {"catalog": "main", "schema": "a.b"}]:
        try:
            resolve_layout(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad} should have been rejected")


def test_install_reports_what_it_skipped():
    result = install(
        "genie-agents", dry_run=True, catalog="main", schema="training_you", create_volume=False,
    )
    rendered = repr(result)
    assert "single schema: main.training_you" in rendered
    assert "CREATE CATALOG" in rendered and "CREATE SCHEMA" in rendered
    assert "CREATE VOLUME" in rendered
