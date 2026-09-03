"""HIST-1 (2026-09-03): a play never appeared in History.

Root cause: ``_record_play`` called ``self.load_history()`` synchronously,
immediately after submitting ``_bg_mark_played`` to the executor — the refresh
read the DB before the write committed (owner's log: refresh at 01:58:59.3,
commit at 01:59:00.8). ``_WatchNotifier.history_changed``
(``metatv/gui/watch_capture.py``) closes that race: ``_bg_mark_played`` emits
it only AFTER its ``session_scope()`` block commits, and
``_on_history_changed`` (the main-thread slot) is what actually calls
``load_history()`` and republishes on ``channel_state_bus`` (so the details
pane's Resume button stops going stale after playback ends).

Covered here:
1. Ordering proof — ``_bg_mark_played`` emits ``history_changed`` only after
   its write commits (a recorder that queries the DB mid-callback sees the
   committed row).
2. ``_on_history_changed`` calls ``load_history()`` and republishes on
   ``channel_state_bus``.
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
