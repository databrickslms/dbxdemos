"""Render a course's document set into a Unity Catalog volume.

Agent mode reads unstructured files alongside tables, so Module 3's exercises
need documents that actually disagree with the tables in interesting ways. These
forty do: every one restates a planted flaw in the words someone would use in a
meeting, so answering "summarise the memos on emerging market equity alongside
the flow trend" means reconciling prose against numbers rather than reading one
or the other.

    academy.create_documents('genie-agents')

PDFs are written if fpdf is installed, plain text otherwise; both are readable by
Agent mode, and the text fallback keeps this working with no extra dependency.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from importlib import resources

from ._catalog import get_course
from ._layout import resolve


@dataclass
class DocumentRun:
    volume: str
    written: int
    fmt: str

    def __repr__(self) -> str:
        return (f"Wrote {self.written} {self.fmt} documents to {self.volume}\n"
                f"  Attach this volume to a Genie Agent to use them in Agent mode.")


def _corpus(course) -> list:
    try:
        raw = (resources.files(course.package) / "documents" / "documents.json").read_text(
            encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError):
        raise ValueError(f"{course.id} ships no documents") from None
    return json.loads(raw)


def _render_pdf(doc: dict) -> bytes | None:
    try:
        from fpdf import FPDF
    except ImportError:
        return None
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    # An explicit width, reset to the left margin each time: fpdf2 raises rather
    # than wrapping if the cursor has drifted and width 0 leaves no room.
    width = pdf.w - pdf.l_margin - pdf.r_margin

    def block(text, size, style="", gap=0.0):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Helvetica", style, size)
        pdf.multi_cell(width, size * 0.55,
                       text.encode("latin-1", "replace").decode("latin-1"))
        if gap:
            pdf.ln(gap)

    block("Meridian Financial Group", 14, "B")
    block(f"{doc['kind']}  -  {doc['date']}", 11, "B", 2)
    block(doc["title"], 12, "B", 3)
    block(doc["body"], 11)
    out = pdf.output(dest="S")
    return out.encode("latin-1") if isinstance(out, str) else bytes(out)


def _render_text(doc: dict) -> bytes:
    return (f"Meridian Financial Group\n{doc['kind']} - {doc['date']}\n\n"
            f"{doc['title']}\n{'=' * len(doc['title'])}\n\n{doc['body']}\n").encode("utf-8")


def create_documents(
    course_id: str,
    *,
    catalog: str | None = None,
    schema: str | None = None,
    table_prefix: str | None = None,
    volume: str | None = None,
    overwrite: bool = True,
) -> DocumentRun:
    """Write the course's documents into its Unity Catalog volume."""
    from databricks.sdk import WorkspaceClient

    course = get_course(course_id)
    docs = _corpus(course)
    w = WorkspaceClient()

    schema = schema or course.default_schema
    table_prefix = table_prefix or course.default_table_prefix
    layout = resolve(catalog=catalog, schema=schema, table_prefix=table_prefix,
                     create_catalog=False, create_schema=None, create_volume=False)

    if volume is None:
        # layout.ref already carries the catalog when one was given, and ends in
        # either a table prefix ("...mfg_ref_") or a schema ("ref."). The volume
        # is named by the same rule the notebooks use when they create it.
        ref = layout.ref
        volume = ref + "documents" if ref.endswith("_") else ref + "documents"
    elif catalog and not volume.startswith(f"{catalog}."):
        volume = f"{catalog}.{volume}"
    parts = [p for p in volume.split(".") if p]
    base = "/Volumes/" + "/".join(parts)

    pdf_ok = _render_pdf(docs[0]) is not None
    fmt = "PDF" if pdf_ok else "text"
    written = 0
    for doc in docs:
        body = _render_pdf(doc) if pdf_ok else _render_text(doc)
        name = doc["file"] if pdf_ok else doc["file"].replace(".pdf", ".txt")
        w.files.upload(f"{base}/{name}", io.BytesIO(body), overwrite=overwrite)
        written += 1
    return DocumentRun(volume=base, written=written, fmt=fmt)
