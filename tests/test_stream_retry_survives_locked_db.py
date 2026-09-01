"""Recording a stream failure must never take the application with it.

This crashed the owner's app on 2026-08-31. A play preflight failed, so
`_on_stream_ready` called `add_failure()`, which committed on the MAIN thread
while a background writer held SQLite's single write lock. The
`OperationalError` was raised straight into the Qt event loop, which cannot
propagate a Python exception, and the process died with **SIGABRT** — while the
user was simply trying to watch something.

Recording that a stream failed is bookkeeping. Losing a piece of bookkeeping is
acceptable; losing the application is not.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest
from loguru import logger

from metatv.core.database import Database
from metatv.core.stream_retry_manager import StreamRetryManager


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — a lock needs a real file to be held."""
    database = Database(f"sqlite:///{tmp_path / 'retry.db'}")
    database.create_tables()
    return database


@pytest.fixture
def manager(db, qapp):
    mgr = StreamRetryManager(db=db, validate_fn=lambda url: True)
    yield mgr
    mgr.stop()
    mgr._executor.shutdown(wait=True)


def _drain(manager) -> None:
    """Wait for the single writer thread to finish what was queued."""
    manager._executor.submit(lambda: None).result(timeout=10)


def test_add_failure_recovers_from_a_real_lock(manager, tmp_path):
    """A real EXCLUSIVE lock, held and released — the write waits, then lands.

    This is the shape that crashed: a background writer holding SQLite's single
    write lock while a play failure is recorded. With the write off the UI
    thread, the wait costs nothing visible and the record still arrives.
    """
    # check_same_thread=False, or the Timer below cannot release it: sqlite3
    # connections are thread-bound by default and rollback() from another
    # thread raises INSIDE the timer, silently, leaving the lock held for the
    # full 30 s busy_timeout. Cost one confusing red run.
    blocker = sqlite3.connect(tmp_path / "retry.db", check_same_thread=False)
    blocker.execute("BEGIN EXCLUSIVE")

    manager.add_failure("p1_1", "IT| SKY DAZN 1 UHD",
                        "https://host/live/u/p/1.ts", "HTTP 500")

    threading.Timer(0.4, lambda: (blocker.rollback(), blocker.close())).start()
    _drain(manager)

    assert any(e.channel_id == "p1_1" for e in manager.get_all_pending()), (
        "the write was lost rather than retried after the lock cleared")


def test_a_write_error_cannot_reach_the_event_loop(manager, monkeypatch):
    """Containment, forced — the half a lock cannot demonstrate quickly.

    A real lock eventually clears. What killed the app was the exception
    ESCAPING: Qt's event loop cannot propagate a Python exception, so an
    OperationalError raised from a slot aborted the process with SIGABRT.
    Recording a stream failure is bookkeeping; losing it is acceptable, losing
    the application is not.
    """
    from sqlalchemy.exc import OperationalError

    from metatv.core import stream_retry_manager as module

    def _boom(self, *a, **kw):
        raise OperationalError("INSERT ...", {}, Exception("database is locked"))

    monkeypatch.setattr(module.StreamRetryRepository, "add", _boom)

    seen = []
    sink = logger.add(lambda m: seen.append(m), level="ERROR")
    try:
        manager.add_failure("p1_boom", "Doomed", "https://host/live/u/p/9.ts", "500")
        _drain(manager)                 # must not raise
    finally:
        logger.remove(sink)

    # Assert the handler RAN. Without this the test passes even when the except
    # clause is removed, because the exception lands in a Future nobody
    # inspects — invisible, and exactly the fake coverage a mutation exposed.
    assert any("add_failure failed" in str(m) for m in seen), (
        "the write error was not caught and reported — it escaped into a "
        "Future instead, where nothing will ever look at it")

    monkeypatch.undo()
    manager.add_failure("p1_after", "Fine", "https://host/live/u/p/8.ts", "500")
    _drain(manager)
    assert any(e.channel_id == "p1_after" for e in manager.get_all_pending()), (
        "the manager stopped working after one failed write")


def test_the_write_does_not_run_on_the_calling_thread(manager, monkeypatch):
    """Thread identity, not elapsed time.

    A timing assertion passes trivially when the database is not contended,
    which is every test run — a mutation that put the write back on the calling
    thread sailed through it. What actually matters is WHICH thread commits:
    on the UI thread a held lock blocks the event loop for the full 30-second
    busy_timeout, and an error there aborts the process.
    """
    from metatv.core import stream_retry_manager as module

    caller = threading.current_thread().name
    ran_on = []
    original = module.StreamRetryRepository.add

    def spy(self, *a, **kw):
        ran_on.append(threading.current_thread().name)
        return original(self, *a, **kw)

    monkeypatch.setattr(module.StreamRetryRepository, "add", spy)

    manager.add_failure("p1_3", "Threaded", "https://host/live/u/p/3.ts", "500")
    _drain(manager)

    assert ran_on, "the write never happened"
    assert ran_on[0] != caller, (
        f"the write committed on the caller's thread ({caller}) — on the UI "
        f"thread that is a 30 s freeze, or a SIGABRT if it raises")


def test_the_write_actually_happens(manager):
    """Non-degeneracy: a method that silently did nothing would pass the rest."""
    manager.add_failure("p1_4", "Real", "https://host/live/u/p/4.ts", "HTTP 500")
    _drain(manager)

    pending = manager.get_all_pending()
    assert any(e.channel_id == "p1_4" for e in pending), (
        "nothing was written — the off-thread path is a no-op")


def test_a_mutation_after_shutdown_does_not_raise(manager):
    """Quitting mid-playback must not turn into a crash on the way out."""
    manager._executor.shutdown(wait=True)

    manager.add_failure("p1_5", "Late", "https://host/live/u/p/5.ts", "HTTP 500")
    manager.clear_all()          # neither may raise
