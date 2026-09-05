"""DEBT-3: favourite/rating/hide-from-alerts writes no longer block the UI thread.

``_toggle_rating`` / ``_toggle_favorite_by_id`` / ``_apply_favorite_toggle`` /
``_hide_channel_from_alerts`` (``metatv/gui/main_window_favorites.py``) used to
open ``with self.db.session_scope() as session:`` directly on whatever thread
called the handler — the Qt main thread in production. SQLite has one writer
across six uncoordinated pools, so that write could queue behind an in-flight
provider refresh and freeze the window for as long as the refresh's batch held
the lock.

Each handler now submits its write to ``_run_query(commit=True)`` instead, so
the write runs in the executor, off the calling thread, and the
``ChannelStateBus`` publish only fires from the main-thread ``on_result``
callback once the write has actually committed — never before, since tier 2's
authoritative re-read must see the new row.

Proven RED on the pre-fix code: reverting the ``main_window_favorites.py`` /
``main_window_async.py`` changes makes every "ran off the main thread"
assertion below fail, because ``session_scope`` was called synchronously on
the calling (== test) thread and there was no ``_run_query`` hop to wait on.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.gui.channel_state_bus import ChannelStateBus
from metatv.gui.main_window_async import _AsyncMixin
from metatv.gui.main_window_favorites import _FavoritesMixin


@pytest.fixture()
def db(tmp_path: Path):
    d = Database(f"sqlite:///{tmp_path / 'offthread.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(db_obj, channel_id: str, **kw) -> None:
    """Seed a channel via a raw session — deliberately bypasses session_scope
    so seeding never shows up in a test's write/order recording."""
    session = db_obj.SessionLocal()
    session.add(ChannelDB(
        id=channel_id, source_id=channel_id, provider_id="prov1",
        name="Test Movie", media_type="movie", **kw,
    ))
    session.commit()
    session.close()


def _read_bool_column(db_obj, channel_id: str, column: str) -> bool:
    """Read one column via a raw session — same bypass as _make_channel."""
    session = db_obj.SessionLocal()
    try:
        row = session.query(ChannelDB).filter_by(id=channel_id).one()
        return bool(getattr(row, column))
    finally:
        session.close()


class _CapturingExecutor:
    """A real ThreadPoolExecutor whose submitted futures are kept so a test
    can block on the specific write it just triggered without shutting the
    pool down (needed when one test drives several toggles in sequence)."""

    def __init__(self):
        self._real = ThreadPoolExecutor(max_workers=2)
        self.futures: list = []

    def submit(self, fn, *args, **kwargs):
        fut = self._real.submit(fn, *args, **kwargs)
        self.futures.append(fut)
        return fut


class _FakeSignal:
    """Stand-in for pyqtSignal(object) — records emit() calls (mirrors
    tests/test_async_query_seam.py's _FakeSignal)."""

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
    thread) to ``order_log`` (and to the returned list) right after the real
    context manager commits — never before — delegating to the real
    implementation so the write actually happens.
    """
    log: list = []
    original = Database.session_scope

    @contextmanager
    def _spy(self, commit=True):
        with original(self, commit=commit) as session:
            yield session
        # Reached only after the real __exit__ — i.e. after the commit.
        current = threading.current_thread()
        log.append(current)
        order_log.append(("write_done", current))

    monkeypatch.setattr(Database, "session_scope", _spy)
    return log


@pytest.fixture()
def host(db, order_log):
    """A bare host driving the real _FavoritesMixin write handlers against a
    REAL executor. ``channel_state_bus.publish`` appends to ``order_log`` so a
    test can assert it never fires before the write's own "write_done" entry
    (appended by the ``thread_log`` fixture). Shuts its executor down at
    teardown so no worker thread outlives the test.
    """
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
    h.load_favorites = lambda: None
    h._remove_sidebar_row = lambda *a, **k: None
    h._refresh_watch_alerts = lambda: None
    h.load_history = lambda: None
    h.load_channels = lambda: None
    h.status_bar = type("S", (), {"showMessage": lambda self, *a, **k: None})()

    h.channel_state_bus = ChannelStateBus(reread=lambda cid: None)

    def _record_publish(channel_id, **delta):
        order_log.append(("published", channel_id, delta))

    h.channel_state_bus.publish = _record_publish

    h._run_query = _AsyncMixin._run_query.__get__(h)
    h._on_query_result = _AsyncMixin._on_query_result.__get__(h)

    h._toggle_rating = _FavoritesMixin._toggle_rating.__get__(h)
    h._toggle_favorite_by_id = _FavoritesMixin._toggle_favorite_by_id.__get__(h)
    h._apply_favorite_toggle = _FavoritesMixin._apply_favorite_toggle.__get__(h)
    h._hide_channel_from_alerts = _FavoritesMixin._hide_channel_from_alerts.__get__(h)

    yield h
    h.executor._real.shutdown(wait=True)


def _wait_for_write(host, timeout: float = 5.0) -> None:
    """Block until the write just submitted has fully finished (including its
    commit) — but deliver nothing to the main-thread slot yet."""
    host.executor.futures[-1].result(timeout=timeout)


def _dispatch_pending(host) -> None:
    """Deliver every result not yet delivered to the main-thread slot (mirrors
    tests/test_async_query_seam.py's manual-dispatch pattern)."""
    while host._processed < len(host._query_result.emitted):
        host._on_query_result(host._query_result.emitted[host._processed])
        host._processed += 1


def test_toggle_rating_runs_off_main_thread_and_publishes_once(db, host, thread_log, order_log):
    channel_id = "ch-rating"
    _make_channel(db, channel_id)
    main_thread = threading.current_thread()

    host._toggle_rating(channel_id, 1)   # returns immediately
    _wait_for_write(host)

    assert len(thread_log) == 1
    assert thread_log[0] is not main_thread, "the write must run off the calling (main) thread"
    assert order_log == [("write_done", thread_log[0])], (
        "the write must commit before anything is delivered to on_result"
    )

    _dispatch_pending(host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", channel_id, {"rating": 1}),
    ], "publish must not fire before the write's commit"


def test_toggle_rating_clear_runs_off_thread_and_publishes_zero(db, host, thread_log, order_log):
    channel_id = "ch-rating-clear"
    _make_channel(db, channel_id)

    host._toggle_rating(channel_id, 1)
    _wait_for_write(host)
    _dispatch_pending(host)
    host._toggle_rating(channel_id, 1)   # click the active rating again -> clears
    _wait_for_write(host)
    _dispatch_pending(host)

    assert len(thread_log) == 2
    assert order_log[-1] == ("published", channel_id, {"rating": 0})


def test_toggle_favorite_by_id_runs_off_main_thread_and_publishes_once(
    db, host, thread_log, order_log,
):
    channel_id = "ch-fav-explicit"
    _make_channel(db, channel_id, is_favorite=False)
    main_thread = threading.current_thread()

    host._toggle_favorite_by_id(channel_id, True)
    _wait_for_write(host)

    assert thread_log[0] is not main_thread
    assert order_log == [("write_done", thread_log[0])]

    _dispatch_pending(host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", channel_id, {"is_favorite": True}),
    ]
    assert _read_bool_column(db, channel_id, "is_favorite") is True


def test_apply_favorite_toggle_runs_off_main_thread_and_publishes_once(
    db, host, thread_log, order_log,
):
    channel_id = "ch-fav-toggle"
    _make_channel(db, channel_id, is_favorite=False)
    main_thread = threading.current_thread()

    host._apply_favorite_toggle(channel_id)
    _wait_for_write(host)

    assert thread_log[0] is not main_thread
    assert order_log == [("write_done", thread_log[0])]

    _dispatch_pending(host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", channel_id, {"is_favorite": True}),
    ]


def test_hide_channel_from_alerts_runs_off_main_thread_and_publishes_once(
    db, host, thread_log, order_log,
):
    channel_id = "ch-hide"
    _make_channel(db, channel_id)
    main_thread = threading.current_thread()

    host._hide_channel_from_alerts(channel_id)
    _wait_for_write(host)

    assert thread_log[0] is not main_thread
    assert order_log == [("write_done", thread_log[0])]

    _dispatch_pending(host)

    assert order_log == [
        ("write_done", thread_log[0]),
        ("published", channel_id, {"is_hidden": True}),
    ]
    assert _read_bool_column(db, channel_id, "is_hidden") is True
