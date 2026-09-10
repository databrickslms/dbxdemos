"""Tests for notebook generation. All pure — no workspace needed."""

from __future__ import annotations

import re
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
    for expected in ["dim_date", "dim_portfolio", "dim_client", "dim_asset_class"]:
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
    assert 'what "AUM" means at Meridian' in src
    assert "SUM over a period is a real balance" in src
    assert "assets under advisement, not AUM" in src
    assert "must not be counted as either" in src


def test_dry_run_install_needs_no_workspace():
    result = install("genie-agents", dry_run=True, catalog="mfg", tier="small")
    assert result.catalog == "mfg"
    assert len(result.notebooks) == len(COURSE.notebooks)
    assert [n.order for n in result.notebooks] == [1, 2, 3, 4, 5, 6, 7, 8, 99, 100]
    rendered = repr(result)
    assert "Run these" in rendered
    assert "slow" not in rendered, "no notebook is slow at the small tier any more"
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
    assert "main.training_you.fct_aum_snapshot" in facts
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
    assert "genie_agent.mfg_core_dim_portfolio" in src
    # No unprefixed leftovers.
    assert "genie_agent.dim_date" not in src


def test_table_prefix_reaches_facts_and_joins():
    layout = resolve_layout(catalog="main", schema="genie_agent", table_prefix="mfg_")
    src = build_notebook_source(COURSE, COURSE.notebooks[2], catalog="main", tier="small", layout=layout)
    assert "main.genie_agent.mfg_core_fct_aum_snapshot" in src
    # The joins must be prefixed too, or 03 breaks against 02's output.
    assert "main.genie_agent.mfg_core_dim_account" in src


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

def test_required_notebooks_are_the_dataset_and_its_check():
    """99_validate is required too — an unverified dataset silently breaks later
    modules, and the checks are what catch a half-finished install."""
    required = [n.name for n in COURSE.notebooks if n.required]
    assert required == [
        "01_catalog_and_schemas",
        "02_dimensions",
        "03_facts",
        "99_validate",
    ]


def test_optional_notebooks_say_what_they_are_for():
    for nb in COURSE.notebooks:
        if not nb.required:
            assert nb.needed_for, f"{nb.name} is optional but does not say why to run it"


def test_governance_does_not_depend_on_staging():
    """05 used to tag tables that 04 creates, so skipping 04 broke 05. Objects are
    now tagged where they are created."""
    gov = next(n for n in COURSE.notebooks if n.name == "05_governance")
    src = build_notebook_source(COURSE, gov, catalog=None, tier="small")
    assert "fct_aum_legacy" not in src.replace("in notebook 04", "")
    assert "fct_holdings_raw" not in src

    staging = next(n for n in COURSE.notebooks if n.name == "04_staging")
    src04 = build_notebook_source(COURSE, staging, catalog=None, tier="small")
    assert "SET TAGS" in src04, "04 should tag its own objects"
    assert "deprecated" in src04


def test_metric_view_declares_its_dependency():
    mv = next(n for n in COURSE.notebooks if n.name == "07_metric_view")
    assert mv.depends_on == "06_curated"
    src = build_notebook_source(COURSE, mv, catalog=None, tier="small")
    # It sources views that 06 creates, so the dependency is real, not advisory.
    assert "vw_aum_reporting" in src
    assert "dim_client_safe" in src


def test_validate_needs_only_the_required_notebooks():
    """99 must work on a minimal install, or it cannot confirm one."""
    val = next(n for n in COURSE.notebooks if n.name == "99_validate")
    src = build_notebook_source(COURSE, val, catalog=None, tier="small")
    for optional_object in ["fct_aum_legacy", "fct_holdings_raw",
                            "vw_aum_reporting", "vw_net_flows",
                            "mv_wealth_metrics"]:
        assert optional_object not in src, f"99 references {optional_object} from an optional notebook"


def test_install_summary_separates_required_from_optional():
    rendered = repr(install("genie-agents", dry_run=True))
    assert "not usable without them" in rendered
    assert "as the course needs them" in rendered
    assert "Modules 6, 7, 12, 13" in rendered
    assert "after 06_curated" in rendered


# ── The public API surface ───────────────────────────────────────────────────
# list_courses() shipped broken in 0.5.0 and 0.6.x: it still referenced
# Course.default_catalog, removed when the naming moved into the manifest. No
# test had ever called it, so 40 tests passed while the first command in the
# README crashed.

def test_list_courses_runs():
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        academy.list_courses()
    printed = buf.getvalue()
    assert "genie-agents" in printed
    assert "genie_agent" in printed, "should show where objects land"
    assert "required" in printed, "should say how many notebooks are needed"


def test_every_public_name_is_importable():
    for name in academy.__all__:
        assert hasattr(academy, name), f"__all__ exports {name} but it is missing"


def test_repr_of_a_dry_run_does_not_raise():
    repr(install("genie-agents", dry_run=True))
    repr(install("genie-agents", dry_run=True, schema="s", create_volume=False))


def test_catalogue_description_does_not_editorialise():
    """It prints on a learner's screen, so it describes the data, not the design."""
    for phrase in ["on purpose", "deliberate", "flaw", "do not tidy"]:
        assert phrase not in COURSE.description.lower()


def test_tier_descriptions_do_not_editorialise():
    for name, tier in COURSE.tiers.items():
        for phrase in ["on purpose", "deliberate", "flaw"]:
            assert phrase not in tier.description.lower(), f"tier {name}: {tier.description}"


# ── Genie Agent definitions ──────────────────────────────────────────────────
# The agents are config, not code, so nothing type-checks them. These tests are
# the only thing standing between a typo and an agent that fails every question.

def test_agent_definitions_render_with_no_unresolved_placeholders():
    from databricks360._agents import _definitions
    from databricks360._notebook import render_template, unresolved_placeholders

    for label, kwargs in ALL_LAYOUTS:
        layout = resolve_layout(**kwargs)
        from databricks360._documents import volume_path
        values = {"CORE": layout.core, "REF": layout.ref, "STAGING": layout.staging,
                  "VOLUME": volume_path(layout)}
        for name, raw in _definitions(COURSE).items():
            left = unresolved_placeholders(render_template(raw, values))
            assert not left, f"[{label}] {name}: unresolved {left}"


def test_agents_only_reference_objects_the_lab_creates():
    """An agent pointed at an object no notebook creates fails on every question,
    and the failure reads as a Genie problem rather than a missing table."""
    import json
    from databricks360._agents import _definitions
    from databricks360._catalog import read_sql
    from databricks360._notebook import render_template

    created = set()
    for nb in COURSE.notebooks:
        if nb.language != "sql":
            continue
        for m in re.finditer(
            r"CREATE (?:OR REPLACE )?(?:VIEW|TABLE)\s+\{\{(\w+)\}\}(\w+)",
            read_sql(COURSE, nb.sql),
        ):
            created.add(f"{{{{{m.group(1)}}}}}{m.group(2)}")

    for name, raw in _definitions(COURSE).items():
        space = json.loads(render_template(raw, {}))
        for table in space["data_sources"].get("tables", []):
            assert table["identifier"] in created, (
                f"{name} references {table['identifier']}, which no notebook creates"
            )


def test_agent_sql_only_references_columns_that_exist():
    """Catches an invented column in a snippet or example query."""
    import json
    from databricks360._agents import _definitions
    from databricks360._catalog import read_sql
    from databricks360._notebook import render_template

    curated_sql = read_sql(COURSE, "06_curated.sql") + read_sql(COURSE, "07_metric_view.sql")
    suspects = ["signed_amount_usd", "net_amount_usd", "aum_usd_total", "flow_amount"]

    for name, raw in _definitions(COURSE).items():
        blob = render_template(raw, {})
        for bogus in suspects:
            assert bogus not in blob, f"{name} references {bogus!r}, which does not exist"
        if name == "curated":
            for real in ["amount_usd", "external_sign", "is_internal",
                         "is_discretionary", "managed_value_usd", "total_advised_value_usd"]:
                if real in blob:
                    assert real in curated_sql, f"{name}: {real!r} is not a curated-view column"


def test_python_notebooks_render_as_python():
    from databricks360._notebook import PY_HEADER

    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_")
    for nb in COURSE.notebooks:
        src = build_notebook_source(COURSE, nb, catalog=None, tier="small", layout=layout)
        if nb.language == "python":
            assert src.startswith(PY_HEADER), f"{nb.name} is not a python notebook"
            compile(read_sql(COURSE, nb.sql), nb.sql, "exec")  # the source must be valid python
        else:
            assert src.startswith("-- Databricks notebook source")


def test_agents_step_is_numbered_and_last_before_validate():
    orders = [n.order for n in COURSE.notebooks]
    agents = next(n for n in COURSE.notebooks if n.name == "08_agents")
    assert agents.order == 8
    assert agents.depends_on == "07_metric_view"
    assert not agents.required, "creating agents is not needed to have a working dataset"
    assert orders == sorted(orders)


def test_every_aliased_column_reference_resolves():
    """`s.as_of_date` shipped once against a table whose column is `snapshot_date`.
    Nothing caught it, because the tests render SQL but never run it. This reads
    the column names back out of the DDL and checks every alias.column reference.

    The index over-approximates on purpose — every `AS alias` inside the CREATE
    statement counts, including CTE aliases — so it produces no false positives
    while still catching a name that appears nowhere in the statement.
    """
    import glob
    from databricks360._catalog import read_sql

    files = {nb.sql: read_sql(COURSE, nb.sql)
             for nb in COURSE.notebooks if nb.language == "sql"}
    joined = "\n".join(files.values())

    index: dict = {}
    for m in re.finditer(r"CREATE OR REPLACE (?:TABLE|VIEW) \{\{\w+\}\}(\w+)", joined):
        rest = joined[m.end():]
        nxt = re.search(r"\nCREATE OR REPLACE (?:TABLE|VIEW|FUNCTION)", rest)
        block = rest[: nxt.start()] if nxt else rest
        cols = {a.lower() for a in re.findall(r"\bAS\s+`?([a-z_][a-z_0-9]*)`?", block, re.I)}
        cols |= {c.lower() for c in re.findall(r"^\s{2}([a-z_][a-z_0-9]*)\s+[A-Z]", block, re.M)}
        cols |= {c.lower() for c in re.findall(r"^\s+([a-z_][a-z_0-9]*),\s*$", block, re.M)}
        for tup in re.findall(r"\bAS\s+\w+\s*\(([^)]+)\)", block):
            cols |= {c.strip().lower() for c in tup.split(",")
                     if re.fullmatch(r"\s*[a-z_][a-z_0-9]*\s*", c)}
        index.setdefault(m.group(1), set()).update(cols)

    bad = []
    for fname, sql in files.items():
        for m in re.finditer(r"(?:FROM|JOIN)\s+\{\{\w+\}\}(\w+)\s+(?:AS\s+)?([a-z]{1,3})\b", sql):
            table, alias = m.group(1), m.group(2)
            if not index.get(table):
                continue
            stmt = sql[m.start():]
            stmt = stmt[: stmt.index(";")] if ";" in stmt else stmt
            for col in set(re.findall(r"\b" + alias + r"\.([a-z_][a-z_0-9]*)", stmt)):
                if col.lower() not in index[table]:
                    bad.append(f"{fname}: {alias}.{col} — {table} has no such column")

    assert not bad, "unresolved column references:\n  " + "\n  ".join(sorted(set(bad)))


def test_no_sql_hardcodes_an_unprefixed_table_name():
    """A single-schema install prefixes every object, so `table_name =
    'fct_holdings_raw'` matches nothing and the check silently reports 0.
    Metadata lookups must match the suffix, and go through {{INFO_SCHEMA}}.
    """
    from databricks360._catalog import read_sql

    for nb in COURSE.notebooks:
        if nb.language != "sql":
            continue
        sql = read_sql(COURSE, nb.sql)
        assert not re.search(r"\bFROM\s+information_schema\.", sql), (
            f"{nb.sql}: use {{{{INFO_SCHEMA}}}} so the lookup follows the install's catalog"
        )
        for m in re.finditer(r"table_name\s*=\s*'([a-z_][a-z_0-9]*)'", sql):
            raise AssertionError(
                f"{nb.sql}: table_name = '{m.group(1)}' misses a prefixed layout — use LIKE '%{m.group(1)}'"
            )


# ── Labs ─────────────────────────────────────────────────────────────────────

def test_lab_specs_are_well_formed():
    """A lab spec is data, so nothing type-checks it. A malformed one fails at
    grading time, in front of a learner."""
    import json
    from importlib import resources

    folder = resources.files(COURSE.package) / "labs"
    specs = sorted(p.name for p in folder.iterdir() if p.name.endswith(".json"))
    assert specs, "the course ships no labs"

    for name in specs:
        spec = json.loads((folder / name).read_text(encoding="utf-8"))
        for key in ("title", "brief", "checks"):
            assert key in spec, f"{name}: missing {key!r}"
        if spec.get("graded"):
            assert spec["checks"], f"{name}: marked graded but carries no checks"
        else:
            assert spec.get("review"), (
                f"{name}: not graded, so it must say what a person reviews instead"
            )
        for check in spec["checks"]:
            assert "name" in check, f"{name}: a check with no name"
            if check.get("kind") == "agent":
                assert "count" in check, f"{name}: agent check {check['name']!r} needs a count path"
                assert spec.get("agent_title"), f"{name}: agent checks need agent_title"
            else:
                assert "sql" in check, f"{name}: check {check['name']!r} needs sql"
                assert isinstance(check["sql"], list), f"{name}: sql must be a list of lines"


def test_lab_sql_uses_the_placeholders_not_hardcoded_names():
    """A check that hardcodes a schema grades one workspace and no other."""
    import json
    from importlib import resources

    folder = resources.files(COURSE.package) / "labs"
    for p in folder.iterdir():
        if not p.name.endswith(".json"):
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        for check in spec["checks"]:
            sql = "\n".join(check.get("sql", []))
            assert "genie_agent" not in sql, f"{p.name}: {check['name']!r} hardcodes a schema"
            assert "workspace." not in sql, f"{p.name}: {check['name']!r} hardcodes a catalog"
            if "{{YOU_INFO}}" in sql:
                assert "{{YOU_SCHEMA}}" in sql, (
                    f"{p.name}: {check['name']!r} reads information_schema without "
                    f"filtering to the learner's schema")


def test_every_graded_lab_has_a_spec():
    """A lab marked GRADED in the course text but with no spec cannot be graded."""
    import json
    from importlib import resources

    folder = resources.files(COURSE.package) / "labs"
    have = {int(p.name[4:6]) for p in folder.iterdir() if p.name.endswith(".json")}
    for n in have:
        spec = json.loads((folder / f"lab_{n:02d}.json").read_text(encoding="utf-8"))
        if spec.get("graded"):
            assert len(spec["checks"]) >= 3, (
                f"lab {n} is graded but has {len(spec['checks'])} checks — too few to be a grade"
            )


def test_every_module_with_a_lab_has_a_spec():
    """The course runs 0 through 17. A module whose lab has no spec gives the learner
    a brief they cannot self-check and a reviewer no criteria."""
    from importlib import resources

    folder = resources.files(COURSE.package) / "labs"
    have = {int(p.name[4:6]) for p in folder.iterdir() if p.name.endswith(".json")}
    missing = sorted(set(range(0, 18)) - have)
    assert not missing, f"no lab spec for module(s): {missing}"


def test_agent_labs_name_an_agent_and_sql_labs_name_a_placeholder():
    """A lab that grades an agent must say which one; a SQL lab must address either
    the learner's schema or the reference, never a bare table name."""
    import json
    from importlib import resources

    folder = resources.files(COURSE.package) / "labs"
    for p in sorted(folder.iterdir()):
        if not p.name.endswith(".json"):
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        for check in spec["checks"]:
            if check.get("kind") == "agent":
                assert spec.get("agent_title"), f"{p.name}: agent check without agent_title"
            else:
                sql = "\n".join(check["sql"])
                assert any(t in sql for t in ("{{YOU", "{{CORE}}", "{{REF")), (
                    f"{p.name}: {check['name']!r} addresses no schema placeholder"
                )


def test_labs_that_promise_material_actually_ship_it():
    """A brief saying 'you are given twelve questions' with nothing attached is
    worse than no brief: the learner cannot start and does not know why."""
    import json
    from importlib import resources

    # "Given the access matrix", "you get nine wrong answers", "Given a Monitor
    # export" — any of these is a promise that something is attached.
    promises = re.compile(r"\bgiven\b|you are given|you're given|you get \w+ (wrong|questions)", re.I)
    folder = resources.files(COURSE.package) / "labs"
    for p in sorted(folder.iterdir()):
        if not p.name.endswith(".json"):
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        brief = " ".join(spec["brief"])
        if promises.search(brief):
            assert spec.get("inputs"), (
                f"{p.name}: the brief promises material but the spec ships none"
            )
            assert spec["inputs"].get("rows"), f"{p.name}: inputs block is empty"


def test_certification_uses_the_system_tag():
    """`certified` as a custom tag key looks right and does nothing. The documented
    effect on Genie's ranking belongs to the system-governed tag
    `system.certification_status`, whose values are certified and deprecated."""
    from databricks360._catalog import read_sql

    for nb in COURSE.notebooks:
        if nb.language != "sql":
            continue
        sql = read_sql(COURSE, nb.sql)
        for m in re.finditer(r"SET TAGS \(([^)]*)\)", sql):
            body = m.group(1)
            for key in re.findall(r"'([a-z_.]+)'\s*=", body):
                assert key not in ("certified", "deprecated"), (
                    f"{nb.sql}: '{key}' is a custom tag. Use "
                    f"'system.certification_status' = '{key}'"
                )


def test_document_corpus_is_complete_and_grounded():
    """Module 3's Agent-mode exercises need documents that disagree with the tables
    in useful ways. Forty files that all say the same thing would teach nothing."""
    import json
    from importlib import resources

    raw = (resources.files(COURSE.package) / "documents" / "documents.json").read_text("utf-8")
    docs = json.loads(raw)
    assert len(docs) == 40, f"expected 40 documents, found {len(docs)}"

    kinds = {}
    for d in docs:
        for key in ("file", "kind", "date", "title", "body"):
            assert d.get(key), f"{d.get('file')}: missing {key}"
        assert len(d["body"]) > 200, f"{d['file']}: too short to be worth reading"
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    assert len(kinds) >= 3, f"only {len(kinds)} document kinds"

    assert len({d["file"] for d in docs}) == 40, "duplicate filenames"

    # Each planted flaw should be discussed by at least one document, or the
    # Agent-mode questions have nothing to reconcile against the tables.
    corpus = " ".join(d["body"].lower() for d in docs)
    for flaw in ["held-away", "exchange", "fiscal", "discretionary", "business day",
                 "time-weighted", "settlement date", "classification"]:
        assert flaw in corpus, f"no document mentions {flaw!r}"


def test_row_filter_does_not_lock_out_the_installer():
    """The mfg_* account groups are created by an admin and may not exist. A row
    filter satisfied by nobody hides every advisor row from everybody, including
    whoever installed the lab — and then Region and State vanish from the metric
    view, so Module 7's California demo fails for a reason that is not the lesson.
    """
    from databricks360._catalog import read_sql

    sql = read_sql(COURSE, "05_governance.sql")
    m = re.search(r"CREATE OR REPLACE FUNCTION \{\{CORE\}\}region_filter.*?;", sql, re.S)
    assert m, "region_filter is gone"
    assert "{{OWNER}}" in m.group(0), (
        "region_filter has no owner clause: applying it would empty dim_advisor "
        "for everyone until the account groups exist"
    )

    # And the placeholder has to actually be substituted, or it renders literally.
    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_")
    nb = next(n for n in COURSE.notebooks if n.name == "05_governance")
    rendered = build_notebook_source(COURSE, nb, catalog=None, tier="small",
                                     layout=layout, owner="someone@example.com")
    assert "{{OWNER}}" not in rendered
    assert "someone@example.com" in rendered


def test_masks_do_not_carry_an_owner_bypass():
    """A mask returns rows, so it never bricks the lab — and an owner bypass would
    quietly hand the person doing Module 6 alone the unmasked PII it is about."""
    from databricks360._catalog import read_sql

    sql = read_sql(COURSE, "05_governance.sql")
    for m in re.finditer(r"CREATE OR REPLACE FUNCTION \{\{CORE\}\}mask_\w+.*?;", sql, re.S):
        assert "{{OWNER}}" not in m.group(0), "a column mask should not exempt the owner"


def test_the_curated_agent_attaches_the_documents_volume():
    """Module 3 teaches Agent mode reading files beside tables. Forty documents in
    a volume that no agent is attached to teaches nothing."""
    import json
    from importlib import resources
    from databricks360._documents import volume_path

    raw = (resources.files(COURSE.package) / "agents" / "curated.geniespace.json").read_text("utf-8")
    space = json.loads(raw)
    volumes = space["data_sources"].get("volumes")
    assert volumes, "the curated agent attaches no volume"
    assert volumes[0]["path"] == "{{VOLUME}}", "the volume path must be a placeholder"

    layout = resolve_layout(schema="genie_agent", table_prefix="mfg_")
    rendered = volume_path(layout)
    assert rendered.startswith("/Volumes/"), rendered
    assert rendered.endswith("documents"), rendered


def test_volume_path_is_three_segments():
    """/Volumes/<catalog>/<schema>/<volume>. Build it from a layout with no catalog
    and you get two segments, an upload that fails with "Path contains an invalid
    volume name", and no clue that the catalog was the problem."""
    from databricks360._documents import volume_path

    for kwargs in ({"catalog": "main", "schema": "genie_agent", "table_prefix": "mfg_"},
                   {"catalog": "main"},
                   {"catalog": "main", "schema": "training_you"}):
        layout = resolve_layout(**kwargs)
        path = volume_path(layout)
        parts = [p for p in path.split("/") if p]
        assert parts[0] == "Volumes", path
        assert len(parts) == 4, f"{path} has {len(parts) - 1} segments after /Volumes, need 3"


def test_both_entry_points_share_one_catalog_resolver():
    """create_agents resolved the catalog from the schema and create_documents did
    not, so the same call worked from one and failed from the other."""
    import inspect
    from databricks360 import _agents, _documents

    for mod in (_agents, _documents):
        src = inspect.getsource(mod)
        assert "resolve_catalog" in src, f"{mod.__name__} does not resolve the catalog"
        assert "for c in w.catalogs.list()" not in src, (
            f"{mod.__name__} has its own copy of the resolver"
        )


def test_cleanup_is_a_dry_run_by_default():
    """It drops schemas. A signature that deletes unless told otherwise is the
    wrong default for that."""
    import inspect
    from databricks360 import cleanup

    sig = inspect.signature(cleanup)
    assert sig.parameters["confirm"].default is False, "confirm must default to False"
    assert sig.parameters["confirm"].kind is inspect.Parameter.KEYWORD_ONLY, (
        "confirm must be keyword-only, so it cannot be passed by accident"
    )


def test_the_cleanup_notebook_does_not_confirm_for_you():
    """The notebook must show the dry run and leave the destructive call commented
    out. A learner running every cell top to bottom should not lose their lab."""
    from databricks360._catalog import read_sql

    src = read_sql(COURSE, "100_cleanup.py")
    live = [l for l in src.splitlines()
            if "confirm=True" in l and not l.strip().startswith("#")]
    assert not live, f"the cleanup notebook confirms without asking: {live}"
    assert 'academy.cleanup("genie-agents")' in src, "no dry run in the cleanup notebook"


def test_cleanup_covers_everything_the_course_installs():
    """Anything the course creates and cleanup forgets is left in the workspace."""
    import inspect
    from databricks360 import _cleanup

    src = inspect.getsource(_cleanup)
    for thing in ("genie/spaces", "DROP SCHEMA", "volume_path", "workspace.delete"):
        assert thing in src, f"cleanup never removes {thing}"


def test_agent_only_labs_do_not_require_a_schema():
    """Lab 9 grades a Genie Agent. Making the caller invent a schema for it puts a
    meaningless argument in the instructions, which teaches the wrong thing about
    what the lab is checking."""
    import inspect
    import json
    from importlib import resources
    from databricks360 import check_lab

    assert inspect.signature(check_lab).parameters["schema"].default is None

    folder = resources.files(COURSE.package) / "labs"
    for p in sorted(folder.iterdir()):
        if not p.name.endswith(".json"):
            continue
        spec = json.loads(p.read_text(encoding="utf-8"))
        if spec["checks"] and all(c.get("kind") == "agent" for c in spec["checks"]):
            assert spec.get("agent_title"), f"{p.name}: agent-only lab with no agent_title"
