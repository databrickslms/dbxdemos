"""Resolve where the lab objects live, given what the workspace permits.

A locked-down Unity Catalog is normal in regulated environments, so the default
assumes the least privilege that can still work: use whatever catalog the session
is already pointed at, and create schemas inside it. Creating a catalog is opt-in.

Four shapes:

  1. Default            current_catalog(), schemas core / ref / staging
  2. Named catalog      an explicit catalog you were granted
  3. Create a catalog   opt in with create_catalog=True
  4. One schema only    everything in a single schema you already own

Layout 4 needs no renaming: core holds the dimensions and facts, ref holds only
the documents volume, staging holds only the two decoy tables, so the three sets
of object names do not overlap and collapsing them is safe.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    """`catalog is None` means "whatever current_catalog() returns at run time",
    which is expressed as unqualified two-level names so SQL resolves it itself."""

    catalog: str | None
    core: str
    ref: str
    staging: str
    schemas: tuple[str, ...]
    create_catalog: bool
    create_schema: bool
    create_volume: bool
    single_schema: str | None

    @property
    def is_single_schema(self) -> bool:
        return self.single_schema is not None

    @property
    def uses_current_catalog(self) -> bool:
        return self.catalog is None

    def describe(self) -> str:
        where = self.catalog or "current_catalog()"
        if self.is_single_schema:
            return f"single schema: {where}.{self.single_schema}"
        return f"catalog: {where}    schemas: {', '.join(self.schemas)}"


def _qualify(catalog: str | None, schema: str) -> str:
    """Two-level when no catalog is named, so SQL resolves it against the session."""
    return schema if catalog is None else f"{catalog}.{schema}"


def resolve(
    *,
    catalog: str | None = None,
    schema: str | None = None,
    create_catalog: bool = False,
    create_schema: bool | None = None,
    create_volume: bool = True,
) -> Layout:
    """Work out the object layout.

    `catalog=None` (the default) targets the session's current catalog and creates
    nothing above schema level — the safest assumption in a governed workspace.

    Passing `schema` selects the single-schema layout and assumes you cannot create
    that schema either, since that is the reason to reach for it.
    """
    if catalog is not None and (not catalog or "." in catalog):
        raise ValueError(f"catalog must be a bare name, got {catalog!r}")
    if schema is not None and (not schema or "." in schema):
        raise ValueError(f"schema must be a bare name, got {schema!r}")
    if create_catalog and catalog is None:
        raise ValueError(
            "create_catalog=True needs an explicit catalog name — "
            "current_catalog() already exists by definition."
        )

    if schema is None:
        return Layout(
            catalog=catalog,
            core=_qualify(catalog, "core"),
            ref=_qualify(catalog, "ref"),
            staging=_qualify(catalog, "staging"),
            schemas=("core", "ref", "staging"),
            create_catalog=create_catalog,
            create_schema=True if create_schema is None else create_schema,
            create_volume=create_volume,
            single_schema=None,
        )

    target = _qualify(catalog, schema)
    return Layout(
        catalog=catalog,
        core=target,
        ref=target,
        staging=target,
        schemas=(schema,),
        create_catalog=create_catalog,
        create_schema=False if create_schema is None else create_schema,
        create_volume=create_volume,
        single_schema=schema,
    )


def setup_ddl(layout: Layout) -> str:
    """The CREATE statements for notebook 01, matched to the layout."""
    cells: list[str] = []

    # Always show where things are about to land. In a governed workspace this is
    # the single most useful line in the notebook.
    cells.append(
        "-- Where this lab is about to be created. Check it before running 02.\n"
        "SELECT current_catalog() AS default_catalog, current_schema() AS default_schema;"
    )

    if layout.create_catalog:
        cells.append(
            f"CREATE CATALOG IF NOT EXISTS {layout.catalog}\n"
            "  COMMENT 'Meridian Financial Group — synthetic dataset for training. "
            "Not production data.';\n"
            f"USE CATALOG {layout.catalog};"
        )
    elif layout.catalog:
        cells.append(
            f"-- Using the existing catalog `{layout.catalog}`. No CREATE CATALOG attempted;\n"
            f"-- pass create_catalog=True only if you hold that privilege.\n"
            f"USE CATALOG {layout.catalog};"
        )
    else:
        cells.append(
            "-- Using the session's current catalog, shown above. Nothing is created at\n"
            "-- catalog level, which is what a governed workspace normally allows.\n"
            "-- Pass catalog='name' to target a different one."
        )

    if layout.create_schema:
        if layout.is_single_schema:
            cells.append(
                f"CREATE SCHEMA IF NOT EXISTS {layout.core}\n"
                "  COMMENT 'Meridian Financial Group teaching dataset.';"
            )
        else:
            cells.append(
                "-- Curated business data. Everything a Genie Agent is pointed at lives here.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.core}\n"
                "  COMMENT 'Core banking facts and dimensions for Meridian Financial Group.';"
            )
            cells.append(
                "-- Unstructured documents for Agent mode and Knowledge Assistant.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.ref}\n"
                "  COMMENT 'Reference and unstructured material: credit committee memos, "
                "branch notes, complaint letters.';"
            )
            cells.append(
                "-- Raw and superseded objects, kept apart from curated data.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.staging}\n"
                "  COMMENT 'Staging: raw and superseded objects. Not intended for reporting.';"
            )
    else:
        listed = ", ".join(f"`{s}`" for s in layout.schemas)
        cells.append(
            f"-- Skipping CREATE SCHEMA: expecting {listed} to exist already.\n"
            "-- Pass create_schema=True if you can create it."
        )

    if layout.create_volume:
        cells.append(
            "-- Only needed for Agent mode over files (Modules 3 and 16). If you lack\n"
            "-- CREATE VOLUME, pass create_volume=False and skip those exercises.\n"
            f"CREATE VOLUME IF NOT EXISTS {layout.ref}.documents\n"
            "  COMMENT 'PDFs attached to the agent for Agent mode: credit committee memos, "
            "branch manager notes, customer complaint letters.';"
        )
    else:
        cells.append(
            "-- Skipping CREATE VOLUME (create_volume=False). Modules 3 and 16 use it for\n"
            "-- Agent mode over unstructured files; everything else is unaffected."
        )

    return "\n\n-- COMMAND ----------\n\n".join(cells)


def schema_list_sql(layout: Layout) -> str:
    return ", ".join(f"'{s}'" for s in layout.schemas)
