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
# 3b. New connections don't crash on pragma setup under a concurrent write lock
# ---------------------------------------------------------------------------

def test_new_connection_survives_concurrent_write_lock(tmp_path):
    """Opening a fresh connection (which runs _set_pragmas) must NOT raise
    'database is locked' while another connection holds an open write transaction.

    Regression: _set_pragmas ran ``PRAGMA auto_vacuum=FULL`` on EVERY connection,
    which acquires a write lock even when the mode is already FULL. During a
    concurrent off-thread provider delete this raised OperationalError (bypassing
    busy_timeout) and crashed the app (SIGABRT). The fix skips the write when
    auto_vacuum is already FULL, so a fresh connection opens cleanly under the lock.
    """
    db_path = tmp_path / "concurrent.db"
    db = Database(f"sqlite:///{db_path}")
    try:
        db.create_tables()
        assert _read_auto_vacuum(db) == 1

        # Another connection holds an OPEN write transaction — the "off-thread delete".
        holder = sqlite3.connect(str(db_path), timeout=1)
        holder.execute("PRAGMA busy_timeout=500")
        holder.execute("BEGIN IMMEDIATE")
        holder.execute("CREATE TABLE _probe (x INTEGER)")  # take + dirty the write lock
        try:
            db.engine.dispose()  # force a brand-new dbapi connection → listener re-fires
            with db.engine.connect() as conn:
                # Opens cleanly: reads the WAL-committed header (mode 1) and skips the
                # auto_vacuum write instead of blocking/raising on the held lock.
                assert conn.exec_driver_sql("PRAGMA auto_vacuum").scalar() == 1
        finally:
            holder.rollback()
            holder.close()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 3c. Engine-wide busy_timeout + journal_mode — lock-resilience layer 1
# ---------------------------------------------------------------------------

def test_fresh_connection_has_30s_busy_timeout(tmp_path):
    """Every connection off Database.engine gets PRAGMA busy_timeout=30000 (30s)
    via the same connect-event listener that sets auto_vacuum, applied BEFORE
    any table exists.

    This is the app-wide lock-resilience layer: a writer contending for the
    SQLite write lock (the startup EPG-refresh / Migration Center write storm
    that produced the 2026-07-31 and 2026-08-01 'database is locked'
    crash-loops) retries silently inside SQLite for up to 30s before an
    OperationalError ever reaches Python, instead of raising on the very
    first collision. (Already present since 2e7ef5b4 — this pins the
    contract so a future refactor of _set_pragmas can't silently drop it.)
    """
    db = Database(f"sqlite:///{tmp_path / 'busy_timeout.db'}")
    try:
        with db.engine.connect() as conn:
            value = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        assert value == 30000, f"expected busy_timeout=30000ms, got {value}"

        # A brand-new dbapi connection (post dispose) must get it too — the
        # pragma is per-connection state, re-applied by the connect listener,
        # not something that only happens to survive on the first connection.
        db.engine.dispose()
        with db.engine.connect() as conn:
            value = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
        assert value == 30000, f"expected busy_timeout=30000ms on a fresh connection, got {value}"
    finally:
        db.close()


def test_fresh_connection_uses_wal_journal_mode(tmp_path):
    """WAL journal mode is already enabled on every connection (concurrent
    readers don't block a writer, and vice versa) — part of the same
    lock-resilience layer as busy_timeout. Regression guard only; not new
    behavior."""
    db = Database(f"sqlite:///{tmp_path / 'wal.db'}")
    try:
        with db.engine.connect() as conn:
            mode = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
        assert mode.lower() == "wal", f"expected journal_mode=WAL, got {mode!r}"
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
