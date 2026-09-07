"""Database migrations"""

# The real migration mechanism is Database._migrate()'s ALTER TABLE list
# (metatv/core/database.py). The standalone numbered scripts that used to live
# here were never importable as modules (a leading digit is not an identifier)
# and nothing globbed or import_module'd them by path — dead since the day
# _migrate() replaced them.
#
# 001_add_detected_prefix.py and 003_add_special_content.py were deleted in
# dead-code sweep B: every column they add is in the frozen
# ORIGINAL_CHANNELS_COLUMNS set of tests/test_schema_upgrade_adds_every_column.py,
# i.e. part of the first CREATE TABLE, so no database can be missing them.
#
# 002_add_max_connections.py was NOT deleted. providers.max_connections is the
# one column of the three files that is neither original schema nor covered by
# _migrate() — see the note in that file. Adding the ALTER TABLE entry is a real
# change, out of scope for a deletion-only sweep.
