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
    # The course's own naming, applied by a bare install().
    assert COURSE.default_schema == "genie_agent"
    assert COURSE.default_table_prefix == "mfg_"
    assert [n.order for n in COURSE.notebooks] == sorted(n.order for n in COURSE.notebooks)
    assert set(COURSE.tiers) == {"small", "large"}


def test_every_manifest_notebook_has_its_sql():
    for nb in COURSE.notebooks:
        assert read_sql(COURSE, nb.sql).strip(), f"{nb.sql} is empty or missing"


def test_notebook_has_databricks_header_and_cells():
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog="mfg", tier="small",
                                layout=resolve_layout(catalog="mfg"))
    assert src.startswith(SQL_HEADER)
    assert src.count(CELL_DELIMITER) >= 5, "banners should have become separate cells"
    assert "-- MAGIC %md" in src, "section banners should render as markdown"


def test_catalog_is_substituted():
    src = build_notebook_source(
        COURSE, COURSE.notebooks[1], catalog="training_v2", tier="small",
        layout=resolve_layout(catalog="training_v2"),
    )
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


# Every layout must be checked, not just the default. An earlier version of this
# test only built catalog=None, where create_catalog is False — so the CREATE
# CATALOG statement was never generated and the spoiler in its COMMENT went
# unnoticed until someone ran it with create_catalog=True.
ALL_LAYOUTS = [
    ("course default", dict(schema="genie_agent", table_prefix="mfg_")),
    ("bare current catalog", dict(catalog=None)),
    ("named catalog", dict(catalog="main")),
    ("create catalog", dict(catalog="mfg", create_catalog=True)),
    ("single schema", dict(schema="training_you")),
    ("single schema, named catalog", dict(catalog="main", schema="training_you")),
    ("no volume", dict(catalog="main", create_volume=False)),
]


def test_notebooks_do_not_reveal_the_planted_flaws():
    """The notebooks must not name what is wrong with the data, in ANY layout.

    Lab 0 asks learners to predict the wrong answers an uncurated agent will give,
    and Module 4 asks them to diagnose them. A notebook captioned "FLAW #2" hands
    over both. Worse, a column comment saying "never SUM across dates" is the fix
    itself — Genie reads Unity Catalog comments, so it would stop making the
    mistake at all and Module 7 would have nothing left to teach.
    """
    spoilers = [
        "flaw",
        "never SUM",
        "Do NOT sum",
        "Enable entity matching",
        "Ask which one the user means",
        "Never mix the two",
        "will inflate transaction counts",
        "deliberate",
        "on purpose",
        "the scariest",
        "nobody would ever get",
        "teaching dataset",
    ]
    for label, kwargs in ALL_LAYOUTS:
        layout = resolve_layout(**kwargs)
        for nb in COURSE.notebooks:
            src = build_notebook_source(
                COURSE, nb, catalog=kwargs.get("catalog"), tier="small", layout=layout
            )
            low = src.lower()
            for phrase in spoilers:
                assert phrase.lower() not in low, (
                    f"[{label}] {nb.sql} reveals the answer: {phrase!r}"
                )


# 06_curated is the worked answer to the curation exercise, so its metadata is
# supposed to be rich and prescriptive. 07 documents the metric definitions for
# the same reason. The terse rule applies to the raw data a learner is handed.
ANSWER_KEY = {"06_curated.sql", "07_metric_view.sql"}


def test_column_comments_are_terse():
    """Real bank catalogues have short, unhelpful comments. Long prescriptive ones
    in the RAW data would be course-author voice leaking into production metadata —
    and would pre-empt the exercise, since Genie reads them."""
    import re

    for label, kwargs in ALL_LAYOUTS:
        layout = resolve_layout(**kwargs)
        for nb in COURSE.notebooks:
            if nb.sql in ANSWER_KEY:
                continue
            src = build_notebook_source(
                COURSE, nb, catalog=kwargs.get("catalog"), tier="small", layout=layout
            )
            for match in re.finditer(r"COMMENT '([^']+)'", src):
                body = match.group(1)
                if len(body) > 120:
                    raise AssertionError(
                        f"[{label}] {nb.sql}: comment too instructive — {body[:80]}"
                    )


def test_the_answer_key_is_actually_instructive():
    """The inverse of the rule above: 06 exists to teach, so if its metadata went
    terse it would have stopped doing its job while every test still passed."""
    curated = next(n for n in COURSE.notebooks if n.sql == "06_curated.sql")
    src = build_notebook_source(COURSE, curated, catalog=None, tier="small")
    assert 'what "revenue" means at Meridian' in src
    assert "SUM over a period is a real balance" in src
    assert "Not the same as delinquent" in src
    assert "an accounting event" in src.lower()


def test_dry_run_install_needs_no_workspace():
    result = install("genie-agents", dry_run=True, catalog="mfg", tier="small")
    assert result.catalog == "mfg"
    assert len(result.notebooks) == len(COURSE.notebooks)
    assert [n.order for n in result.notebooks] == [1, 2, 3, 4, 5, 6, 7, 99]
    rendered = repr(result)
    assert "Run these" in rendered
    assert "slow" in rendered, "the facts notebook should be flagged slow"
    assert "needs admin" in rendered, "governance should be flagged as needing privilege"


# ── Restricted Unity Catalog layouts ─────────────────────────────────────────
# A locked-down metastore is the norm in regulated environments, so all three
# shapes are covered: full control, no CREATE CATALOG, and one schema only.

from databricks360._layout import resolve as resolve_layout, setup_ddl


def test_multi_schema_layout_creates_nothing_above_schema():
    """The multi-schema layout in a governed workspace: no CREATE CATALOG at all."""
    src = build_notebook_source(
        COURSE, COURSE.notebooks[0], catalog=None, tier="small",
        layout=resolve_layout(),
    )
    assert "CREATE CATALOG IF NOT EXISTS" not in src
    # Schema names are unqualified so SQL resolves them against current_catalog().
    assert "CREATE SCHEMA IF NOT EXISTS core" in src
    assert "CREATE SCHEMA IF NOT EXISTS ref" in src
    assert "CREATE SCHEMA IF NOT EXISTS staging" in src
    assert "CREATE VOLUME IF NOT EXISTS ref.documents" in src
    # And it shows the learner where that actually is.
    assert "SELECT current_catalog() AS default_catalog" in src


def test_multi_schema_tables_are_two_level():
    src = build_notebook_source(
        COURSE, COURSE.notebooks[1], catalog=None, tier="small",
        layout=resolve_layout(),
    )
    assert "core.dim_date" in src
    assert "mfg.core" not in src


def test_named_catalog_qualifies_and_switches_to_it():
    src = build_notebook_source(
        COURSE, COURSE.notebooks[0], catalog="main", tier="small",
        layout=resolve_layout(catalog="main"),
    )
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
    """With no CREATE SCHEMA privilege, say so rather than emitting a failing statement."""
    layout = resolve_layout(catalog="main", schema="training_you", create_schema=False)
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
    multi = build_notebook_source(
        COURSE, COURSE.notebooks[0], catalog="mfg", tier="small",
        layout=resolve_layout(catalog="mfg"),
    )
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
        "genie-agents", dry_run=True, catalog="main", schema="training_you",
        create_schema=False, create_volume=False,
    )
    rendered = repr(result)
    assert "single schema: main.training_you" in rendered
    assert "CREATE SCHEMA" in rendered
    assert "CREATE VOLUME" in rendered


def test_bare_install_uses_the_course_naming():
    """install('genie-agents') with no arguments must produce the layout the
    course expects, not a generic one the caller has to remember to ask for."""
    result = install("genie-agents", dry_run=True)
    rendered = repr(result)
    assert "genie_agent" in rendered
    assert "mfg_core_dim_date" in rendered

    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog=None, tier="small",
                                layout=resolve_layout(schema=COURSE.default_schema,
                                                      table_prefix=COURSE.default_table_prefix))
    assert "genie_agent.mfg_core_dim_date" in src


# ── Table-name prefixes for a shared schema ──────────────────────────────────

def test_table_prefix_folds_the_group_into_object_names():
    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_")
    src = build_notebook_source(COURSE, COURSE.notebooks[1], catalog=None, tier="small", layout=layout)
    assert "genie_agent.mfg_core_dim_date" in src
    assert "genie_agent.mfg_core_dim_branch" in src
    # No unprefixed leftovers.
    assert "genie_agent.dim_date" not in src


def test_table_prefix_reaches_facts_and_joins():
    layout = resolve_layout(catalog="main", schema="genie_agent", table_prefix="mfg_")
    src = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="main", tier="small", layout=layout)
    assert "main.genie_agent.mfg_core_fct_transactions" in src
    # The joins must be prefixed too, or 03 breaks against 02's output.
    assert "main.genie_agent.mfg_core_dim_account" in src
    assert "main.genie_agent.mfg_core_dim_customer" in src


def test_prefixed_volume_lands_in_the_same_schema():
    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_")
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog=None, tier="small", layout=layout)
    assert "CREATE VOLUME IF NOT EXISTS genie_agent.mfg_ref_documents" in src
    # Creation is attempted by default now; the schema is normally ours to make.
    assert "CREATE SCHEMA IF NOT EXISTS genie_agent" in src


def test_prefix_never_leaks_into_the_schema_name():
    """The prefix names objects, not the schema that holds them."""
    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_", create_schema=True)
    src = build_notebook_source(COURSE, COURSE.notebooks[0], catalog=None, tier="small", layout=layout)
    assert "CREATE SCHEMA IF NOT EXISTS genie_agent" in src
    assert "mfg_core_genie_agent" not in src
    assert "CREATE SCHEMA IF NOT EXISTS genie_agent.mfg" not in src


def test_prefix_without_a_schema_is_rejected():
    try:
        resolve_layout(table_prefix="mfg_")
    except ValueError as exc:
        assert "single-schema" in str(exc)
    else:
        raise AssertionError("table_prefix with no schema should raise")


def test_prefix_must_be_a_safe_identifier():
    for bad in ["mfg-", "mfg.", "mfg core"]:
        try:
            resolve_layout(schema="s", table_prefix=bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"{bad!r} should have been rejected")


def test_no_unresolved_placeholders_with_a_prefix():
    layout = resolve_layout(catalog="main", schema="genie_agent", table_prefix="mfg_")
    for nb in COURSE.notebooks:
        src = build_notebook_source(COURSE, nb, catalog="main", tier="small", layout=layout)
        assert unresolved_placeholders(src) == [], nb.sql


def test_install_shows_an_example_object_name():
    result = install("genie-agents", dry_run=True, schema="genie_agent", table_prefix="mfg_")
    assert "genie_agent.mfg_core_dim_date" in repr(result)


# ── Which notebooks are actually required ────────────────────────────────────

def test_only_the_first_three_are_required():
    required = [n.name for n in COURSE.notebooks if n.required]
    assert required == ["01_catalog_and_schemas", "02_dimensions", "03_facts"]


def test_optional_notebooks_say_what_they_are_for():
    for nb in COURSE.notebooks:
        if not nb.required:
            assert nb.needed_for, f"{nb.name} is optional but does not say why to run it"


def test_governance_does_not_depend_on_staging():
    """05 used to tag tables that 04 creates, so skipping 04 broke 05. Objects are
    now tagged where they are created."""
    gov = next(n for n in COURSE.notebooks if n.name == "05_governance")
    src = build_notebook_source(COURSE, gov, catalog=None, tier="small")
    assert "fct_txn_legacy" not in src.replace("in notebook 04", "")
    assert "fct_transactions_raw" not in src

    staging = next(n for n in COURSE.notebooks if n.name == "04_staging")
    src04 = build_notebook_source(COURSE, staging, catalog=None, tier="small")
    assert "SET TAGS" in src04, "04 should tag its own objects"
    assert "deprecated" in src04


def test_metric_view_declares_its_dependency():
    mv = next(n for n in COURSE.notebooks if n.name == "07_metric_view")
    assert mv.depends_on == "06_curated"
    src = build_notebook_source(COURSE, mv, catalog=None, tier="small")
    # It sources views that 06 creates, so the dependency is real, not advisory.
    assert "vw_transactions_net" in src
    assert "dim_customer_safe" in src


def test_validate_needs_only_the_required_notebooks():
    """99 must work on a minimal install, or it cannot confirm one."""
    val = next(n for n in COURSE.notebooks if n.name == "99_validate")
    src = build_notebook_source(COURSE, val, catalog=None, tier="small")
    for optional_object in ["fct_txn_legacy", "fct_transactions_raw",
                            "vw_transactions_net", "vw_loan_book_eop",
                            "mv_banking_metrics"]:
        assert optional_object not in src, f"99 references {optional_object} from an optional notebook"


def test_install_summary_separates_required_from_optional():
    rendered = repr(install("genie-agents", dry_run=True))
    assert "not usable without them" in rendered
    assert "as the course needs them" in rendered
    assert "Modules 6, 7, 12, 13" in rendered
    assert "after 06_curated" in rendered
