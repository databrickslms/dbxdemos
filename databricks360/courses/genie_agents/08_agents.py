# ============================================================================
# Meridian Financial Group — 08. Genie Agents
#
# Two agents, created from definitions shipped with this package rather than
# built by hand. Create Genie Space takes the whole configuration in one call,
# so there is nothing to click.
#
#   uncurated  — all 14 base objects, a long prose instruction block
#   curated    — the 7 objects from Module 7, short instructions, example SQL,
#                and the documents volume attached for Agent mode
#
# Needs 04_staging, 06_curated and 07_metric_view to have been run.
# ============================================================================

import databricks360 as academy

# ============================================================================
# The documents first
# Forty Meridian files - committee memos, advisor call notes, complaint
# resolutions - written into the course volume. The curated agent attaches that
# volume, so Agent mode can read them alongside the tables. Module 3 needs this.
# ============================================================================

academy.create_documents("genie-agents")

# ----------------------------------------------------------------------------
# Check the agents before creating them — nothing is created here
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
