"""Quitting must not wait thirty seconds for an optional statistics refresh.

The owner's log, 2026-09-01, twice in one evening::

    21:08:02.203  Player manager cleanup complete
    21:08:32.231  ERROR  Database: PRAGMA optimize failed on close
                  sqlite3.OperationalError: database is locked

Exactly 30.0 s — the connection default ``busy_timeout``, inherited by the
close path from the pragma listener. The second time they killed the app with
Ctrl+C rather than wait.

``PRAGMA optimize`` is an optimisation: it re-ANALYZEs what has drifted so the
next launch plans queries well. Skipping it costs a slightly stale plan, which
is invisible. Waiting for it costs half a minute staring at a window that will
not close.
"""
from __future__ import annotations

import sqlite3
import time

from metatv.core.database import _CLOSE_BUSY_TIMEOUT_MS, Database


def test_close_gives_up_quickly_when_a_writer_still_holds_the_lock(tmp_path):
    """The regression, measured rather than asserted about.

    A second connection holds an EXCLUSIVE write transaction — the shape a
    background writer draining at shutdown produces. ``close()`` must return in
    about its own short timeout, not the connection default.
    """
    path = tmp_path / "locked.db"
    db = Database(f"sqlite:///{path}")
    db.create_tables()

    holder = sqlite3.connect(path, timeout=30)
    holder.execute("PRAGMA journal_mode=WAL")
    holder.execute("BEGIN EXCLUSIVE")
    holder.execute("CREATE TABLE IF NOT EXISTS _lock_probe (x INTEGER)")
    try:
        started = time.monotonic()
        db.close()
        elapsed = time.monotonic() - started
    finally:
        holder.rollback()
        holder.close()

    budget = (_CLOSE_BUSY_TIMEOUT_MS / 1000.0) + 4.0
    assert elapsed < budget, (
        f"close() took {elapsed:.1f}s with the write lock held. It is waiting "
        f"out the connection's 30s busy_timeout for a statistics refresh that "
        f"is pure optimisation — that is the half-minute hang on quit.")


def test_the_close_timeout_is_far_below_the_connection_default(tmp_path):
    """Pins the RELATIONSHIP, not the literal.

    The number may be tuned; what must never come back is close() inheriting
    the 30 s default, which is the whole defect.
    """
    assert _CLOSE_BUSY_TIMEOUT_MS <= 5000, (
        f"the close-path busy timeout is {_CLOSE_BUSY_TIMEOUT_MS} ms; anything "
        "near the 30000 ms connection default reintroduces the hang")


def test_close_still_runs_the_optimize_when_nothing_holds_the_lock(tmp_path):
    """The feature is not simply deleted — an unlocked close still refreshes.

    Without this, setting the timeout to 0 would pass the test above while
    silently removing the statistics refresh entirely.
    """
    statements: list[str] = []
    path = tmp_path / "free.db"
    db = Database(f"sqlite:///{path}")
    db.create_tables()

    real = Database.close
    from sqlalchemy import event

    engine = db.engine

    @event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    real(db)
    assert any("optimize" in s.lower() for s in statements), (
        "close() no longer refreshes query statistics at all")
