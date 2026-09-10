# ============================================================================
# Meridian Financial Group — 100. Clean up
#
# Removes everything this course installed: the schema and every object in it,
# the documents volume, the two Genie Agents, and these notebooks.
#
# THIS DROPS A SCHEMA. Read the dry run before you confirm it.
#
# It removes only what the course created. Agents are matched by the titles the
# package gives them, so one you renamed or built yourself is reported and left
# alone. Same for anything else that ended up in the lab schema.
# ============================================================================

import databricks360 as academy

# ----------------------------------------------------------------------------
# What would go — nothing is deleted by this cell
# ----------------------------------------------------------------------------
academy.cleanup("genie-agents")

# ============================================================================
# Do it
# Uncomment and run once you have read the list above and agree with it.
# ============================================================================

# academy.cleanup("genie-agents", confirm=True)

# ============================================================================
# If you installed somewhere other than the default
#
# Pass the same arguments you installed with, or nothing is found:
#
#   academy.cleanup("genie-agents", catalog="training", confirm=True)
#   academy.cleanup("genie-agents", schema="large_tier", confirm=True)
#   academy.cleanup("genie-agents", title_suffix="(large tier)", confirm=True)
#
# keep_notebooks=True leaves this folder in place, which is useful if you want
# to reinstall later without downloading again.
# ============================================================================
