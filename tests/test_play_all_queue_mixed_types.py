"""A Play-All queue of MOVIES records its watch progress (ledger D54).

The queued branch of ``_bg_capture_watch`` and ``_bg_finalise_episode`` always
wrote through ``repos.episodes``, so a movie or channel in a Play-All queue was
looked up in the episode table, not found, and silently never recorded. Each
queue entry now carries its own ``media_type`` and the write goes to the
matching store.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from metatv.core.repositories import RepositoryFactory
from tests.conftest import make_channel, wire_episode_watch_signal


def _seed_movies(db, n: int) -> list[str]:
    with db.session_scope() as session:
        return [make_channel(session, f"Movie {i}", media_type="movie").id
                for i in range(n)]


def _movie_fields(db, channel_id: str) -> dict:
    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id(channel_id)
        return {"watch_completed": bool(ch.watch_completed),
                "watch_progress": ch.watch_progress}


def _host(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    wire_episode_watch_signal(host)
    host.db = db
    host.executor = SimpleNamespace(submit=lambda fn, *a, **k: fn(*a, **k))
    host.config = SimpleNamespace(watch_complete_threshold=0.9, prompt_after_autoplay=False)
    host.player_manager = MagicMock()
    host._watch_tracking = {}
    return host


def _queue_entry(ids):
    return {
        "media_type": "movie",
        "played_via": "manual",
        "queue": [{"content_id": i, "media_type": "movie"} for i in ids],
        "last_seen_pos": 0,
    }


def test_the_playing_movie_in_a_queue_records_its_position(db):
    m0, m1 = _seed_movies(db, 2)
    host = _host(db)
    host._watch_tracking["k"] = _queue_entry([m0, m1])
    host.player_manager.get_properties.return_value = {
        "time-pos": 600.0, "duration": 6000.0, "playlist-pos": 0,
    }

    host._bg_capture_watch("k", dict(host._watch_tracking["k"]))

    assert _movie_fields(db, m0)["watch_progress"] == 600


def test_a_movie_the_queue_advanced_past_is_completed(db):
    m0, m1 = _seed_movies(db, 2)
    host = _host(db)
    host._watch_tracking["k"] = _queue_entry([m0, m1])
    # Tick 1: movie 0 is playing — its position is written.
    host.player_manager.get_properties.return_value = {
        "time-pos": 5900.0, "duration": 6000.0, "playlist-pos": 0,
    }
    host._bg_capture_watch("k", dict(host._watch_tracking["k"]))
    # Tick 2: mpv moved on to movie 1, so movie 0 played to the end.
    host.player_manager.get_properties.return_value = {
        "time-pos": 10.0, "duration": 5000.0, "playlist-pos": 1,
    }
    host._bg_capture_watch("k", dict(host._watch_tracking["k"]))

    assert _movie_fields(db, m0)["watch_completed"] is True
    assert _movie_fields(db, m1)["watch_progress"] == 10


def test_the_playlist_ending_completes_the_last_movie(db):
    (m0,) = _seed_movies(db, 1)
    host = _host(db)
    host._watch_tracking["k"] = _queue_entry([m0])
    host.player_manager.get_properties.return_value = {
        "time-pos": 3000.0, "duration": 6000.0, "playlist-pos": 0,
    }
    host._bg_capture_watch("k", dict(host._watch_tracking["k"]))
    # The player window is gone and mpv reported the playlist ran out.
    host.player_manager.active_keys.return_value = []
    host.player_manager.last_exit_reason.return_value = "End of file"
    host._watch_checkpoint_timer = MagicMock()

    host._watch_checkpoint_tick()

    assert _movie_fields(db, m0)["watch_completed"] is True
