-- ============================================================================
-- Meridian Financial Group — 01. Catalog, schemas, volume
--
-- Run first. Idempotent.
--
-- The DDL below is generated to match what your workspace actually permits.
-- By default nothing is created above schema level: the lab lands in whatever
-- current_catalog() returns, which is what a governed workspace normally allows.
--
--   default              current_catalog(), schemas core / ref / staging
--   catalog='main'       an explicit catalog you were granted
--   create_catalog=True  opt in, if you hold that privilege
--   schema='mine'        everything in one schema you already own
--
-- The single-schema case renames nothing: the three schemas hold non-overlapping
-- object names, so collapsing them is safe. Notebooks 02 onward resolve their own
-- paths and need no changes whichever layout you used.
--
-- See the "Regulated environments" section of the package README.
-- ============================================================================

{{SETUP_DDL}}

-- ----------------------------------------------------------------------------
-- Verify — the schemas below must all exist before you run 02
-- ----------------------------------------------------------------------------
-- Unqualified information_schema resolves against the current catalog, so this
-- works whether or not a catalog was named.
SELECT current_catalog() AS catalog_name, schema_name
FROM {{INFO_SCHEMA}}.schemata
WHERE schema_name IN ({{SCHEMA_LIST}})
ORDER BY schema_name;
