"""Watch-progress capture wiring (Slice 1b).

The engine (Slice 1a) records progress; this slice samples mpv position at a
periodic checkpoint and routes it through the chokepoint, per instance (so it
stays correct under Split Streams). Tested here: the key resolver, registration
in _bg_mark_played (movies only), the checkpoint tick (submit tracked / prune
dead), and the off-thread capture actually persisting progress.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ChannelDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'cap.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed(db, ch_id, media_type):
    s = db.get_session()
    try:
        s.add(ChannelDB(id=ch_id, source_id=ch_id, provider_id="p",
                        name=ch_id, media_type=media_type))
        s.commit()
    finally:
        s.close()


# ── PlayerManager.resolve_key ──────────────────────────────────────────────────

def _pm(split: bool):
    from metatv.core.player_manager import PlayerManager
    pm = PlayerManager.__new__(PlayerManager)
    pm.config = MagicMock(split_streams_by_source=split)
    return pm


def test_resolve_key_shared_when_split_off():
    assert _pm(False).resolve_key("provA") == "__shared__"


def test_resolve_key_provider_when_split_on():
    assert _pm(True).resolve_key("provA") == "provA"


def test_resolve_key_force_new_window_overrides_split_off():
    assert _pm(False).resolve_key("provA", force_new_window=True) == "provA"


# ── _StreamingMixin capture wiring ─────────────────────────────────────────────

def _host(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host._watch_tracking = {}
    return host


def test_mark_played_registers_movie_tracking(db):
    _seed(db, "m1", "movie")
    host = _host(db)
    host._bg_mark_played("m1", key="__shared__")
    assert host._watch_tracking["__shared__"]["content_id"] == "m1"
    assert host._watch_tracking["__shared__"]["media_type"] == "movie"


def test_mark_played_clears_tracking_for_non_movie(db):
    """Switching a window from a movie to a live channel must stop capturing the movie."""
    _seed(db, "live1", "live")
    host = _host(db)
    host._watch_tracking = {"__shared__": {"content_id": "old_movie", "media_type": "movie"}}
    host._bg_mark_played("live1", key="__shared__")
    assert "__shared__" not in host._watch_tracking


def test_capture_persists_progress_and_completion(db):
    _seed(db, "m1", "movie")
    host = _host(db)
    host.config = MagicMock(watch_complete_threshold=0.9)
    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {"time-pos": 2900, "duration": 3000}  # 96%

    host._bg_capture_watch("__shared__", {"content_id": "m1", "media_type": "movie",
                                          "played_via": "manual"})

    s = db.get_session()
    try:
        ch = RepositoryFactory(s).channels.get_by_id("m1")
        assert bool(ch.watch_completed) is True
    finally:
        s.close()


def test_capture_skips_when_no_duration(db):
    """A live/unknown-duration read (duration None/0) must not write progress."""
    _seed(db, "m1", "movie")
    host = _host(db)
    host.config = MagicMock(watch_complete_threshold=0.9)
    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {"time-pos": 100, "duration": None}

    host._bg_capture_watch("__shared__", {"content_id": "m1", "media_type": "movie"})

    s = db.get_session()
    try:
        ch = RepositoryFactory(s).channels.get_by_id("m1")
        assert ch.watch_progress == 0  # untouched
    finally:
        s.close()


def test_checkpoint_submits_tracked_active_keys_and_prunes_dead(db):
    host = _host(db)
    host.player_manager = MagicMock()
    host.player_manager.active_keys.return_value = ["k_live"]
    host.executor = MagicMock()
    host._watch_checkpoint_timer = MagicMock()
    host._watch_tracking = {
        "k_live": {"content_id": "m1", "media_type": "movie"},
        "k_dead": {"content_id": "m2", "media_type": "movie"},  # window closed
    }

    host._watch_checkpoint_tick()

    assert "k_dead" not in host._watch_tracking, "tracking for closed windows is pruned"
    assert "k_live" in host._watch_tracking
    host.executor.submit.assert_called_once()
    # submitted (_bg_capture_watch, "k_live", info)
    assert host.executor.submit.call_args[0][1] == "k_live"


def test_checkpoint_stops_timer_when_nothing_playing(db):
    host = _host(db)
    host.player_manager = MagicMock()
    host.player_manager.active_keys.return_value = []
    host.executor = MagicMock()
    host._watch_checkpoint_timer = MagicMock()
    host._watch_tracking = {"k_dead": {"content_id": "m1", "media_type": "movie"}}

    host._watch_checkpoint_tick()

    host._watch_checkpoint_timer.stop.assert_called_once()
    host.executor.submit.assert_not_called()
