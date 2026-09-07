"""Database migrations"""

# The real migration mechanism is Database._migrate()'s ALTER TABLE list
# (metatv/core/database.py). The standalone numbered scripts that used to live
# here were never importable as modules (a leading digit is not an identifier)
# and nothing globbed or import_module'd them by path — dead since the day
# _migrate() replaced them.
#
# 001_add_detected_prefix.py and 003_add_special_content.py went in dead-code
# sweep B; 002_add_max_connections.py was kept back because its column was the
# one thing in those three files that _migrate() genuinely did not cover, and
# adding an ALTER TABLE entry is a real change rather than a deletion.
#
# That entry now exists (SCHEMA-1), so 002 is gone too. It was not alone:
# widening tests/test_schema_upgrade_adds_every_column.py from "channels" to
# EVERY table found eleven more columns in the same state, and _migrate()
# carries all twelve.
