"""DB-10 — core.write_gate / Database.session_scope(background=True).

Real ``Database`` on a ``tmp_path`` FILE throughout (never ``:memory:``,
CLAUDE.md "Tests — prove behavior"). Serialization is proven by instrumented
entry/exit counters under a ``threading.Barrier``, never by timing/sleep
comparisons — two threads are made to WANT to run at the same instant, and a
shared counter records how many were actually inside the critical section at
once.
"""

from __future__ import annotations

import re
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from loguru import logger

from metatv.core import write_gate
from metatv.core.database import ProfileDB

# How long a worker holds the gate/scope open. Long enough that any missed
# serialization is virtually certain to be observed (thread-scheduling jitter
# is microseconds; this is 150ms), short enough the suite stays fast.
_HOLD_S = 0.15


class _Recorder:
    """Thread-safe: how many holders were inside a critical section at once."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.events: list[tuple[str, str]] = []

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.events.append((threading.current_thread().name, "enter"))

    def exit(self) -> None:
        with self._lock:
            self.events.append((threading.current_thread().name, "exit"))
            self.active -= 1


def _start(fn, *, name: str) -> threading.Thread:
    t = threading.Thread(target=fn, name=name, daemon=True)
    t.start()
    return t


# ---------------------------------------------------------------------------
# core.write_gate — the primitive, no Database involved
# ---------------------------------------------------------------------------

def test_background_write_gate_serializes_two_threads():
    """Two threads both wanting the gate at once must never run concurrently."""
    rec = _Recorder()
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=5)
        with write_gate.background_write_gate():
            rec.enter()
            time.sleep(_HOLD_S)
            rec.exit()

    t1 = _start(worker, name="w1")
    t2 = _start(worker, name="w2")
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()

    assert rec.max_active == 1, f"background writers overlapped: {rec.events}"


def test_gate_free_baseline_actually_overlaps():
    """Mutation check: prove the barrier+sleep technique above is not vacuous.

    With NO gate at all (a plain no-op context manager — what every one of
    DB-10's call sites looked like before this slice), the same two threads
    DO run concurrently. This is what the suite looked like pre-fix: nothing
    serialized a background writer against another, so this assertion would
    have been the honest (failing-to-serialize) baseline.
    """
    rec = _Recorder()
    barrier = threading.Barrier(2)

    @contextmanager
    def _no_gate():
        yield

    def worker():
        barrier.wait(timeout=5)
        with _no_gate():
            rec.enter()
            time.sleep(_HOLD_S)
            rec.exit()

    t1 = _start(worker, name="w1")
    t2 = _start(worker, name="w2")
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert rec.max_active == 2, (
        "sanity check failed: two threads holding a no-op context manager "
        "should overlap — if this fails, the barrier/sleep technique itself "
        "is unreliable and the serialization test above proves nothing"
    )


def test_background_write_gate_reentrant_same_thread_does_not_block():
    """A thread that already holds the gate passes straight through a nested acquire.

    A migration task (gated at MigrationManager's dispatch chokepoint) that
    calls MetadataManager._persist_metadata_cache (itself gated) is exactly
    this shape in production. If reentrancy were broken this would hang for
    GATE_TIMEOUT_S (15s) before "proceeding anyway" rather than returning
    immediately — the 2s join timeout below is what turns that into a fast
    failure instead of a slow one.
    """
    def worker():
        with write_gate.background_write_gate():
            with write_gate.background_write_gate():
                pass

    started = time.monotonic()
    t = _start(worker, name="reentrant")
    t.join(timeout=2)
    assert not t.is_alive(), "nested acquire on the same thread did not return promptly"
    assert time.monotonic() - started < 2.0


def test_background_write_gate_main_thread_never_blocks():
    """The main thread passes straight through even while another thread holds the gate.

    Several write helpers are shared between a manager's background loop and
    a direct main-thread call (DownloadManager._set_state, used by both the
    transfer loop and pause()/resume()/cancel()) — the gate must never turn a
    UI click into a wait.
    """
    holding = threading.Event()
    release = threading.Event()

    def holder():
        with write_gate.background_write_gate():
            holding.set()
            release.wait(timeout=5)

    t = _start(holder, name="holder")
    try:
        assert holding.wait(timeout=2), "holder thread never acquired the gate"
        started = time.monotonic()
        with write_gate.background_write_gate():  # this call IS the main thread
            pass
        assert time.monotonic() - started < 1.0, "main thread blocked on the gate"
    finally:
        release.set()
        t.join(timeout=5)


def test_background_write_gate_timeout_logs_once_and_proceeds(monkeypatch):
    """A caller that cannot acquire the gate in time logs a warning and still runs.

    Never silently skips the write, never blocks indefinitely — see
    write_gate.py's "Timeout, not an unbounded wait".
    """
    monkeypatch.setattr(write_gate, "GATE_TIMEOUT_S", 0.1)
    holding = threading.Event()
    release = threading.Event()

    def holder():
        with write_gate.background_write_gate():
            holding.set()
            release.wait(timeout=5)

    t = _start(holder, name="holder")
    ran: list[bool] = []
    messages: list[str] = []
    sink_id = logger.add(lambda msg: messages.append(str(msg)), level="WARNING")
    try:
        assert holding.wait(timeout=2), "holder thread never acquired the gate"

        def waiter():
            with write_gate.background_write_gate():
                ran.append(True)

        t2 = _start(waiter, name="waiter")
        t2.join(timeout=3)
        assert not t2.is_alive(), "timed-out caller never returned"
    finally:
        logger.remove(sink_id)
        release.set()
        t.join(timeout=5)

    assert ran == [True], "a caller that timed out waiting for the gate must still run its body"
    assert any("write_gate" in m and "waited" in m for m in messages), (
        f"expected a one-time timeout warning; got: {messages}"
    )


# ---------------------------------------------------------------------------
# Database.session_scope(background=True) — the real integration point
# ---------------------------------------------------------------------------

def test_session_scope_background_gates_two_writers(db):
    """Two session_scope(background=True) writers must serialize."""
    rec = _Recorder()
    barrier = threading.Barrier(2)

    def worker(key: str, value: str):
        barrier.wait(timeout=5)
        with db.session_scope(background=True) as session:
            rec.enter()
            time.sleep(_HOLD_S)
            session.add(ProfileDB(key=key, value=value))
            rec.exit()

    t1 = _start(lambda: worker("db10-k1", "v1"), name="db-w1")
    t2 = _start(lambda: worker("db10-k2", "v2"), name="db-w2")
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()

    assert rec.max_active == 1, f"background writers overlapped: {rec.events}"

    with db.session_scope(commit=False) as session:
        keys = {row.key for row in session.query(ProfileDB)
                .filter(ProfileDB.key.in_(("db10-k1", "db10-k2"))).all()}
    assert keys == {"db10-k1", "db10-k2"}, "both writes must still land"


def test_session_scope_ui_path_write_is_not_gated(db):
    """A write WITHOUT background=True (the _run_query(commit=True) UI path)
    must run concurrently with another writer, never queue behind the gate —
    it stays latency-sensitive by design."""
    rec = _Recorder()
    barrier = threading.Barrier(2)

    def worker(key: str, value: str):
        barrier.wait(timeout=5)
        with db.session_scope() as session:   # no background=True
            rec.enter()
            time.sleep(_HOLD_S)
            session.add(ProfileDB(key=key, value=value))
            rec.exit()

    t1 = _start(lambda: worker("db10-ui1", "v1"), name="ui-w1")
    t2 = _start(lambda: worker("db10-ui2", "v2"), name="ui-w2")
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive()

    assert rec.max_active == 2, (
        "a UI-path write (no background=True) must not be serialized by "
        "DB-10's gate — favourite/rating toggles etc. must stay instant"
    )


def test_session_scope_background_ignored_for_read_only(db):
    """background=True is a no-op when commit=False — reads are unaffected."""
    rec = _Recorder()
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait(timeout=5)
        with db.session_scope(commit=False, background=True) as session:
            rec.enter()
            time.sleep(_HOLD_S)
            session.query(ProfileDB).count()
            rec.exit()

    t1 = _start(worker, name="r1")
    t2 = _start(worker, name="r2")
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert rec.max_active == 2, "a read-only scope must never be gated, even with background=True"


# ---------------------------------------------------------------------------
# Census guard — "a runner that ran nothing exits 0" (CLAUDE.md)
# ---------------------------------------------------------------------------

#: file -> minimum number of gated write call sites expected in it. Minimums,
#: not exact counts, so an unrelated addition to one of these files never
#: fails this test — but a refactor that quietly drops the background=True
#: kwarg (or the whole gated block) from a file DOES. New background-writer
#: files belong here too, alongside their DB-10 census entry in the PR.
_MIN_GATED_SITES = {
    "metatv/core/download_manager.py": 8,
    "metatv/core/epg_fetch.py": 3,
    "metatv/core/epg_manager.py": 1,
    "metatv/core/metadata_enrichment_queue.py": 2,
    "metatv/core/metadata_manager.py": 1,
    "metatv/core/profile_store.py": 2,
    "metatv/core/recording_manager.py": 7,
    "metatv/core/signal_check_manager.py": 1,
    "metatv/core/stream_retry_manager.py": 2,
    "metatv/core/tmdb_enrichment_manager.py": 4,
    "metatv/core/watchlist.py": 3,
}

#: files gated via a direct ``with write_gate.background_write_gate():`` wrap
#: (a legacy get_session()/try/finally block, or MigrationManager's dispatch
#: chokepoint) rather than session_scope(background=True).
_MIN_DIRECT_WRAPS = {
    "metatv/core/epg_fetch.py": 1,       # _run_fetch's chunked programme store
    "metatv/core/epg_manager.py": 1,     # _relink_worker
    "metatv/core/migration_manager.py": 1,  # every migration task, incl. orphan sweep
}

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_background_writer_census_is_not_empty():
    """DB-10's gate must actually gate something, everywhere the census found.

    A grep-based repo-wide guard, same family as test_no_stray_color_literals
    et al. (CLAUDE.md "--quick cannot see a repo-wide drift guard") — no
    single changed-file selection would ever pick this up on its own.
    """
    total_kwarg_sites = 0
    for rel_path, minimum in _MIN_GATED_SITES.items():
        text = (_REPO_ROOT / rel_path).read_text()
        count = len(re.findall(r"session_scope\(background=True\)", text))
        assert count >= minimum, (
            f"{rel_path}: expected >= {minimum} session_scope(background=True) "
            f"site(s), found {count} — a background writer lost its gate"
        )
        total_kwarg_sites += count

    total_direct_wraps = 0
    for rel_path, minimum in _MIN_DIRECT_WRAPS.items():
        text = (_REPO_ROOT / rel_path).read_text()
        count = len(re.findall(r"with write_gate\.background_write_gate\(\)", text))
        assert count >= minimum, (
            f"{rel_path}: expected >= {minimum} direct write_gate wrap(s), "
            f"found {count} — a background writer lost its gate"
        )
        total_direct_wraps += count

    assert total_kwarg_sites >= 30
    assert total_direct_wraps >= 3
