-- ============================================================================
-- Meridian Financial Group — 01. Catalog, schemas, volume
--
-- Run first. Idempotent.
--
-- The DDL below is generated to match what your workspace actually permits.
-- Three layouts are supported, because a locked-down Unity Catalog is the norm
-- in regulated environments, not the exception:
--
--   1. Full control        creates a catalog and core / ref / staging schemas
--   2. No CREATE CATALOG   creates the three schemas inside a catalog you have
--   3. One schema only     puts everything in a single schema you already own
--
-- In layout 3 nothing is renamed: the three schemas hold non-overlapping object
-- names, so collapsing them is safe. Every later notebook resolves its own
-- paths, so 02 and 03 need no changes whichever layout you used.
--
-- See the "Regulated environments" section of the package README.
-- ============================================================================

{{SETUP_DDL}}

-- ----------------------------------------------------------------------------
-- Verify — the schemas below must all exist before you run 02
-- ----------------------------------------------------------------------------
SELECT catalog_name, schema_name
FROM {{CATALOG}}.information_schema.schemata
WHERE schema_name IN ({{SCHEMA_LIST}})
ORDER BY schema_name;
