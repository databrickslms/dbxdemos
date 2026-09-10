# ============================================================================
# Meridian Financial Group — 08. Genie Agents
#
# Two agents, created from definitions shipped with this package rather than
# built by hand. Create Genie Space takes the whole configuration in one call,
# so there is nothing to click.
#
#   uncurated  — all 14 base objects, a long prose instruction block
#   curated    — the 7 objects from Module 7, short instructions, example SQL
#
# Needs 04_staging, 06_curated and 07_metric_view to have been run.
# ============================================================================

import databricks360 as academy

# ----------------------------------------------------------------------------
# Check first — nothing is created
# Reports any object an agent references that does not exist yet.
# ----------------------------------------------------------------------------
academy.create_agents("genie-agents", dry_run=True)

# ============================================================================
# Create both agents
# Refuses to run if an agent of the same name already exists, rather than
# quietly making a second one. Delete the old pair from the Genie UI first, or
# pass allow_duplicates=True if you really want both.
# ============================================================================

academy.create_agents("genie-agents")

# ============================================================================
# Now ask them both the same question
#
#     What was our AUM in California at the end of last year?
#
# Write down the two answers and what you think the difference between the
# agents accounts for, before reading anything else. You will need it.
# ============================================================================
