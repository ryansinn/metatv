"""Behavioral tests for Slice 3b-1 — follow the queue: track auto-advanced episodes.

Covered behaviors:
1. play_episode with queued episodes stores a 'queue' list in _watch_tracking, not
   a flat 'content_id' — so the checkpoint can map playlist-pos to the right episode.
2. _bg_capture_watch (queued branch) records progress against the episode at the
   *current* playlist-pos, not always episode-0.
3. Auto-advancing (playlist-pos 0→1→2) finalises each passed episode as watch_completed
   and records last_played_via='queue' for auto-advanced episodes.
4. The started episode (index 0) retains last_played_via='manual'.
5. On instance close (player window disappears between ticks), _watch_checkpoint_tick
   finalises the current episode so progress is not lost.
6. Single-episode plays use the flat-dict branch (backward-compat, unchanged).
7. last_seen_pos in the live tracking dict advances as the playlist moves.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'queue_watch.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_episodes(db, ep_ids: list[str]) -> None:
    """Insert minimal EpisodeDB rows for a 3-episode series."""
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        for i, ep_id in enumerate(ep_ids, start=1):
            session.add(EpisodeDB(
                id=ep_id,
                series_id="ser1",
                season_id="seas1",
                provider_id="p1",
                episode_id=f"ep_orig_{i}",
                season_num=1,
                episode_num=i,
                title=f"Episode {i}",
            ))


def _read_episode_fields(db, ep_id: str) -> dict:
    """Return a plain dict of the key watch fields for an episode (safe outside session)."""
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_by_id(ep_id)
        if ep is None:
            return {}
        return {
            "watch_completed": bool(ep.watch_completed),
            "watch_progress": ep.watch_progress,
            "last_played_via": ep.last_played_via,
            "is_watched": bool(ep.is_watched),
        }


# ---------------------------------------------------------------------------
# 1. play_episode stores queue list in _watch_tracking
# ---------------------------------------------------------------------------

def _make_series_host_queued(db):
    """Build a _SeriesMixin host for queued-episode play tests."""
    from metatv.gui.main_window_series import _SeriesMixin
    host = _SeriesMixin.__new__(_SeriesMixin)
    host.db = db
    host.config = MagicMock(
        autoplay_season_episodes=True,
        watch_complete_threshold=0.9,
        split_streams_by_source=False,
    )
    host.player_manager = MagicMock()
    host.player_manager.resolve_key.return_value = "__shared__"
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif_1"
    host.executor = MagicMock()
    host._watch_tracking = {}
    host.load_history = MagicMock()
    host.load_favorites = MagicMock()
    host.launch_player_for_episode = MagicMock()
    host._start_watch_capture = MagicMock()
    return host


def _make_episode_dto(ep_id, ep_num, season_id="seas1"):
    from metatv.core.repositories.dtos import EpisodeDTO
    return EpisodeDTO(
        id=ep_id,
        episode_num=ep_num,
        season_num=1,
        title=f"Episode {ep_num}",
        series_name="Test Series",
        stream_url=f"http://example.com/ep{ep_num}.ts",
        duration="0:45:00",
        is_watched=False,
        rating=None,
        series_id="ser_src_1",
        provider_id="p1",
        season_id=season_id,
        watch_progress=0,
        watch_completed=False,
    )


def _seed_series_channel_and_episodes(db, ep_ids):
    """Seed parent channel + episodes so play_episode DB lookups succeed."""
    from metatv.core.database import ChannelDB, EpisodeDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ch_ser",
            source_id="ser_src_1",
            provider_id="p1",
            name="Test Series",
            media_type="series",
        ))
        for i, ep_id in enumerate(ep_ids, start=1):
            session.add(EpisodeDB(
                id=ep_id,
                series_id="ser_src_1",
                season_id="seas1",
                provider_id="p1",
                episode_id=f"ep_orig_{i}",
                season_num=1,
                episode_num=i,
                title=f"Episode {i}",
                stream_url=f"http://example.com/ep{i}.ts",
            ))


def test_play_episode_with_queue_stores_queue_list(db):
    """When episodes are queued, _watch_tracking[key] contains a 'queue' list."""
    _seed_series_channel_and_episodes(db, ["e1", "e2", "e3"])
    host = _make_series_host_queued(db)

    # Manually call play_episode with autoplay enabled — it reads from DB so we
    # need the DTOs to match what's in the session.  Use a custom side-effect
    # on get_episodes_dto_by_season to return our test DTOs.
    ep1 = _make_episode_dto("e1", 1)
    ep2 = _make_episode_dto("e2", 2)
    ep3 = _make_episode_dto("e3", 3)

    # Patch get_episodes_dto_by_season to return all 3 episodes.
    from unittest.mock import patch as _patch
    import metatv.core.repositories.episode as ep_repo_mod
    with _patch.object(
        ep_repo_mod.EpisodeRepository,
        "get_episodes_dto_by_season",
        return_value=[ep1, ep2, ep3],
    ):
        host.play_episode(ep1)

    tracking = host._watch_tracking
    assert "__shared__" in tracking, "tracking entry missing"
    info = tracking["__shared__"]
    assert "queue" in info, "queue list missing from tracking entry"
    queue = info["queue"]
    assert len(queue) == 3, f"expected 3 items in queue, got {len(queue)}"
    assert queue[0]["content_id"] == "e1"
    assert queue[1]["content_id"] == "e2"
    assert queue[2]["content_id"] == "e3"


def test_play_episode_queue_tracking_has_last_seen_pos(db):
    """Queue tracking entry includes last_seen_pos=0 (no advances yet)."""
    _seed_series_channel_and_episodes(db, ["e1", "e2"])
    host = _make_series_host_queued(db)

    ep1 = _make_episode_dto("e1", 1)
    ep2 = _make_episode_dto("e2", 2)

    import metatv.core.repositories.episode as ep_repo_mod
    with patch.object(
        ep_repo_mod.EpisodeRepository,
        "get_episodes_dto_by_season",
        return_value=[ep1, ep2],
    ):
        host.play_episode(ep1)

    info = host._watch_tracking["__shared__"]
    assert info.get("last_seen_pos") == 0
    assert info.get("played_via") == "manual"


def test_play_episode_single_no_queue_uses_flat_dict(db):
    """Single-episode play (no queue) keeps the flat-dict tracking entry."""
    _seed_series_channel_and_episodes(db, ["e1"])
    host = _make_series_host_queued(db)
    host.config.autoplay_season_episodes = False

    ep1 = _make_episode_dto("e1", 1)

    import metatv.core.repositories.episode as ep_repo_mod
    with patch.object(
        ep_repo_mod.EpisodeRepository,
        "get_episodes_dto_by_season",
        return_value=[ep1],
    ):
        host.play_episode(ep1)

    info = host._watch_tracking["__shared__"]
    assert "queue" not in info, "flat-dict branch should not have 'queue'"
    assert info["content_id"] == "e1"
    assert info["media_type"] == "episode"


# ---------------------------------------------------------------------------
# 2 + 3 + 4. _bg_capture_watch queued branch: progress against current pos,
#             finalise advanced, correct played_via values
# ---------------------------------------------------------------------------

def _make_streaming_host(db):
    """Build a _StreamingMixin host for capture-watch tests."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)
    host._watch_tracking = {}
    return host


def _make_queue_info(ep_ids: list[str], last_seen_pos: int = 0) -> dict:
    """Build the queue tracking entry as play_episode would produce it."""
    return {
        "media_type": "episode",
        "played_via": "manual",
        "queue": [{"content_id": eid} for eid in ep_ids],
        "last_seen_pos": last_seen_pos,
    }


def test_capture_records_progress_against_current_playlist_pos(db):
    """When playlist-pos=1, progress goes to e2 (not e1)."""
    _seed_episodes(db, ["e1", "e2", "e3"])
    host = _make_streaming_host(db)
    host._watch_tracking["k"] = _make_queue_info(["e1", "e2", "e3"], last_seen_pos=0)

    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {
        "time-pos": 300.0,
        "duration": 1500.0,
        "playlist-pos": 1,   # mpv is on E2
    }

    info_snapshot = dict(host._watch_tracking["k"])
    info_snapshot["queue"] = list(info_snapshot["queue"])
    host._bg_capture_watch("k", info_snapshot)

    ep2 = _read_episode_fields(db, "e2")
    ep1 = _read_episode_fields(db, "e1")
    # E2 should have progress (300s, 20%)
    assert ep2["watch_progress"] == 300, f"e2 progress={ep2['watch_progress']}"
    # E1 was auto-advanced past (pos 0 → 1), so it should be completed
    assert ep1["watch_completed"] is True, "e1 should be finalised when advanced past"


def test_capture_finalises_auto_advanced_episodes(db):
    """Advancing from pos 0 to pos 2 finalises e1 and e2 as watch_completed=True."""
    _seed_episodes(db, ["e1", "e2", "e3"])
    host = _make_streaming_host(db)
    host._watch_tracking["k"] = _make_queue_info(["e1", "e2", "e3"], last_seen_pos=0)

    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {
        "time-pos": 600.0,
        "duration": 2700.0,
        "playlist-pos": 2,   # mpv jumped two episodes (e.g. skipped ahead)
    }

    info_snapshot = dict(host._watch_tracking["k"])
    info_snapshot["queue"] = list(info_snapshot["queue"])
    host._bg_capture_watch("k", info_snapshot)

    ep1 = _read_episode_fields(db, "e1")
    ep2 = _read_episode_fields(db, "e2")
    ep3 = _read_episode_fields(db, "e3")
    assert ep1["watch_completed"] is True, "e1 should be finalised"
    assert ep2["watch_completed"] is True, "e2 should be finalised"
    assert ep3["watch_completed"] is False, "e3 is still in progress, not completed"


def test_capture_played_via_manual_for_first_episode(db):
    """The started episode (index 0 → index 1 advance) is finalised as 'manual'."""
    _seed_episodes(db, ["e1", "e2"])
    host = _make_streaming_host(db)
    host._watch_tracking["k"] = _make_queue_info(["e1", "e2"], last_seen_pos=0)

    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {
        "time-pos": 100.0,
        "duration": 1500.0,
        "playlist-pos": 1,   # advanced past e1
    }

    info_snapshot = dict(host._watch_tracking["k"])
    info_snapshot["queue"] = list(info_snapshot["queue"])
    host._bg_capture_watch("k", info_snapshot)

    ep1 = _read_episode_fields(db, "e1")
    assert ep1["last_played_via"] == "manual", (
        f"started episode should be 'manual', got {ep1['last_played_via']!r}"
    )


def test_capture_played_via_queue_for_auto_advanced(db):
    """Episodes auto-advanced past index 1+ are recorded as last_played_via='queue'."""
    _seed_episodes(db, ["e1", "e2", "e3"])
    host = _make_streaming_host(db)
    # Start at pos 1 already (e1 was already finalised last tick); e2 gets advanced.
    host._watch_tracking["k"] = _make_queue_info(["e1", "e2", "e3"], last_seen_pos=1)

    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {
        "time-pos": 50.0,
        "duration": 1500.0,
        "playlist-pos": 2,   # advanced past e2
    }

    info_snapshot = dict(host._watch_tracking["k"])
    info_snapshot["queue"] = list(info_snapshot["queue"])
    info_snapshot["last_seen_pos"] = 1  # mimic the live value
    host._bg_capture_watch("k", info_snapshot)

    ep2 = _read_episode_fields(db, "e2")
    assert ep2["last_played_via"] == "queue", (
        f"auto-advanced episode should be 'queue', got {ep2['last_played_via']!r}"
    )


def test_capture_current_episode_played_via_queue_when_not_first(db):
    """Current episode at index > 0 gets last_played_via='queue' for live progress."""
    _seed_episodes(db, ["e1", "e2", "e3"])
    host = _make_streaming_host(db)
    # Already past e1 (last_seen_pos=1), no new advances this tick.
    host._watch_tracking["k"] = _make_queue_info(["e1", "e2", "e3"], last_seen_pos=1)

    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {
        "time-pos": 200.0,
        "duration": 1500.0,
        "playlist-pos": 1,   # still on e2, no advance
    }

    info_snapshot = dict(host._watch_tracking["k"])
    info_snapshot["queue"] = list(info_snapshot["queue"])
    info_snapshot["last_seen_pos"] = 1
    host._bg_capture_watch("k", info_snapshot)

    ep2 = _read_episode_fields(db, "e2")
    assert ep2["watch_progress"] == 200, f"e2 progress should be 200, got {ep2['watch_progress']}"
    assert ep2["last_played_via"] == "queue"


# ---------------------------------------------------------------------------
# 5. On-stop finalization: window closes before checkpoint
# ---------------------------------------------------------------------------

def test_checkpoint_tick_finalises_current_on_window_close(db):
    """When a queued window disappears, _watch_checkpoint_tick submits _bg_finalise_episode."""
    _seed_episodes(db, ["e1", "e2"])
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)
    host._watch_checkpoint_timer = MagicMock()
    host.executor = MagicMock()

    # Window "k" was tracking a queue at last_seen_pos=1 (e2 was playing)
    host._watch_tracking = {
        "k": {
            "media_type": "episode",
            "played_via": "manual",
            "queue": [{"content_id": "e1"}, {"content_id": "e2"}],
            "last_seen_pos": 1,
        }
    }

    # player_manager reports no active keys (window closed)
    host.player_manager = MagicMock()
    host.player_manager.active_keys.return_value = []

    host._watch_checkpoint_tick()

    # The executor must have been asked to finalise e2 (the episode at last_seen_pos=1)
    assert host.executor.submit.called, "executor.submit not called"
    call_args = host.executor.submit.call_args_list
    finalise_calls = [c for c in call_args if c[0][0].__name__ == "_bg_finalise_episode"]
    assert finalise_calls, "no _bg_finalise_episode call found"
    # Check the content_id and played_via
    submitted_ep_id = finalise_calls[0][0][1]
    submitted_via = finalise_calls[0][0][2]
    assert submitted_ep_id == "e2", f"expected e2, got {submitted_ep_id}"
    assert submitted_via == "queue", f"expected 'queue', got {submitted_via}"

    # The tracking entry should be removed
    assert "k" not in host._watch_tracking


# ---------------------------------------------------------------------------
# 6. last_seen_pos advances in the live dict
# ---------------------------------------------------------------------------

def test_update_last_seen_pos_advances_in_live_dict(db):
    """_update_last_seen_pos sets last_seen_pos on the live tracking entry."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host._watch_tracking = {
        "k": {
            "media_type": "episode",
            "queue": [{"content_id": "e1"}, {"content_id": "e2"}],
            "last_seen_pos": 0,
        }
    }

    host._update_last_seen_pos("k", 1)

    assert host._watch_tracking["k"]["last_seen_pos"] == 1


def test_update_last_seen_pos_noop_for_flat_entry():
    """_update_last_seen_pos is a no-op for non-queue (flat-dict) tracking entries."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host._watch_tracking = {
        "k": {"content_id": "m1", "media_type": "movie"}
    }
    # Should not raise and should not add last_seen_pos
    host._update_last_seen_pos("k", 5)
    assert "last_seen_pos" not in host._watch_tracking["k"]


# ---------------------------------------------------------------------------
# 7. _bg_finalise_episode marks episode 100% completed
# ---------------------------------------------------------------------------

def test_bg_finalise_episode_marks_completed(db):
    """_bg_finalise_episode sets watch_completed=True on the episode."""
    _seed_episodes(db, ["ef"])
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)

    host._bg_finalise_episode("ef", "queue")

    ep = _read_episode_fields(db, "ef")
    assert ep["watch_completed"] is True
    assert ep["last_played_via"] == "queue"


def test_bg_finalise_episode_manual_via(db):
    """_bg_finalise_episode records last_played_via='manual' when via='manual'."""
    _seed_episodes(db, ["ef2"])
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)

    host._bg_finalise_episode("ef2", "manual")

    ep = _read_episode_fields(db, "ef2")
    assert ep["last_played_via"] == "manual"
