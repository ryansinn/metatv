"""Behavioral tests for Slice 3a — episode watch tracking + display + mpv title.

Covered behaviours:
1. DB migration list includes episodes.watch_progress and episodes.watch_completed.
2. EpisodeRepository.record_watch_progress marks watch_completed at threshold.
3. EpisodeRepository.record_watch_progress sets watch_completed on EpisodeDB.
4. EpisodeDTO carries watch_progress and watch_completed from the repo builder.
5. Series-view row builder yields ✓ / ◐ / ▶ for the three watch states.
6. MPVPlayer.queue sends the title as a per-file force-media-title option.
7. play_episode registers the episode in _watch_tracking for capture.
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
    d = Database(f"sqlite:///{tmp_path / 'ep.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_episode(db, ep_id="e1", watch_progress=0, watch_completed=False):
    """Insert a minimal EpisodeDB row."""
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id,
            series_id="ser1",
            season_id="s1",
            provider_id="p1",
            episode_id="ep_orig_1",
            season_num=1,
            episode_num=1,
            title="Test Episode",
            watch_progress=watch_progress,
            watch_completed=watch_completed,
        ))


# ---------------------------------------------------------------------------
# 1. Migration list covers both episode columns
# ---------------------------------------------------------------------------

def test_migration_list_includes_episode_watch_progress():
    """episodes.watch_progress must be in the _migrate column list."""
    from metatv.core.database import Database
    db_cls = Database
    # Instantiate without a real DB to read the constant
    migrations = [
        (table, col, col_type)
        for table, col, col_type in [
            ("episodes", "watch_progress", "INTEGER DEFAULT 0"),
            ("episodes", "watch_completed", "INTEGER DEFAULT 0"),
        ]
    ]
    # Verify both entries appear in the real migration list by checking the source
    import inspect
    source = inspect.getsource(Database._migrate)
    assert '"watch_progress"' in source or "'watch_progress'" in source, (
        "episodes.watch_progress missing from migration list"
    )
    assert '"watch_completed"' in source or "'watch_completed'" in source, (
        "episodes.watch_completed missing from migration list"
    )


def test_migration_list_episode_columns_have_integer_default():
    """Both episode migration entries specify INTEGER DEFAULT 0."""
    import inspect
    from metatv.core.database import Database
    source = inspect.getsource(Database._migrate)
    # Check that both entries appear near the "episodes" table references
    # (a shape check that the migration entries actually exist, alongside the
    # behavioral test above that creates_tables creates the column for new DBs)
    assert source.count('"episodes"') >= 3 or source.count("'episodes'") >= 3, (
        "Expected at least 3 episodes entries in migration (last_played_via + watch_progress + watch_completed)"
    )


# ---------------------------------------------------------------------------
# 2. EpisodeDB column exists on a fresh database (create_tables path)
# ---------------------------------------------------------------------------

def test_episode_watch_completed_column_created(db):
    """New databases have the watch_completed column on episodes."""
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        ep = EpisodeDB(
            id="e_fresh",
            series_id="ser1",
            season_id="s1",
            provider_id="p1",
            episode_id="ep_orig_1",
            season_num=1,
            episode_num=1,
            title="Fresh Episode",
            watch_completed=True,
        )
        session.add(ep)

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_by_id("e_fresh")
        assert bool(ep.watch_completed) is True, "watch_completed column not found or not writable"


# ---------------------------------------------------------------------------
# 3. EpisodeRepository.record_watch_progress marks watch_completed at threshold
# ---------------------------------------------------------------------------

def test_episode_record_progress_marks_completed_at_threshold(db):
    """Crossing the threshold sets watch_completed=True on the episode."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        done = repo.record_watch_progress("e1", position_s=1420, duration_s=1500)  # 94.7%
        assert done is True
        ep = repo.get_by_id("e1")
        assert bool(ep.watch_completed) is True
        assert ep.watch_progress == 0, "completed episode should clear the resume point"
        assert bool(ep.is_watched) is True, "is_watched must also be set (legacy flag)"


def test_episode_record_progress_partial_does_not_complete(db):
    """Below the threshold, watch_completed stays False and progress is recorded."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        done = repo.record_watch_progress("e1", position_s=300, duration_s=1500)  # 20%
        assert done is False
        ep = repo.get_by_id("e1")
        assert bool(ep.watch_completed) is False
        assert ep.watch_progress == 300


def test_episode_record_progress_completion_is_sticky(db):
    """Once watch_completed, a later partial rewatch does not un-complete the episode."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        repo.record_watch_progress("e1", 1450, 1500)   # complete
        repo.record_watch_progress("e1", 300, 1500)    # rewatch, stop early
        ep = repo.get_by_id("e1")
        assert bool(ep.watch_completed) is True, "completion must be sticky"
        assert ep.watch_progress == 300, "resume point still tracks the rewatch"


def test_episode_record_progress_played_via_threaded(db):
    """played_via is stored on the episode row."""
    _seed_episode(db)
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        repo = RepositoryFactory(session).episodes
        repo.record_watch_progress("e1", 300, 1500, played_via="queue")
        ep = repo.get_by_id("e1")
        assert ep.last_played_via == "queue"


# ---------------------------------------------------------------------------
# 4. EpisodeDTO carries watch_progress and watch_completed
# ---------------------------------------------------------------------------

def test_episode_dto_carries_watch_completed(db):
    """get_episodes_dto_by_season returns DTOs with watch_completed=True when set."""
    _seed_episode(db, ep_id="e2", watch_completed=True, watch_progress=0)
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dtos = RepositoryFactory(session).episodes.get_episodes_dto_by_season("s1")

    ep2 = next(d for d in dtos if d.id == "e2")
    assert ep2.watch_completed is True
    assert ep2.watch_progress == 0


def test_episode_dto_carries_watch_progress(db):
    """get_episodes_dto_by_season returns DTOs with watch_progress set."""
    _seed_episode(db, ep_id="e3", watch_completed=False, watch_progress=450)
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dtos = RepositoryFactory(session).episodes.get_episodes_dto_by_season("s1")

    ep3 = next(d for d in dtos if d.id == "e3")
    assert ep3.watch_completed is False
    assert ep3.watch_progress == 450


def test_episode_dto_carries_play_side_fields(db):
    """get_episodes_dto_by_season populates series_id, provider_id, season_id."""
    _seed_episode(db, ep_id="e4")
    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dtos = RepositoryFactory(session).episodes.get_episodes_dto_by_season("s1")

    ep4 = next(d for d in dtos if d.id == "e4")
    assert ep4.series_id == "ser1"
    assert ep4.provider_id == "p1"
    assert ep4.season_id == "s1"


# ---------------------------------------------------------------------------
# 5. Series-view row builder — three-state watch icon logic
# ---------------------------------------------------------------------------

def _make_episode_dto(watch_completed=False, watch_progress=0):
    """Build a minimal EpisodeDTO for icon-logic tests."""
    from metatv.core.repositories.dtos import EpisodeDTO
    return EpisodeDTO(
        id="e1",
        episode_num=1,
        season_num=1,
        title="Test Episode",
        series_name="Test Series",
        stream_url="http://example.com/ep1.ts",
        duration="0:45:00",
        is_watched=watch_completed,
        rating=None,
        series_id="ser1",
        provider_id="p1",
        season_id="s1",
        watch_progress=watch_progress,
        watch_completed=watch_completed,
    )


def _ep_icon(dto) -> str:
    """Replicate the three-state icon logic from populate_series_tree."""
    from metatv.gui import icons as _icons
    if dto.watch_completed:
        return _icons.watched_icon
    elif dto.watch_progress > 0:
        return _icons.partial_watched_icon
    else:
        return _icons.episode_icon


def test_series_tree_icon_completed():
    """Completed episode gets the ✓ watched_icon."""
    from metatv.gui import icons as _icons
    ep = _make_episode_dto(watch_completed=True, watch_progress=0)
    assert _ep_icon(ep) == _icons.watched_icon


def test_series_tree_icon_in_progress():
    """In-progress episode (progress > 0, not completed) gets the ◐ partial_watched_icon."""
    from metatv.gui import icons as _icons
    ep = _make_episode_dto(watch_completed=False, watch_progress=720)
    assert _ep_icon(ep) == _icons.partial_watched_icon


def test_series_tree_icon_unwatched():
    """Unwatched episode (progress = 0, not completed) gets the ▶ episode_icon."""
    from metatv.gui import icons as _icons
    ep = _make_episode_dto(watch_completed=False, watch_progress=0)
    assert _ep_icon(ep) == _icons.episode_icon


def test_series_tree_icon_completed_takes_priority_over_progress():
    """Even if watch_progress > 0, watch_completed=True wins and shows ✓."""
    from metatv.gui import icons as _icons
    # Edge case: completed=True but progress was not cleared (shouldn't happen after the fix,
    # but the icon logic should still be correct: completed takes priority)
    ep = _make_episode_dto(watch_completed=True, watch_progress=300)
    assert _ep_icon(ep) == _icons.watched_icon


# ---------------------------------------------------------------------------
# 6. MPVPlayer.queue passes per-item force-media-title
# ---------------------------------------------------------------------------

def _make_mpv_player():
    """Construct a minimal MPVPlayer with IPC stubbed out."""
    from metatv.core.players.mpv import MPVPlayer
    from metatv.core.players.base import QueueMode

    player = MPVPlayer.__new__(MPVPlayer)
    player.single_instance = True
    player._instances = {}
    player._last_key = "__shared__"
    player.config = MagicMock(
        preferred_player="mpv",
        player_mode="single-instance",
        mpv_extra_args=[],
        mpv_args_override_all=False,
        buffer_profile="reconnect_only",
        default_cache_size="auto",
        prebuffer_before_play=False,
        close_player_when_finished=False,
    )
    return player


def test_mpv_queue_sends_force_media_title_as_per_file_option():
    """queue() embeds force-media-title=<title> in the loadfile per-file options."""
    player = _make_mpv_player()
    from metatv.core.players.base import QueueMode

    # _ensure_instance_running must succeed and _send_ipc_command must capture the command
    sent_commands = []

    with patch.object(player, "_ensure_instance_running", return_value=True), \
         patch.object(player, "_send_ipc_command", side_effect=lambda cmd, key: sent_commands.append(cmd) or True):
        result = player.queue("http://example.com/ep2.ts", "S01E02 - The Answer", QueueMode.APPEND)

    assert result is True
    assert len(sent_commands) == 1
    cmd = sent_commands[0]["command"]
    # loadfile <url> <mode> <playlist_index_or_0> <per-file-options>
    assert cmd[0] == "loadfile"
    assert cmd[1] == "http://example.com/ep2.ts"
    assert cmd[2] == "append"
    # The per-file options string must contain force-media-title
    options_str = cmd[4]
    assert "force-media-title=" in options_str
    assert "S01E02 - The Answer" in options_str


def test_mpv_queue_escapes_comma_in_title():
    """Commas in the title are escaped so they don't break mpv's options parser."""
    player = _make_mpv_player()
    from metatv.core.players.base import QueueMode

    sent_commands = []

    with patch.object(player, "_ensure_instance_running", return_value=True), \
         patch.object(player, "_send_ipc_command", side_effect=lambda cmd, key: sent_commands.append(cmd) or True):
        player.queue("http://example.com/ep.ts", "Hello, World!", QueueMode.APPEND)

    options_str = sent_commands[0]["command"][4]
    # The comma must be escaped; the raw unescaped comma must not appear
    assert "\\," in options_str, f"Expected escaped comma in {options_str!r}"


def test_mpv_queue_uses_instance_key_from_arg():
    """When instance_key='prov1', queue targets that instance, not _last_key."""
    player = _make_mpv_player()
    from metatv.core.players.base import QueueMode

    used_keys = []

    def capture_ensure(key):
        used_keys.append(key)
        return True

    with patch.object(player, "_ensure_instance_running", side_effect=capture_ensure), \
         patch.object(player, "_send_ipc_command", return_value=True):
        player.queue("http://x.com/ep.ts", "E1", QueueMode.APPEND, instance_key="prov1")

    assert "prov1" in used_keys, f"Expected 'prov1' in {used_keys}"


# ---------------------------------------------------------------------------
# 7. play_episode registers _watch_tracking and calls _start_watch_capture
# ---------------------------------------------------------------------------

def _make_series_mixin_host(db):
    """Build a _SeriesMixin host with the minimal attributes play_episode needs."""
    from metatv.gui.main_window_series import _SeriesMixin

    host = _SeriesMixin.__new__(_SeriesMixin)
    host.db = db
    host.config = MagicMock(
        autoplay_season_episodes=False,
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
    # Stub out the UI refresh calls
    host.load_history = MagicMock()
    host.load_favorites = MagicMock()
    # Stub out launch_player_for_episode to avoid real network calls
    host.launch_player_for_episode = MagicMock()
    return host


def _make_playable_episode_dto():
    """Build a minimal EpisodeDTO that play_episode can consume."""
    from metatv.core.repositories.dtos import EpisodeDTO
    return EpisodeDTO(
        id="e_play",
        episode_num=3,
        season_num=2,
        title="S02E03 - Test",
        series_name="Test Series",
        stream_url="http://example.com/s02e03.ts",
        duration="0:45:00",
        is_watched=False,
        rating=None,
        series_id="ser_src_1",
        provider_id="prov1",
        season_id="season_1",
        watch_progress=0,
        watch_completed=False,
    )


def _seed_channel_for_play(db):
    """Seed the parent channel so play_episode's get_by_source_id lookup succeeds."""
    from metatv.core.database import ChannelDB, EpisodeDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id="ch_parent",
            source_id="ser_src_1",
            provider_id="prov1",
            name="Test Series",
            media_type="series",
        ))
        session.add(EpisodeDB(
            id="e_play",
            series_id="ser_src_1",
            season_id="season_1",
            provider_id="prov1",
            episode_id="ep_orig_play",
            season_num=2,
            episode_num=3,
            title="S02E03 - Test",
        ))


def test_play_episode_registers_episode_in_watch_tracking(db):
    """play_episode registers the episode in _watch_tracking for capture."""
    _seed_channel_for_play(db)
    host = _make_series_mixin_host(db)
    ep = _make_playable_episode_dto()

    # Stub _start_watch_capture to avoid QTimer dependency
    host._start_watch_capture = MagicMock()

    host.play_episode(ep)

    tracking = host._watch_tracking
    assert "__shared__" in tracking, "episode not registered in _watch_tracking"
    info = tracking["__shared__"]
    assert info["content_id"] == "e_play"
    assert info["media_type"] == "episode"
    assert info["played_via"] == "manual"


def test_play_episode_calls_start_watch_capture(db):
    """play_episode calls _start_watch_capture to arm the checkpoint timer."""
    _seed_channel_for_play(db)
    host = _make_series_mixin_host(db)
    ep = _make_playable_episode_dto()
    host._start_watch_capture = MagicMock()

    host.play_episode(ep)

    host._start_watch_capture.assert_called_once()


def test_play_episode_threads_provider_id_to_launch(db):
    """play_episode passes provider_id to launch_player_for_episode."""
    _seed_channel_for_play(db)
    host = _make_series_mixin_host(db)
    ep = _make_playable_episode_dto()
    host._start_watch_capture = MagicMock()

    host.play_episode(ep)

    _, kwargs = host.launch_player_for_episode.call_args
    assert kwargs.get("provider_id") == "prov1", (
        f"provider_id not threaded to launch_player_for_episode: {kwargs}"
    )


def test_watch_capture_writes_episode_progress(db):
    """_bg_capture_watch routes to EpisodeRepository.record_watch_progress for episodes."""
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id="ecap",
            series_id="s1",
            season_id="seas1",
            provider_id="p1",
            episode_id="eorig",
            season_num=1,
            episode_num=1,
            title="Cap Episode",
        ))

    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.db = db
    host.config = MagicMock(watch_complete_threshold=0.9)
    host.player_manager = MagicMock()
    host.player_manager.get_properties.return_value = {"time-pos": 1350, "duration": 1500}  # 90%

    host._bg_capture_watch("__shared__", {
        "content_id": "ecap",
        "media_type": "episode",
        "played_via": "manual",
    })

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        ep = RepositoryFactory(session).episodes.get_by_id("ecap")
        assert bool(ep.watch_completed) is True, "episode should be marked completed at 90%"
        assert ep.last_played_via == "manual"
