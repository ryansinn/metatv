"""A commit that blocks the UI thread is recorded, so the risk stops being a guess.

Under WAL a reader never blocks, which is what makes the app feel fast. Writers
still serialise against each other, and user-state mutations — favourite, hide,
not-interested, rating — commit synchronously in Qt slots. A bulk pass holding
the write lock therefore stalls a click handler for as long as its batch takes,
and `busy_timeout=30000` is the point it would give up rather than the wait a
user should expect.

Nothing here prevents that, on purpose. The two available fixes each cost
something real: routing every user-state mutation through the async seam is a
wide refactor, and giving the main thread a short busy_timeout turns a slow
favourite toggle into a FAILED one, which is worse than a slow one. Neither is
worth buying before the frequency is known — and it is not known. Batches are
sized (2,000 rows), so the typical wait *should* be far below the threshold.
This turns that "should" into evidence.
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import patch

import pytest
from loguru import logger

import metatv.core.database as db_mod
from metatv.core.database import (
    SLOW_MAIN_THREAD_COMMIT_MS,
    ChannelDB,
    Database,
)


@pytest.fixture()
def logged():
    """Capture loguru output — the app logs through loguru, not stdlib."""
    seen: list[str] = []
    sink = logger.add(lambda m: seen.append(m.record["message"]), level="WARNING")
    yield seen
    logger.remove(sink)


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'wait.db'}")
    d.create_tables()
    yield d
    d.close()


def _row(n: str) -> ChannelDB:
    return ChannelDB(id=n, source_id=n, provider_id="p", name=n, media_type="movie")


def _commit_taking(ms: float, database, name: str, in_thread: bool = False):
    """Run one committing scope whose commit appears to take *ms*."""
    def run():
        ticks = iter([0.0, ms / 1000.0])
        with patch.object(db_mod.time, "perf_counter",
                          lambda: next(ticks, ms / 1000.0)):
            with database.session_scope() as s:
                s.add(_row(name))
    if in_thread:
        t = threading.Thread(target=run)
        t.start()
        t.join()
    else:
        run()


def test_a_slow_main_thread_commit_is_logged(db, logged):
    _commit_taking(SLOW_MAIN_THREAD_COMMIT_MS + 400, db, "slow")
    assert any("UI thread blocked" in m for m in logged), (
        "a commit that stalled the UI thread left no trace, so the risk stays "
        "unmeasurable"
    )


def test_a_fast_main_thread_commit_is_silent(db, logged):
    """Below the threshold the wait is invisible; logging it is only noise."""
    _commit_taking(1.0, db, "fast")
    assert not any("UI thread blocked" in m for m in logged)


def test_a_slow_worker_commit_is_silent(db, logged):
    """Workers are allowed to wait — that is what the 30s timeout is for.

    The finding is specifically about the UI thread. Logging every slow bulk
    commit would bury the one line that matters under the migration's own noise.
    """
    _commit_taking(SLOW_MAIN_THREAD_COMMIT_MS + 400, db, "worker", in_thread=True)
    assert not any("UI thread blocked" in m for m in logged)


def test_the_threshold_is_a_perceptible_delay():
    """100ms is the point a click stops feeling instant."""
    assert 50 <= SLOW_MAIN_THREAD_COMMIT_MS <= 250


def test_read_only_scopes_are_not_timed(db, logged):
    """commit=False never commits, so there is no wait to attribute."""
    ticks = iter([0.0, 5.0])
    with patch.object(db_mod.time, "perf_counter", lambda: next(ticks, 5.0)):
        with db.session_scope(commit=False) as s:
            s.query(ChannelDB).all()
    assert not any("UI thread blocked" in m for m in logged)
