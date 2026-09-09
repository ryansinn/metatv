"""BUS-2 — bulk hide/favorite/queue now publish to ``ChannelStateBus``.

The audit's finding: bulk mutation handlers write the same
favorite/hidden/queued axes the single-item handlers do, but each ended in a
hand-picked list of the views it happened to remember to refresh, never
``channel_state_bus.publish()`` — reopening the exact class of bug #311 the
bus exists to prevent, for the bulk path specifically. The gap was
self-documented in ``channel_state_bus.py``'s own module docstring ("Known
gap — bulk mutations do NOT publish").

Proven RED pre-fix: with this test file in place, reverting
``main_window_favorites.py``'s ``_bulk_add_to_favorites``/``_bulk_add_to_queue``
and ``main_window_metadata.py``'s ``_bulk_hide_channels`` to their pre-BUS-2
bodies (a bare ``with self.db.session_scope():`` loop + the hand-picked
refresh tail, no ``_run_query``, no publish loop) turns every
"publishes one delta per channel" and "runs off main thread" assertion below
red: ``recorder.received``/``order_log`` stay empty because nothing publishes,
and ``thread_log`` stays empty because the write never goes through
``_run_query``/the executor at all. Verified by hand via ``git stash`` on the
two source files with this file left in place, then ``git stash pop`` to
restore the fix.

``_bulk_mark_watched`` is deliberately absent — "watched" isn't a field
``ChannelActionState`` tracks at all (not even its single-channel siblings,
``_mark_channel_watched``/``_mark_channel_unwatched``, publish to this bus),
so it is out of BUS-2's scope. See ``channel_state_bus.py``'s module
docstring for the full reasoning, including the measured re-read cost of
publishing per-channel over a bulk selection.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from metatv.core.database import Database


def _make_channel(db_obj, channel_id: str, **kw) -> None:
    """Seed a channel via a raw session — deliberately bypasses session_scope
    so seeding never shows up in a test's write/thread recording (mirrors
    tests/test_channel_state_writes_offthread.py's helper of the same name)."""
    from metatv.core.database import ChannelDB

    session = db_obj.SessionLocal()
    session.add(ChannelDB(
        id=channel_id, source_id=channel_id, provider_id="prov1",
        name=f"Test {channel_id}", media_type="movie", **kw,
    ))
    session.commit()
    session.close()


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'bus2_bulk.db'}")
    d.create_tables()
    yield d
    d.close()


class _Recorder:
    """A bound-method target for ChannelStateBus.subscribe (WeakMethod needs one)."""

    def __init__(self):
        self.received: list[tuple[str, dict]] = []

    def on_event(self, channel_id: str, delta: dict) -> None:
        self.received.append((channel_id, delta))


# ---------------------------------------------------------------------------
# Behavior: each bulk mutation publishes one delta PER channel, matching the
# single-item sibling's delta shape exactly.
# ---------------------------------------------------------------------------


def test_bulk_add_to_favorites_publishes_one_delta_per_channel(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bf-1", "bf-2", "bf-3"]
    for cid in ids:
        _make_channel(db, cid, is_favorite=False)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._bulk_add_to_favorites(ids)

    assert recorder.received == [(cid, {"is_favorite": True}) for cid in ids]
    # Tier-2's authoritative re-read (inline executor) ran once per channel —
    # the details pane received a state for every channel in the batch.
    seen_ids = {s.channel_id for s in host.details_pane.applied_states}
    assert seen_ids == set(ids)
    for state in host.details_pane.applied_states:
        assert state.is_favorite is True


def test_bulk_add_to_favorites_skips_missing_channels(db):
    """A channel_id with no row must not publish — mirrors the write's own
    silent skip (repos.channels.get_by_id returns None)."""
    from tests.conftest import make_channel_state_bus_host

    _make_channel(db, "bf-real", is_favorite=False)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._bulk_add_to_favorites(["bf-real", "bf-ghost"])

    assert recorder.received == [("bf-real", {"is_favorite": True})]


def test_bulk_add_to_queue_publishes_one_delta_per_channel(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bq-1", "bq-2"]
    for cid in ids:
        _make_channel(db, cid)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._bulk_add_to_queue(ids)

    assert recorder.received == [(cid, {"in_queue": True}) for cid in ids]
    for state in host.details_pane.applied_states:
        assert state.in_queue is True


def test_bulk_add_to_queue_idempotent_publish_for_already_queued(db):
    """queue.add() no-ops for a channel already queued; publish must still
    fire — an idempotent True is still the correct, current state."""
    from tests.conftest import make_channel_state_bus_host

    _make_channel(db, "bq-dup")
    host = make_channel_state_bus_host(db)
    host._bulk_add_to_queue(["bq-dup"])  # seed membership
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._bulk_add_to_queue(["bq-dup"])  # already queued

    assert recorder.received == [("bq-dup", {"in_queue": True})]


def test_bulk_hide_channels_publishes_one_delta_per_channel(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bh-1", "bh-2", "bh-3"]
    for cid in ids:
        _make_channel(db, cid)
    host = make_channel_state_bus_host(db)
    recorder = _Recorder()
    host.channel_state_bus.subscribe(recorder.on_event)

    host._bulk_hide_channels(ids)

    assert recorder.received == [(cid, {"is_hidden": True}) for cid in ids]
    for state in host.details_pane.applied_states:
        assert state.is_hidden is True


# ---------------------------------------------------------------------------
# List-membership refreshes stay a SINGLE call, never one per channel — the
# CLAUDE.md boundary this slice must not cross in either direction.
# ---------------------------------------------------------------------------


def test_bulk_add_to_favorites_calls_load_favorites_once(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bf-once-1", "bf-once-2", "bf-once-3"]
    for cid in ids:
        _make_channel(db, cid, is_favorite=False)
    host = make_channel_state_bus_host(db)
    calls: list[str] = []
    host.load_favorites = lambda: calls.append("load_favorites")

    host._bulk_add_to_favorites(ids)

    assert calls == ["load_favorites"]


def test_bulk_add_to_queue_calls_section_refreshes_once(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bq-once-1", "bq-once-2"]
    for cid in ids:
        _make_channel(db, cid)
    host = make_channel_state_bus_host(db)
    calls: list[str] = []
    host._refresh_queue_section = lambda: calls.append("queue")
    host._refresh_recommended_section = lambda: calls.append("recommended")

    host._bulk_add_to_queue(ids)

    assert calls == ["queue", "recommended"]


def test_bulk_hide_channels_calls_view_refreshes_once(db):
    from tests.conftest import make_channel_state_bus_host

    ids = ["bh-once-1", "bh-once-2"]
    for cid in ids:
        _make_channel(db, cid)
    host = make_channel_state_bus_host(db)
    calls: list[str] = []
    host.preferences_view = type(
        "P", (), {"refresh": staticmethod(lambda: calls.append("preferences"))}
    )()
    host._refresh_recommended_section = lambda: calls.append("recommended")
    host.load_channels = lambda: calls.append("channels")

    host._bulk_hide_channels(ids)

    assert calls == ["preferences", "recommended", "channels"]


# ---------------------------------------------------------------------------
# DEBT-3 shape: the write runs off the calling thread; publish only fires
# AFTER that write has committed — never before, and never on the write's
# own thread.
# ---------------------------------------------------------------------------


class _CapturingExecutor:
    """A real ThreadPoolExecutor whose submitted futures are kept so a test
    can block on the write it just triggered (mirrors
    tests/test_channel_state_writes_offthread.py's helper of the same name)."""

    def __init__(self):
        self._real = ThreadPoolExecutor(max_workers=2)
        self.futures: list = []

    def submit(self, fn, *args, **kwargs):
        fut = self._real.submit(fn, *args, **kwargs)
        self.futures.append(fut)
        return fut


class _FakeSignal:
    def __init__(self):
        self.emitted: list = []

    def emit(self, value):
        self.emitted.append(value)


@pytest.fixture()
def order_log():
    return []


@pytest.fixture()
def thread_log(monkeypatch, order_log):
    """Patch Database.session_scope so every write appends ("write_done",
    thread) to order_log right after the real context manager commits —
    never before — delegating to the real implementation so the write
    actually happens."""
    log: list = []
    original = Database.session_scope

    @contextmanager
    def _spy(self, commit=True):
        with original(self, commit=commit) as session:
            yield session
        current = threading.current_thread()
        log.append(current)
        order_log.append(("write_done", current))

    monkeypatch.setattr(Database, "session_scope", _spy)
    return log


@pytest.fixture()
def offthread_host(db, order_log):
    from metatv.gui.channel_state_bus import ChannelStateBus
    from metatv.gui.main_window_async import _AsyncMixin
    from metatv.gui.main_window_favorites import _FavoritesMixin
    from metatv.gui.main_window_metadata import _MetadataMixin
    from tests.conftest import wire_status_method

    class _Host:
        pass

    h = _Host()
    h.db = db
    h.executor = _CapturingExecutor()
    h._query_result = _FakeSignal()
    h._processed = 0
    h.view_mode = "channels"
    h.preferences_view = type("P", (), {"refresh": lambda self: None})()
    h._refresh_recommended_section = lambda: None
    h._refresh_queue_section = lambda: None
    h.load_favorites = lambda: None
    h.load_channels = lambda: None
    h.status_bar = type("S", (), {"showMessage": lambda self, *a, **k: None})()
    wire_status_method(h)

    h.channel_state_bus = ChannelStateBus(reread=lambda cid: None)

    def _record_publish(channel_id, **delta):
        order_log.append(("published", channel_id, delta))

    h.channel_state_bus.publish = _record_publish

    h._run_query = _AsyncMixin._run_query.__get__(h)
    h._on_query_result = _AsyncMixin._on_query_result.__get__(h)
    h._write_failed = _FavoritesMixin._write_failed.__get__(h)

    h._bulk_add_to_favorites = _FavoritesMixin._bulk_add_to_favorites.__get__(h)
    h._bulk_add_to_queue = _FavoritesMixin._bulk_add_to_queue.__get__(h)
    h._bulk_hide_channels = _MetadataMixin._bulk_hide_channels.__get__(h)

    yield h
    h.executor._real.shutdown(wait=True)


def _wait_for_write(host, timeout: float = 5.0) -> None:
    """Block until the write just submitted has fully finished (including its
    commit) — but deliver nothing to the main-thread slot yet."""
    host.executor.futures[-1].result(timeout=timeout)


def _dispatch_pending(host) -> None:
    """Deliver every result not yet delivered to the main-thread slot."""
    while host._processed < len(host._query_result.emitted):
        host._on_query_result(host._query_result.emitted[host._processed])
        host._processed += 1


def test_bulk_hide_channels_runs_off_main_thread_and_publishes_after_commit(
    db, offthread_host, thread_log, order_log,
):
    ids = ["oh-1", "oh-2"]
    for cid in ids:
        _make_channel(db, cid)
    main_thread = threading.current_thread()

    offthread_host._bulk_hide_channels(ids)   # returns immediately
    _wait_for_write(offthread_host)

    assert len(thread_log) == 1
    assert thread_log[0] is not main_thread, "the write must run off the calling (main) thread"
    assert order_log == [("write_done", thread_log[0])], (
        "publish must not fire before the batch's own commit"
    )

    _dispatch_pending(offthread_host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", "oh-1", {"is_hidden": True}),
        ("published", "oh-2", {"is_hidden": True}),
    ]


def test_bulk_add_to_favorites_runs_off_main_thread_and_publishes_after_commit(
    db, offthread_host, thread_log, order_log,
):
    ids = ["of-1", "of-2"]
    for cid in ids:
        _make_channel(db, cid, is_favorite=False)
    main_thread = threading.current_thread()

    offthread_host._bulk_add_to_favorites(ids)
    _wait_for_write(offthread_host)

    assert thread_log[0] is not main_thread
    assert order_log == [("write_done", thread_log[0])]

    _dispatch_pending(offthread_host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", "of-1", {"is_favorite": True}),
        ("published", "of-2", {"is_favorite": True}),
    ]


def test_bulk_add_to_queue_runs_off_main_thread_and_publishes_after_commit(
    db, offthread_host, thread_log, order_log,
):
    ids = ["oq-1", "oq-2"]
    for cid in ids:
        _make_channel(db, cid)
    main_thread = threading.current_thread()

    offthread_host._bulk_add_to_queue(ids)
    _wait_for_write(offthread_host)

    assert thread_log[0] is not main_thread
    assert order_log == [("write_done", thread_log[0])]

    _dispatch_pending(offthread_host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", "oq-1", {"in_queue": True}),
        ("published", "oq-2", {"in_queue": True}),
    ]
