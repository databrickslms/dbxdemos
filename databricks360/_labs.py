"""Runnable labs: a brief, a place to work, and a checker that grades it.

A lab in this course is not a quiz. The learner builds real objects in their own
schema, and the checker compares those objects against the reference behaviour by
running both and diffing the results. That means a lab can be marked GRADED and
actually be graded, rather than assessed by reading someone's notes.

    academy.lab('genie-agents', 7)                    # the brief
    academy.check_lab('genie-agents', 7, schema='lab_you')

Checks are declared as data in courses/<course>/labs/lab_NN.json, so adding a lab
is authoring a brief and a list of assertions, not writing more Python.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from importlib import resources

from ._catalog import get_course
from ._layout import resolve
from ._notebook import render_template


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    required: bool = True


@dataclass
class LabResult:
    lab: int
    title: str
    schema: str
    checks: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.required)

    @property
    def score(self) -> str:
        done = sum(1 for c in self.checks if c.passed)
        return f"{done}/{len(self.checks)}"

    def __repr__(self) -> str:
        head = [f"Lab {self.lab} — {self.title}",
                f"  your work: {self.schema}",
                f"  score:     {self.score}", ""]
        for c in self.checks:
            mark = "PASS" if c.passed else ("FAIL" if c.required else "warn")
            head.append(f"  [{mark}] {c.name}")
            if c.detail:
                head.append(f"         {c.detail}")
        head.append("")
        head.append("  All required checks passed." if self.passed
                    else "  Not passing yet — see the failures above.")
        return "\n".join(head)


def _count(space: dict, path: str) -> int:
    """Count items at a dotted path in a serialized_space, e.g.
    'instructions.sql_snippets.measures' or 'data_sources.tables'.
    A trailing '#synonyms' counts synonyms across the items at that path."""
    field = None
    if "#" in path:
        path, field = path.split("#", 1)
    node = space
    for part in path.split("."):
        node = (node or {}).get(part)
        if node is None:
            return 0
    if field:
        total = 0
        for i in node:
            if not isinstance(i, dict):
                continue
            v = i.get(field)
            total += len(v) if isinstance(v, list) else (1 if v else 0)
        return total
    if isinstance(node, dict):
        return sum(len(v) for v in node.values() if isinstance(v, list))
    return len(node or [])


def _spec(course, lab: int) -> dict:
    name = f"lab_{lab:02d}.json"
    try:
        return json.loads((resources.files(course.package) / "labs" / name)
                          .read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError(f"{course.id} has no lab {lab}") from None


def lab(course_id: str, number: int) -> None:
    """Print a lab's brief, the material it works on, and what the checker looks for.

    Several labs open with "you are given" — the twelve inbox questions, the nine
    wrong answers, the access matrix. Those live here, in the spec, so the lab can
    actually be started rather than merely described.
    """
    course = get_course(course_id)
    spec = _spec(course, number)
    print(f"Lab {number} — {spec['title']}   ({spec.get('minutes', '?')} min"
          f"{', GRADED' if spec.get('graded') else ''})")
    print()
    print("  The numbered steps for this lab are in the course module. What follows is")
    print("  a summary, the material the lab works on, and what a reviewer looks for.")
    print()
    for line in spec["brief"]:
        print(f"  {line}")
    if spec.get("inputs"):
        print()
        print("  " + "=" * 68)
        print(f"  {spec['inputs']['title']}")
        print("  " + "=" * 68)
        for row in spec["inputs"]["rows"]:
            print(f"  {row}" if row else "")
    print()
    if spec["checks"]:
        print("  The checker will verify:")
        for c in spec["checks"]:
            print(f"    - {c['name']}")
    if spec.get("review"):
        print()
        print("  Reviewed by a person, not the checker:")
        for r in spec["review"]:
            print(f"    - {r}")
    print()
    if spec["checks"]:
        print(f"  When you are ready:  academy.check_lab('{course_id}', {number}, schema='<your schema>')")
    else:
        print("  This lab has no automatic grade. The judgement is the exercise.")


def check_lab(
    course_id: str,
    number: int,
    *,
    schema: str | None = None,
    catalog: str | None = None,
    ref_catalog: str | None = None,
    ref_schema: str | None = None,
    ref_table_prefix: str | None = None,
    warehouse_id: str | None = None,
    agent: str | None = None,
) -> LabResult:
    """Grade a lab by running the learner's objects against the reference.

    `schema` is where you built your answer. The reference dataset is wherever the
    course was installed, which defaults to the course's own naming.
    """
    from databricks.sdk import WorkspaceClient
    from databricks.sdk.service.sql import StatementState

    course = get_course(course_id)
    spec = _spec(course, number)
    w = WorkspaceClient()

    ref = resolve(catalog=ref_catalog or catalog,
                  schema=ref_schema or course.default_schema,
                  table_prefix=ref_table_prefix or course.default_table_prefix,
                  create_catalog=False, create_schema=None, create_volume=False)
    needs_schema = any(c.get("kind") != "agent" for c in spec["checks"])
    if needs_schema and not schema:
        raise ValueError(
            f"lab {number} checks objects you built, so it needs schema='<your schema>'"
        )
    you = (f"{catalog}.{schema}" if catalog else schema) if schema else "(not needed)" 
    # information_schema sits at catalog level, so a metadata query cannot be
    # written as <catalog>.<schema>.information_schema — that is four name parts.
    # YOU_INFO addresses it correctly and YOU_SCHEMA filters it to the learner's work.
    values = {
        "CORE": ref.core, "REF": ref.ref, "STAGING": ref.staging,
        "YOU": f"{you}." if schema else "",
        "YOU_INFO": f"{catalog}.information_schema" if catalog else "information_schema",
        "YOU_SCHEMA": f"'{schema}'" if schema else "''",
        # Lab 0 grades the installed dataset rather than something the learner built,
        # so it needs to address the reference schema's metadata too.
        "REF_INFO": (f"{ref.catalog}.information_schema" if ref.catalog
                     else "information_schema"),
        "REF_SCHEMA": f"'{ref.single_schema or 'core'}'",
    }

    warehouse = warehouse_id or next(iter(w.warehouses.list())).id

    def run(sql: str):
        r = w.statement_execution.execute_statement(
            warehouse_id=warehouse, statement=sql, wait_timeout="50s")
        if r.status.state != StatementState.SUCCEEDED:
            msg = r.status.error.message if r.status.error else str(r.status.state)
            return None, msg.splitlines()[0][:160]
        return (r.result.data_array or []), None

    # Agent labs are graded against the agent's own configuration rather than SQL.
    agent_space = None
    if any(c.get("kind") == "agent" for c in spec["checks"]):
        want = agent or spec.get("agent_title", "")
        # A just-created space takes a few seconds to appear in the listing, and
        # "no agent found" is a poor answer to give someone who made one a moment ago.
        match = []
        for attempt in range(4):
            spaces = w.api_client.do("GET", "/api/2.0/genie/spaces").get("spaces", [])
            match = [sp for sp in spaces if want.lower() in (sp.get("title") or "").lower()]
            if match:
                break
            if attempt < 3:
                time.sleep(4)
        if match:
            newest = sorted(match, key=lambda sp: sp.get("create_time", ""))[-1]
            full = w.api_client.do(
                "GET", f"/api/2.0/genie/spaces/{newest['space_id']}",
                query={"include_serialized_space": True})
            agent_space = json.loads(full["serialized_space"])

    result = LabResult(lab=number, title=spec["title"], schema=you)
    for check in spec["checks"]:
        if check.get("kind") == "agent":
            if agent_space is None:
                result.checks.append(CheckResult(
                    check["name"], False,
                    f"no agent found whose name contains {want!r}",
                    check.get("required", True)))
                continue
            got = _count(agent_space, check["count"])
            need = check.get("at_least", 1)
            ok = got >= need
            result.checks.append(CheckResult(
                check["name"], ok,
                f"{got} found, {need} needed" if not ok else f"{got} found",
                check.get("required", True)))
            if not ok and check.get("hint"):
                result.checks[-1].detail += f" — {check['hint']}"
            continue
        sql = render_template("\n".join(check["sql"]), values)
        rows, err = run(sql)
        if err:
            # "not built yet" is the usual reason a check cannot run, and a raw
            # TABLE_OR_VIEW_NOT_FOUND tells a learner less than the hint does.
            missing = re.search(r"table or view `[^`]+`\.`[^`]+`\.`([^`]+)`", err)
            if missing:
                detail = f"{missing.group(1)} does not exist yet"
                if check.get("hint"):
                    detail += f" — {check['hint']}"
            else:
                detail = f"query failed: {err}"
            result.checks.append(CheckResult(
                check["name"], False, detail, check.get("required", True)))
            continue
        # A check passes when its query returns exactly one row whose first
        # column is true. Anything else is a failure with the row as evidence.
        ok = bool(rows) and str(rows[0][0]).lower() in ("true", "1")
        detail = "" if ok else (check.get("hint", "") or f"got {rows[0] if rows else 'no rows'}")
        if ok and len(rows[0]) > 1:
            detail = str(rows[0][1])
        result.checks.append(CheckResult(
            check["name"], ok, detail, check.get("required", True)))
    return result
