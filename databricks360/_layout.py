"""Resolve where the lab objects live, given what the workspace permits.

A locked-down Unity Catalog is normal in regulated environments, so the lab has
to fit three shapes rather than assume it owns a metastore:

  1. Full control       — create a catalog, and core / ref / staging inside it
  2. No CREATE CATALOG  — create the three schemas in a catalog you were given
  3. One schema only    — everything in a single schema you already own

Layout 3 needs no renaming: core holds the dims and facts, ref holds only the
documents volume, staging holds only the two decoy tables, so the three sets of
object names do not overlap and collapsing them is safe.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Layout:
    catalog: str
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

    def describe(self) -> str:
        if self.is_single_schema:
            return f"single schema: {self.core}"
        return f"schemas: {', '.join(f'{self.catalog}.{s}' for s in self.schemas)}"


def resolve(
    *,
    catalog: str,
    schema: str | None = None,
    create_catalog: bool | None = None,
    create_schema: bool | None = None,
    create_volume: bool = True,
) -> Layout:
    """Work out the object layout.

    Passing `schema` selects the single-schema layout and, unless told otherwise,
    assumes you cannot create the catalog or the schema — that is the whole reason
    someone reaches for it.
    """
    if not catalog or "." in catalog:
        raise ValueError(f"catalog must be a bare name, got {catalog!r}")
    if schema is not None and (not schema or "." in schema):
        raise ValueError(f"schema must be a bare name, got {schema!r}")

    if schema is None:
        return Layout(
            catalog=catalog,
            core=f"{catalog}.core",
            ref=f"{catalog}.ref",
            staging=f"{catalog}.staging",
            schemas=("core", "ref", "staging"),
            create_catalog=True if create_catalog is None else create_catalog,
            create_schema=True if create_schema is None else create_schema,
            create_volume=create_volume,
            single_schema=None,
        )

    target = f"{catalog}.{schema}"
    return Layout(
        catalog=catalog,
        core=target,
        ref=target,
        staging=target,
        schemas=(schema,),
        create_catalog=False if create_catalog is None else create_catalog,
        create_schema=False if create_schema is None else create_schema,
        create_volume=create_volume,
        single_schema=schema,
    )


def setup_ddl(layout: Layout) -> str:
    """The CREATE statements for notebook 01, matched to the layout."""
    out: list[str] = []

    if layout.create_catalog:
        out.append(
            f"CREATE CATALOG IF NOT EXISTS {layout.catalog}\n"
            "  COMMENT 'Meridian Financial Group — synthetic teaching dataset for the "
            "Genie Agents course. Contains deliberate data-quality flaws; not a reference "
            "implementation.';"
        )
    else:
        out.append(
            f"-- Skipping CREATE CATALOG: using the existing catalog `{layout.catalog}`.\n"
            f"-- Pass create_catalog=True if you do have the privilege and want it created."
        )

    if layout.create_schema:
        if layout.is_single_schema:
            out.append(
                f"CREATE SCHEMA IF NOT EXISTS {layout.core}\n"
                "  COMMENT 'Meridian Financial Group teaching dataset — facts, dimensions "
                "and the deliberately unfit staging objects, all in one schema.';"
            )
        else:
            out.append(
                f"-- Curated business data. Everything a Genie Agent is pointed at lives here.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.core}\n"
                "  COMMENT 'Core banking facts and dimensions for Meridian Financial Group.';"
            )
            out.append(
                f"-- Unstructured documents for Agent mode and Knowledge Assistant.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.ref}\n"
                "  COMMENT 'Reference and unstructured material: credit committee memos, "
                "branch notes, complaint letters.';"
            )
            out.append(
                f"-- The deliberately awful objects used in Modules 7 and 13, kept apart so\n"
                f"-- the \"before\" and \"after\" states stay visibly distinct.\n"
                f"CREATE SCHEMA IF NOT EXISTS {layout.staging}\n"
                "  COMMENT 'Deliberately unfit-for-purpose objects used to teach scoping and "
                "latency. Never point a production agent here.';"
            )
    else:
        listed = ", ".join(f"`{layout.catalog}.{s}`" for s in layout.schemas)
        out.append(
            f"-- Skipping CREATE SCHEMA: expecting {listed} to exist already.\n"
            f"-- Pass create_schema=True if you can create it."
        )

    if layout.create_volume:
        out.append(
            f"-- Only needed for Agent mode over files (Modules 3 and 16). If you lack\n"
            f"-- CREATE VOLUME, pass create_volume=False and skip those exercises.\n"
            f"CREATE VOLUME IF NOT EXISTS {layout.ref}.documents\n"
            "  COMMENT 'PDFs attached to the agent for Agent mode: credit committee memos, "
            "branch manager notes, customer complaint letters.';"
        )
    else:
        out.append(
            "-- Skipping CREATE VOLUME (create_volume=False). Modules 3 and 16 use it for\n"
            "-- Agent mode over unstructured files; everything else is unaffected."
        )

    return "\n\n-- COMMAND ----------\n\n".join(out)


def schema_list_sql(layout: Layout) -> str:
    """A SQL IN-list of the schema names, for the verify query."""
    return ", ".join(f"'{s}'" for s in layout.schemas)
