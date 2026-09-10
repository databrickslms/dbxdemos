"""Render a course's document set into a Unity Catalog volume.

Agent mode reads unstructured files alongside tables, so Module 3's exercises
need documents that actually disagree with the tables in interesting ways. These
forty do: every one restates a planted flaw in the words someone would use in a
meeting, so answering "summarise the memos on emerging market equity alongside
the flow trend" means reconciling prose against numbers rather than reading one
or the other.

    academy.create_documents('genie-agents')

Documents are written as PDFs, which needs `fpdf2`. That is not optional in any
useful sense: Agent mode reads PDF, JPG, PNG, TIFF, DOC, DOCX, PPT and PPTX, and
nothing else. A plain-text fallback would put forty files in the volume that the
feature ignores without saying so, which is worse than stopping.

Attaching the volume is not enough to read it. A workspace admin must turn on the
preview **Analyze Files in Volumes with Genie Agents** from the Previews page;
until then the attachment is accepted, the files sit in the volume, and the agent
replies that it has no document-search tool. File analysis also runs in Agent
mode only, and without content search the agent retrieves from at most five files
per question — worth remembering against forty documents.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from importlib import resources

from ._catalog import get_course
from ._layout import resolve, resolve_catalog


@dataclass
class DocumentRun:
    volume: str
    written: int
    fmt: str

    def __repr__(self) -> str:
        return (f"Wrote {self.written} {self.fmt} documents to {self.volume}\n"
                f"  Attach this volume to a Genie Agent to use them in Agent mode.")


def volume_path(layout) -> str:
    """The /Volumes path for a course's documents volume, under a given layout.

    layout.ref already carries the catalog when one was given, and ends in either
    a table prefix ("...mfg_ref_") or a schema ("ref."). Either way the volume is
    named by the same rule the notebooks use when they create it.
    """
    return "/Volumes/" + "/".join(p for p in (layout.ref + "documents").split(".") if p)


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
    # A /Volumes path is three segments: catalog, schema, volume. Without a
    # catalog the layout yields two, and the upload fails with "Path contains an
    # invalid volume name" — which is how notebook 08 failed the first time it
    # was ever run as a notebook rather than called with an explicit catalog.
    if catalog is None:
        catalog = resolve_catalog(w, schema)
    layout = resolve(catalog=catalog, schema=schema, table_prefix=table_prefix,
                     create_catalog=False, create_schema=None, create_volume=False)

    if volume is None:
        base = volume_path(layout)
    else:
        if catalog and not volume.startswith(f"{catalog}."):
            volume = f"{catalog}.{volume}"
        base = "/Volumes/" + "/".join(p for p in volume.split(".") if p)

    if _render_pdf(docs[0]) is None:
        raise ImportError(
            "fpdf2 is needed to write the documents as PDFs.\n"
            "    %pip install fpdf2\n"
            "Agent mode reads PDF, JPG, PNG, TIFF, DOC, DOCX, PPT and PPTX, and nothing "
            "else. Writing plain text instead would put forty files in the volume that "
            "the agent silently ignores, so this stops rather than doing that."
        )
    written = 0
    for doc in docs:
        w.files.upload(f"{base}/{doc['file']}", io.BytesIO(_render_pdf(doc)),
                       overwrite=overwrite)
        written += 1
    return DocumentRun(volume=base, written=written, fmt="PDF")
