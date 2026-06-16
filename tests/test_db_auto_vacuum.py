"""Behavioral tests for the auto_vacuum=FULL database optimisation.

Three things are verified:
1. A brand-new Database is created in FULL mode (pragma set before create_all).
2. An existing NONE-mode database is migrated to FULL by _ensure_auto_vacuum, and
   pre-existing data survives the VACUUM.
3. _ensure_auto_vacuum is idempotent: calling it twice on an already-FULL database
   does not error and leaves the mode at 1.

All databases are file-backed (tmp_path) because auto_vacuum / VACUUM are
meaningless on an in-memory SQLite database.
"""

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import text

from metatv.core.database import Database


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _read_auto_vacuum(db: Database) -> int:
    """Return the current auto_vacuum pragma value (0=NONE, 1=FULL, 2=INCREMENTAL)."""
    with db.engine.connect() as conn:
        return conn.exec_driver_sql("PRAGMA auto_vacuum").scalar()


# ---------------------------------------------------------------------------
# 1. New database is born in FULL mode
# ---------------------------------------------------------------------------

def test_new_database_has_auto_vacuum_full(tmp_path):
    """A freshly created database must have auto_vacuum=1 (FULL) after create_tables."""
    db = Database(f"sqlite:///{tmp_path / 'new.db'}")
    try:
        db.create_tables()
        assert _read_auto_vacuum(db) == 1, "Expected auto_vacuum=1 (FULL) on a new database"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 2. Existing NONE database is migrated; data is preserved
# ---------------------------------------------------------------------------

def test_existing_none_database_is_migrated_to_full(tmp_path):
    """An existing NONE-mode database must be switched to FULL, and its rows preserved."""
    db_path = tmp_path / "legacy.db"

    # Create a raw SQLite database with auto_vacuum=NONE (the sqlite3 default)
    # and insert a sentinel row so we can verify data survives VACUUM.
    with sqlite3.connect(str(db_path)) as raw:
        raw.execute("PRAGMA auto_vacuum=0")   # explicit NONE
        raw.execute("CREATE TABLE sentinel (id INTEGER PRIMARY KEY, value TEXT)")
        raw.execute("INSERT INTO sentinel VALUES (1, 'hello')")
        raw.commit()
        # Confirm the file really is in NONE mode before we hand it to Database
        mode = raw.execute("PRAGMA auto_vacuum").fetchone()[0]
        assert mode == 0, f"Pre-condition failed: expected auto_vacuum=0, got {mode}"

    # Now open it with Database and run create_tables (which calls _ensure_auto_vacuum)
    db = Database(f"sqlite:///{db_path}")
    try:
        db.create_tables()

        # Mode must be FULL after migration
        assert _read_auto_vacuum(db) == 1, "Expected auto_vacuum=1 (FULL) after migration"

        # Pre-existing data must still be present
        with db.engine.connect() as conn:
            row = conn.exec_driver_sql("SELECT value FROM sentinel WHERE id=1").fetchone()
        assert row is not None, "Sentinel row disappeared after VACUUM"
        assert row[0] == "hello", f"Sentinel data corrupted: got {row[0]!r}"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3. _ensure_auto_vacuum is idempotent when already FULL
# ---------------------------------------------------------------------------

def test_ensure_auto_vacuum_is_idempotent(tmp_path):
    """Calling _ensure_auto_vacuum twice must not error and must leave mode at 1."""
    db = Database(f"sqlite:///{tmp_path / 'idempotent.db'}")
    try:
        db.create_tables()                   # first call — sets FULL (or finds it already FULL)
        assert _read_auto_vacuum(db) == 1

        db._ensure_auto_vacuum()             # second call — must be a no-op
        assert _read_auto_vacuum(db) == 1, "Mode changed after second _ensure_auto_vacuum call"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 4. (Optional) Auto-reclaim: freelist_count stays low after delete on FULL DB
# ---------------------------------------------------------------------------

def test_full_mode_reclaims_pages_after_delete(tmp_path):
    """On a FULL-mode database, deleting rows keeps freelist_count near zero.

    This demonstrates that auto_vacuum is actually working (SQLite reclaims freed
    pages on commit in FULL mode, so the freelist never accumulates).
    """
    db = Database(f"sqlite:///{tmp_path / 'reclaim.db'}")
    try:
        db.create_tables()
        assert _read_auto_vacuum(db) == 1

        # Insert enough rows to allocate several pages, then delete them all
        with db.engine.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS bulk_test (id INTEGER PRIMARY KEY, data TEXT)"
            )
            conn.exec_driver_sql(
                "INSERT INTO bulk_test (data) "
                "SELECT hex(randomblob(200)) FROM (WITH RECURSIVE n(x) AS "
                "(SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<500) SELECT x FROM n)"
            )
            conn.commit()

        with db.engine.connect() as conn:
            conn.exec_driver_sql("DELETE FROM bulk_test")
            conn.commit()

        # In FULL mode SQLite reclaims pages on each commit — freelist should be small
        with db.engine.connect() as conn:
            freelist = conn.exec_driver_sql("PRAGMA freelist_count").scalar()

        # FULL mode guarantees prompt page reclaim; freelist_count == 0 is typical.
        # We allow a small margin (< 10) in case the engine holds a page or two in reserve.
        assert freelist < 10, (
            f"Expected near-zero freelist_count in FULL auto_vacuum mode, got {freelist}"
        )
    finally:
        db.close()
