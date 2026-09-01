"""Behavioral tests for the Wave 5 stream-recovery UX fixes (S1 + S2).

S2 — the sidebar's Stream Monitoring list dropped a stream the instant it
recovered because both the repository read (``get_all_pending``) and its
``StreamRetryManager`` wrapper filtered to ``status == "pending"`` only. The
green-icon/"Back online!" rendering already existed in ``sidebar/alerts.py``
but was unreachable. Fix: a new ``get_all_display`` read (pending + online)
feeds the sidebar; ``get_all_pending`` is untouched so the background checker
never re-probes an already-recovered row.

S1 — the "back online" toast (``_on_stream_back_online``) had no way to
actually play the recovered stream; it now carries a Play action wired to
the existing retry-play seam (``_on_retry_play_requested`` — the same handler
double-clicking the Stream Monitoring row uses).

All DB-backed tests use file-backed SQLite (tmp_path) per CLAUDE.md rule.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# S2: repository read — get_all_display includes "online", get_all_pending doesn't
# ---------------------------------------------------------------------------

def _make_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'retry.db'}")
    d.create_tables()
    return d


def test_repo_get_all_display_includes_online_rows(tmp_path):
    from metatv.core.repositories.stream_retry import StreamRetryRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        entry = repo.add("ch1", "Channel One", "http://x/1.ts", "timeout")
        repo.mark_checked(entry, ok=True, error=None)  # recovers -> status="online"

    with db.session_scope(commit=False) as session:
        repo = StreamRetryRepository(session)
        display = repo.get_all_display()
        assert len(display) == 1
        assert display[0].status == "online"
        assert display[0].channel_id == "ch1"
    db.close()


def test_repo_get_all_pending_excludes_online_rows_so_checker_never_reprobes(tmp_path):
    """The checker's read (get_all_pending) must NOT see a recovered row."""
    from metatv.core.repositories.stream_retry import StreamRetryRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        entry = repo.add("ch1", "Channel One", "http://x/1.ts", "timeout")
        repo.mark_checked(entry, ok=True, error=None)

    with db.session_scope(commit=False) as session:
        repo = StreamRetryRepository(session)
        pending = repo.get_all_pending()

    assert pending == []
    db.close()


def test_repo_get_all_display_still_includes_pending_rows(tmp_path):
    """Sanity: get_all_display doesn't drop still-pending rows."""
    from metatv.core.repositories.stream_retry import StreamRetryRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        repo.add("ch1", "Channel One", "http://x/1.ts", "timeout")

    with db.session_scope(commit=False) as session:
        repo = StreamRetryRepository(session)
        display = repo.get_all_display()
        assert len(display) == 1
        assert display[0].status == "pending"
    db.close()


# ---------------------------------------------------------------------------
# S2: StreamRetryManager wrapper mirrors the repository split
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_manager_get_all_display_returns_online_entries(qapp, tmp_path):
    from metatv.core.repositories.stream_retry import StreamRetryRepository
    from metatv.core.stream_retry_manager import StreamRetryManager

    db = _make_db(tmp_path)
    mgr = StreamRetryManager(db, validate_fn=lambda url: (True, None))
    # Seeded through the repository, NOT mgr.add_failure(): that write is
    # deliberately off-thread (see StreamRetryManager._write — a main-thread
    # commit against a held SQLite lock killed the app with SIGABRT), so
    # reading straight back raced the worker. It won on a quiet laptop and
    # lost on a loaded macOS runner, which is why this file failed CI while
    # passing locally 8/8. The subject here is the display read, not the write.
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        entry = repo.add("ch1", "Channel One", "http://x/1.ts", "timeout")
        repo.mark_checked(entry, ok=True, error=None)

    display = mgr.get_all_display()
    pending = mgr.get_all_pending()

    assert len(display) == 1
    assert display[0].status == "online"
    assert pending == []
    db.close()


def test_main_window_refresh_uses_display_read_not_pending(qapp, tmp_path):
    """_refresh_alerts_retry_section must use get_all_display (S2 fix site)."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.sidebar_sections = {"alerts": MagicMock()}
    host.stream_retry_manager = MagicMock()
    host.stream_retry_manager.get_all_display.return_value = ["online-entry"]

    host._refresh_alerts_retry_section()

    host.stream_retry_manager.get_all_display.assert_called_once()
    host.stream_retry_manager.get_all_pending.assert_not_called()
    host.sidebar_sections["alerts"].refresh_retry.assert_called_once_with(["online-entry"])


# ---------------------------------------------------------------------------
# S2: widget renders the green icon + "Back online!" tooltip (offscreen)
# ---------------------------------------------------------------------------

def test_widget_refresh_retry_renders_green_icon_and_tooltip_for_online_entry(qapp, tmp_path):
    from metatv.core.config import Config
    from metatv.core.stream_retry_manager import StreamRetryEntry
    from metatv.gui import icons as _icons
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    cfg = Config(config_dir=tmp_path)
    section = WatchAlertsSection(cfg, MagicMock())

    entry = StreamRetryEntry(
        id="r1", channel_id="ch1", channel_name="Channel One",
        stream_url="http://x/1.ts", status="online", attempt_count=2,
        last_error="timeout", next_check_at=None,
    )
    section.refresh_retry([entry])

    assert section._retry_list.count() == 1
    item = section._retry_list.item(0)
    assert _icons.stream_retry_online_icon in item.text()
    assert _icons.stream_retry_pending_icon not in item.text()
    assert "Back online!" in item.toolTip()

    section.setParent(None)
    section.deleteLater()
    qapp.processEvents()


def test_widget_refresh_retry_renders_pending_icon_for_pending_entry(qapp, tmp_path):
    """Sanity companion: a still-pending row keeps the red/pending icon."""
    from metatv.core.config import Config
    from metatv.core.stream_retry_manager import StreamRetryEntry
    from metatv.gui import icons as _icons
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    cfg = Config(config_dir=tmp_path)
    section = WatchAlertsSection(cfg, MagicMock())

    entry = StreamRetryEntry(
        id="r2", channel_id="ch2", channel_name="Channel Two",
        stream_url="http://x/2.ts", status="pending", attempt_count=1,
        last_error="timeout", next_check_at=None,
    )
    section.refresh_retry([entry])

    item = section._retry_list.item(0)
    assert _icons.stream_retry_pending_icon in item.text()
    assert _icons.stream_retry_online_icon not in item.text()

    section.setParent(None)
    section.deleteLater()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# S1: back-online toast carries a Play action wired to the retry-play seam
# ---------------------------------------------------------------------------

def test_manager_emits_stream_online_with_stream_url(qapp, tmp_path):
    """The widened stream_online signal emits (channel_id, channel_name, stream_url)."""
    from metatv.core.repositories.stream_retry import StreamRetryRepository
    from metatv.core.stream_retry_manager import StreamRetryManager

    db = _make_db(tmp_path)
    mgr = StreamRetryManager(db, validate_fn=lambda url: (True, None))
    # Same reason as above: add_failure returns before the row exists, and
    # _run_checks below reads it synchronously on THIS thread. CI caught the
    # loss exactly as you would expect —
    #   assert [] == [('ch1', 'Channel One', 'http://x/1.ts')]
    # with the worker still alive at teardown ("left Python thread(s)
    # running: ['stream_retry_0']"). Seeding directly also means no worker
    # thread is started at all, so the QtResourceLeakWarning goes with it.
    with db.session_scope() as session:
        StreamRetryRepository(session).add(
            "ch1", "Channel One", "http://x/1.ts", "timeout")

    received = []
    mgr.stream_online.connect(lambda cid, name, url: received.append((cid, name, url)))

    mgr._run_checks(force_all=True)

    assert received == [("ch1", "Channel One", "http://x/1.ts")]
    db.close()


def test_stream_back_online_toast_has_play_action_wired_to_retry_play():
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.notification_manager = MagicMock()
    host._refresh_alerts_retry_section = MagicMock()
    host._on_retry_play_requested = MagicMock()

    host._on_stream_back_online("ch-1", "FOX SPORTS 1", "http://example.com/stream.ts")

    host.notification_manager.show.assert_called_once()
    kwargs = host.notification_manager.show.call_args.kwargs
    actions = dict(kwargs.get("actions", []))
    assert "Play" in actions

    actions["Play"]()

    host._on_retry_play_requested.assert_called_once_with(
        "ch-1", "http://example.com/stream.ts", "FOX SPORTS 1"
    )
    host._refresh_alerts_retry_section.assert_called_once()


def test_stream_back_online_toast_play_defaults_to_empty_url_when_omitted():
    """Backward-compat: stream_url defaults to "" (older-shaped callers)."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.notification_manager = MagicMock()
    host._refresh_alerts_retry_section = MagicMock()
    host._on_retry_play_requested = MagicMock()

    host._on_stream_back_online("ch-1", "FOX SPORTS 1")

    kwargs = host.notification_manager.show.call_args.kwargs
    actions = dict(kwargs.get("actions", []))
    actions["Play"]()

    host._on_retry_play_requested.assert_called_once_with("ch-1", "", "FOX SPORTS 1")
