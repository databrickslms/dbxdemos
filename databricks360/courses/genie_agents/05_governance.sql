-- ============================================================================
-- Meridian Financial Group — 05. Governance
--
-- Row-level and column-level access control, enforced by Unity Catalog.
--
-- REQUIRES: privilege to create functions in this schema, and to ALTER the
-- tables. If you cannot, skip this notebook — everything else still works, and
-- the course notes where the exercises depend on it.
--
-- GROUPS: the row filter checks account-level group membership. An admin
-- creates these once, in the account console or via SCIM:
--
--     mfg_region_ne     mfg_region_se     mfg_region_mw     mfg_region_west
--     mfg_unrestricted  mfg_finance
--
-- Nobody in a group behaves as unrestricted, so an unassigned user sees no rows.
-- That is the correct default: fail closed.
-- ============================================================================


-- ============================================================================
-- Row filter — branch region
-- A regional manager sees their own region. mfg_unrestricted sees everything.
-- ============================================================================
CREATE OR REPLACE FUNCTION {{CORE}}region_filter(region STRING)
RETURN
  is_account_group_member('mfg_unrestricted')
  OR (region = 'NE'   AND is_account_group_member('mfg_region_ne'))
  OR (region = 'SE'   AND is_account_group_member('mfg_region_se'))
  OR (region = 'MW'   AND is_account_group_member('mfg_region_mw'))
  OR (region = 'WEST' AND is_account_group_member('mfg_region_west'));

ALTER TABLE {{CORE}}dim_branch
  SET ROW FILTER {{CORE}}region_filter ON (region);


-- ============================================================================
-- Column masks — customer identifiers
-- Masked for everyone except mfg_unrestricted. Income is narrower still:
-- finance only.
-- ============================================================================
CREATE OR REPLACE FUNCTION {{CORE}}mask_identifier(v STRING)
RETURN CASE WHEN is_account_group_member('mfg_unrestricted') THEN v ELSE '****' END;

CREATE OR REPLACE FUNCTION {{CORE}}mask_email(v STRING)
RETURN CASE
  WHEN is_account_group_member('mfg_unrestricted') THEN v
  -- Keep the domain: useful for segmentation, harmless on its own.
  ELSE concat('***@', split(v, '@')[1])
END;

CREATE OR REPLACE FUNCTION {{CORE}}mask_dob(v DATE)
RETURN CASE
  WHEN is_account_group_member('mfg_unrestricted') THEN v
  -- Truncating to the year keeps age analysis possible without a birth date.
  ELSE date_trunc('YEAR', v)
END;

CREATE OR REPLACE FUNCTION {{CORE}}mask_income(v DECIMAL(12,2))
RETURN CASE
  WHEN is_account_group_member('mfg_finance')
    OR is_account_group_member('mfg_unrestricted') THEN v
  ELSE NULL
END;

ALTER TABLE {{CORE}}dim_customer ALTER COLUMN ssn_last4
  SET MASK {{CORE}}mask_identifier;
ALTER TABLE {{CORE}}dim_customer ALTER COLUMN email
  SET MASK {{CORE}}mask_email;
ALTER TABLE {{CORE}}dim_customer ALTER COLUMN dob
  SET MASK {{CORE}}mask_dob;
ALTER TABLE {{CORE}}dim_customer ALTER COLUMN annual_income
  SET MASK {{CORE}}mask_income;


-- ============================================================================
-- Certification and deprecation
-- Two revenue tables exist. Tag which one is authoritative so nobody has to ask.
-- ============================================================================
ALTER TABLE {{CORE}}fct_transactions
  SET TAGS ('certified' = 'true', 'owner' = 'cards_analytics');

-- The staging objects are tagged in notebook 04, where they are created, so
-- this notebook does not depend on 04 having been run.


-- ----------------------------------------------------------------------------
-- Verify — what is protected, and what you can see
-- ----------------------------------------------------------------------------
SELECT current_user() AS whoami,
       is_account_group_member('mfg_unrestricted') AS unrestricted,
       is_account_group_member('mfg_region_ne')    AS region_ne,
       is_account_group_member('mfg_region_west')  AS region_west,
       is_account_group_member('mfg_finance')      AS finance;

-- Row count under your own filter. Unassigned users correctly see zero.
SELECT count(*) AS branches_visible FROM {{CORE}}dim_branch;

-- What the masks do for you specifically.
SELECT customer_id, segment, ssn_last4, email, dob, annual_income
FROM {{CORE}}dim_customer
LIMIT 5;
