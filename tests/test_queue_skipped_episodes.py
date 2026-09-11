"""QUEUE-1: an episode the player skipped is not marked watched, and closing
the player mid-episode keeps its position.

Owner's real run (2026-09-10, "Police Squad!" S01E01 with E02-E06 queued): E01
played to the end; the source then refused the next connection (HTTP 500 x5),
so mpv FAILED TO OPEN E02, E03 and E04 and advanced past each within seconds —
"advanced past" was read as "played to the end", so all three were ticked
watched despite never producing a frame. E05 opened and played ~30 minutes,
then the stream died ("Some errors happened") and mpv exited; the close branch
force-completed it, replacing its 30-minute position with 100%.

Covered:
1. The advance-past loop in ``_bg_capture_watch`` no longer finalises an
   episode with zero recorded progress (``require_seen=True``).
2. Closing the player mid-episode (``PlayerManager.last_exit_reason`` != "End
   of file") keeps the per-tick-written position instead of force-completing.
3. The playlist genuinely running out ("End of file") still completes the
   last episode.
4. A stream-error exit ("Some errors happened" — the owner's E05) is treated
   the same as any other mid-episode close: the position is kept.
5. Answering "No" to the queue-end prompt only takes back what the queue
   itself marked — an in-progress or never-played episode is left alone.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from metatv.core.database import EpisodeDB
from metatv.core.repositories import RepositoryFactory
from tests.conftest import wire_episode_watch_signal


def _seed_episode(db, ep_id: str, num: int) -> None:
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id,
            season_id="s1",
            series_id="ser1",
            provider_id="p1",
            episode_id=str(num),
            episode_num=num,
            season_num=1,
            title=f"Episode {num}",
            stream_url=f"http://example.com/{ep_id}.ts",
        ))


def _episode_fields(db, ep_id: str) -> dict:
    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id(ep_id)
        if ep is None:
            return {}
        return {
            "watch_completed": bool(ep.watch_completed),
            "watch_percent": ep.watch_percent,
            "watch_progress": ep.watch_progress,
            "last_played": ep.last_played,
            "last_played_via": ep.last_played_via,
        }


def _streaming_host(db):
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    wire_episode_watch_signal(host)
    host.db = db
    host.executor = SimpleNamespace(submit=lambda fn, *a, **k: fn(*a, **k))
    host.config = SimpleNamespace(watch_complete_threshold=0.9, prompt_after_autoplay=True)
    host.player_manager = MagicMock()
    host._watch_tracking = {}
    return host


def _prompt_host(db):
    from metatv.gui.queue_end_prompt import _QueueEndPromptMixin
    host = _QueueEndPromptMixin.__new__(_QueueEndPromptMixin)
    wire_episode_watch_signal(host)
    host.db = db
    host.executor = SimpleNamespace(submit=lambda fn, *a, **k: fn(*a, **k))
    return host


# ---------------------------------------------------------------------------
# 1. A skipped (never-played) episode is not marked watched on advance-past.
# ---------------------------------------------------------------------------

def test_an_episode_the_player_skipped_is_not_marked_watched(db):
    _seed_episode(db, "e1", 1)
    _seed_episode(db, "e2", 2)
    _seed_episode(db, "e3", 3)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress(
            "e1", 750, 1500, 0.9, "manual"
        )

    host = _streaming_host(db)
    host._watch_tracking["k"] = {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": "e1"}, {"content_id": "e2"}, {"content_id": "e3"}],
        "last_seen_pos": 0,
    }
    host.player_manager.get_properties.return_value = {
        "time-pos": 5.0, "duration": 1500.0, "playlist-pos": 2,
    }

    host._bg_capture_watch("k", dict(host._watch_tracking["k"]))

    e1 = _episode_fields(db, "e1")
    e2 = _episode_fields(db, "e2")
    e3 = _episode_fields(db, "e3")
    assert e1["watch_completed"] is True, "e1 had real progress — advancing past it completes it"
    assert e2["watch_completed"] is False, "e2 was never actually played"
    assert e2["watch_percent"] == 0
    assert e2["last_played"] is None
    assert e3["watch_progress"] == 5, "e3 is the current episode — its live position is recorded"


# ---------------------------------------------------------------------------
# 2-4. The close branch keeps the position unless the playlist ran out.
# ---------------------------------------------------------------------------

def test_closing_the_player_mid_episode_keeps_its_position(db):
    _seed_episode(db, "e1", 1)
    _seed_episode(db, "e2", 2)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress(
            "e2", 900, 1500, 0.9, "queue"
        )

    host = _streaming_host(db)
    host._watch_tracking["k"] = {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": "e1"}, {"content_id": "e2"}],
        "last_seen_pos": 1,
    }
    host.player_manager.active_keys.return_value = []
    host.player_manager.last_exit_reason.return_value = "Quit"
    host._watch_checkpoint_timer = MagicMock()
    host._queue_end_detected = MagicMock()

    host._watch_checkpoint_tick()

    e2 = _episode_fields(db, "e2")
    assert e2["watch_progress"] == 900, "closing the window must not lose the position"
    assert e2["watch_completed"] is False


def test_the_playlist_ending_completes_the_last_episode(db):
    _seed_episode(db, "e1", 1)
    _seed_episode(db, "e2", 2)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress(
            "e2", 900, 1500, 0.9, "queue"
        )

    host = _streaming_host(db)
    host._watch_tracking["k"] = {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": "e1"}, {"content_id": "e2"}],
        "last_seen_pos": 1,
    }
    host.player_manager.active_keys.return_value = []
    host.player_manager.last_exit_reason.return_value = "End of file"
    host._watch_checkpoint_timer = MagicMock()
    host._queue_end_detected = MagicMock()

    host._watch_checkpoint_tick()

    e2 = _episode_fields(db, "e2")
    assert e2["watch_completed"] is True, "the playlist genuinely ran out — the last episode finished"


def test_a_stream_error_exit_keeps_the_position_too(db):
    """The owner's E05: a mid-episode stream error ("Some errors happened") must
    not be treated as the episode finishing — same as a manual Quit."""
    _seed_episode(db, "e1", 1)
    _seed_episode(db, "e2", 2)
    with db.session_scope() as session:
        RepositoryFactory(session).episodes.record_watch_progress(
            "e2", 900, 1500, 0.9, "queue"
        )

    host = _streaming_host(db)
    host._watch_tracking["k"] = {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": "e1"}, {"content_id": "e2"}],
        "last_seen_pos": 1,
    }
    host.player_manager.active_keys.return_value = []
    host.player_manager.last_exit_reason.return_value = "Some errors happened"
    host._watch_checkpoint_timer = MagicMock()
    host._queue_end_detected = MagicMock()

    host._watch_checkpoint_tick()

    e2 = _episode_fields(db, "e2")
    assert e2["watch_progress"] == 900
    assert e2["watch_completed"] is False


# ---------------------------------------------------------------------------
# 5. "No" only takes back what the queue itself marked.
# ---------------------------------------------------------------------------

def test_no_takes_back_only_what_the_queue_marked(db):
    _seed_episode(db, "e2", 2)
    _seed_episode(db, "e3", 3)
    _seed_episode(db, "e4", 4)
    with db.session_scope() as session:
        repos = RepositoryFactory(session)
        repos.episodes.record_watch_progress("e2", 1.0, 1.0, 0.9, "queue")     # completed via queue
        repos.episodes.record_watch_progress("e3", 900, 1500, 0.9, "queue")    # in progress
        # e4 is never touched.

    host = _prompt_host(db)
    host._bg_unmark_queue_episodes(["e2", "e3", "e4"])

    e2 = _episode_fields(db, "e2")
    e3 = _episode_fields(db, "e3")
    e4 = _episode_fields(db, "e4")
    assert e2["watch_completed"] is False, "answering No must undo what the queue marked"
    assert e2["watch_percent"] == 0
    assert e3["watch_progress"] == 900, "an in-progress episode is not the queue's mark to take back"
    assert e3["watch_completed"] is False
    assert e4["watch_completed"] is False
    assert e4["watch_progress"] == 0
