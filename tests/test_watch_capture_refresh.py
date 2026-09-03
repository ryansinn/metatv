"""HIST-1 / PLAY-9 (2026-09-03): a play never appeared in History, and a movie
watched to the end was silently dropped from tracking if mpv exited between
20s checkpoints (EOF or a manual quit) instead of finalising the last sample.

HIST-1 root cause: ``_record_play`` called ``self.load_history()``
synchronously, immediately after submitting ``_bg_mark_played`` to the
executor — the refresh read the DB before the write committed (owner's log:
refresh at 01:58:59.3, commit at 01:59:00.8). ``_WatchNotifier.history_changed``
(``metatv/gui/watch_capture.py``) closes that race: workers emit it only AFTER
their ``session_scope()`` block commits, and ``_on_history_changed`` (the
main-thread slot) is what actually calls ``load_history()`` and republishes on
``channel_state_bus`` (so the details pane's Resume button stops going stale
after playback ends).

PLAY-9 root cause: ``_watch_checkpoint_tick``'s close branch (a tracked key
that disappeared from ``player_manager.active_keys()`` between ticks) only
finalised QUEUED episodes. A movie or single (non-queued) episode was popped
from tracking silently — its last position was never persisted and a >=90%
watch never promoted to completed. ``_update_last_sample`` now records the
last sampled position/duration on every ``_bg_capture_watch`` tick for
non-queued tracks; the close branch finalises it via ``_bg_finalise_progress``.

Covered here:
1. Ordering proof — ``_bg_mark_played`` emits ``history_changed`` only after
   its write commits (a recorder that queries the DB mid-callback sees the
   committed row).
2. ``_on_history_changed`` calls ``load_history()`` and republishes on
   ``channel_state_bus``.
3. PLAY-9 close-branch finalise: a >=90% last sample is promoted to completed.
4. PLAY-9 close-branch finalise: a partial last sample persists as a resume
   point, not completed.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories import RepositoryFactory


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'watch_capture_refresh.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_channel(db, ch_id: str, media_type: str = "movie") -> None:
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=ch_id, source_id=ch_id, provider_id="p1",
            name=ch_id, media_type=media_type,
            stream_url=f"http://example.com/{ch_id}.mp4",
        ))


# ---------------------------------------------------------------------------
# 1. Ordering proof (HIST-1): history_changed fires only after the commit.
# ---------------------------------------------------------------------------

def test_bg_mark_played_emits_only_after_write_commits(db, qapp):
    from metatv.gui.main_window_streaming import _StreamingMixin
    from metatv.gui.watch_capture import _WatchNotifier

    _seed_channel(db, "c1", "live")

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    # _WatchNotifier's real parent is the QMainWindow-derived MainWindow; this
    # bare mixin host isn't a QObject, so construct it parentless here.
    host._watch_notifier = _WatchNotifier()

    seen: list[str] = []

    def _recorder(channel_id):
        # If history_changed fired before the write committed, last_played
        # would still be None here — this is the HIST-1 race made assertable.
        with db.session_scope(commit=False) as session:
            ch = RepositoryFactory(session).channels.get_by_id(channel_id)
            assert ch.last_played is not None, (
                "history_changed fired before the mark_played write committed")
        seen.append(channel_id)

    host._watch_notifier.history_changed.connect(_recorder)

    host._bg_mark_played("c1", None)

    assert seen == ["c1"], "recorder did not fire exactly once with the channel id"


# ---------------------------------------------------------------------------
# 2. _on_history_changed refreshes History and republishes on the state bus.
# ---------------------------------------------------------------------------

def test_on_history_changed_refreshes_history_and_publishes_state(qapp):
    from metatv.gui.main_window_streaming import _StreamingMixin
    from tests.conftest import attach_channel_state_bus

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.load_history = MagicMock()
    attach_channel_state_bus(host)
    host.channel_state_bus.publish = MagicMock()

    host._on_history_changed("c1")

    host.load_history.assert_called_once()
    host.channel_state_bus.publish.assert_called_once_with("c1")


def test_on_history_changed_skips_publish_with_no_channel_id(qapp):
    """Some emit paths could carry None; publish must not fire on nothing."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    from tests.conftest import attach_channel_state_bus

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.load_history = MagicMock()
    attach_channel_state_bus(host)
    host.channel_state_bus.publish = MagicMock()

    host._on_history_changed(None)

    host.load_history.assert_called_once()
    host.channel_state_bus.publish.assert_not_called()


# ---------------------------------------------------------------------------
# 3 + 4. PLAY-9 — close-branch finalise of a movie/single-episode last sample.
# ---------------------------------------------------------------------------

class _SyncExecutor:
    """Executor stand-in that runs the submitted job inline (no real thread)."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)
        return MagicMock()


def _make_close_host(db, pos_s: float, dur_s: float):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)
    host.executor = _SyncExecutor()
    host.player_manager = MagicMock()
    host.player_manager.active_keys.return_value = []  # window closed
    host._watch_checkpoint_timer = MagicMock()
    host._watch_tracking = {
        "k1": {
            "content_id": "c1",
            "media_type": "movie",
            "played_via": "manual",
            "last_sample": (pos_s, dur_s),
        }
    }
    return host


def test_close_branch_promotes_complete_watch(db, qapp):
    """A >=90% last sample is finalised as completed even though mpv already exited."""
    _seed_channel(db, "c1", "movie")
    host = _make_close_host(db, 2850, 3000)  # 95%

    host._watch_checkpoint_tick()

    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id("c1")
        assert bool(ch.watch_completed) is True
        assert ch.watch_progress == 0
    assert "k1" not in host._watch_tracking, "closed window must be dropped from tracking"


def test_close_branch_persists_partial_resume_point(db, qapp):
    """A partial last sample is persisted as a resume point, not marked complete."""
    _seed_channel(db, "c1", "movie")
    host = _make_close_host(db, 900, 3000)  # 30%

    host._watch_checkpoint_tick()

    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id("c1")
        assert ch.watch_progress == int(900)
        assert bool(ch.watch_completed) is False
