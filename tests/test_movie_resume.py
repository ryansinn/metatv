"""Behavioral tests for movie resume-seek.

Covered behaviors:
1. PlayableChannelDTO carries watch_progress and watch_completed from the DB.
2. get_playable_dto populates watch_progress and watch_completed.
3. play_media resolves start_seconds > 0 for a non-live channel with saved progress.
4. play_media resolves start_seconds == 0 for a live channel (no resume).
5. play_media resolves start_seconds == 0 when watch_completed is True.
6. play_media resolves start_seconds == 0 when watch_progress is 0.
7. _bg_validate_and_play threads start_seconds into the _stream_ready payload.
8. _on_stream_ready passes start_seconds to player_manager.play().
9. PlayerManager.play() passes start_seconds down to MPVPlayer.play().
10. MPVPlayer.play() includes per-file start= option in loadfile when start_seconds > 0.
11. MPVPlayer.play() omits per-file options when start_seconds == 0.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# DB fixture + seed helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'resume.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_channel(
    db,
    ch_id: str,
    media_type: str,
    watch_progress: int = 0,
    watch_completed: bool = False,
) -> None:
    from metatv.core.database import ChannelDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=ch_id,
            source_id=ch_id,
            provider_id="p1",
            name=f"Channel {ch_id}",
            media_type=media_type,
            stream_url=f"http://example.com/{ch_id}.mp4",
            watch_progress=watch_progress,
            watch_completed=watch_completed,
        ))


# ---------------------------------------------------------------------------
# 1–2. PlayableChannelDTO fields from DB
# ---------------------------------------------------------------------------

def test_playable_dto_watch_fields_populated(db):
    """get_playable_dto returns a DTO with watch_progress and watch_completed set."""
    _seed_channel(db, "movie1", "movie", watch_progress=300, watch_completed=False)

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).channels.get_playable_dto("movie1")

    assert dto is not None
    assert dto.watch_progress == 300
    assert dto.watch_completed is False


def test_playable_dto_watch_completed(db):
    """get_playable_dto reflects watch_completed=True when channel is finished."""
    _seed_channel(db, "movie2", "movie", watch_progress=0, watch_completed=True)

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).channels.get_playable_dto("movie2")

    assert dto is not None
    assert dto.watch_completed is True
    assert dto.watch_progress == 0


def test_playable_dto_defaults_to_zero_progress(db):
    """get_playable_dto defaults watch_progress=0, watch_completed=False for fresh channel."""
    _seed_channel(db, "movie3", "movie")

    with db.session_scope(commit=False) as session:
        from metatv.core.repositories import RepositoryFactory
        dto = RepositoryFactory(session).channels.get_playable_dto("movie3")

    assert dto is not None
    assert dto.watch_progress == 0
    assert dto.watch_completed is False


# ---------------------------------------------------------------------------
# 3–6. start_seconds resolution in play_media
# ---------------------------------------------------------------------------

def _make_streaming_host():
    """Minimal _StreamingMixin host without running mpv or Qt."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.loading_channels = set()
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif-1"
    host.player_manager = MagicMock()
    host.player_manager.is_available.return_value = True
    host.executor = MagicMock()
    return host


def _make_channel_dto(
    media_type: str,
    watch_progress: int = 0,
    watch_completed: bool = False,
) -> object:
    from metatv.core.repositories.dtos import PlayableChannelDTO
    return PlayableChannelDTO(
        id="ch1",
        source_id="src1",
        provider_id="p1",
        name="Test Channel",
        stream_url="http://example.com/stream.mp4",
        media_type=media_type,
        is_favorite=False,
        is_hidden=False,
        is_adult=False,
        logo_url=None,
        detected_prefix=None,
        detected_quality=None,
        detected_region=None,
        detected_title=None,
        detected_year=None,
        raw_data=None,
        metadata_id=None,
        watch_progress=watch_progress,
        watch_completed=watch_completed,
    )


def test_play_media_resolves_start_for_in_progress_movie():
    """play_media submits start_seconds=watch_progress for a non-live channel with saved progress."""
    host = _make_streaming_host()
    channel = _make_channel_dto("movie", watch_progress=300, watch_completed=False)

    host.play_media(channel)

    # Verify executor.submit was called with start_seconds=300 as last positional arg
    call_args = host.executor.submit.call_args
    submitted_fn, *pos_args = call_args[0]
    assert submitted_fn == host._bg_validate_and_play
    # start_seconds is the last positional argument
    assert pos_args[-1] == 300


def test_play_media_no_resume_for_live_channel():
    """play_media submits start_seconds=0 for a live channel regardless of watch_progress."""
    host = _make_streaming_host()
    # Live channels can't really have watch_progress but guard anyway
    channel = _make_channel_dto("live", watch_progress=300, watch_completed=False)

    host.play_media(channel)

    call_args = host.executor.submit.call_args
    _, *pos_args = call_args[0]
    assert pos_args[-1] == 0


def test_play_media_no_resume_when_completed():
    """play_media submits start_seconds=0 when watch_completed is True."""
    host = _make_streaming_host()
    channel = _make_channel_dto("movie", watch_progress=0, watch_completed=True)

    host.play_media(channel)

    call_args = host.executor.submit.call_args
    _, *pos_args = call_args[0]
    assert pos_args[-1] == 0


def test_play_media_no_resume_when_no_progress():
    """play_media submits start_seconds=0 when watch_progress == 0."""
    host = _make_streaming_host()
    channel = _make_channel_dto("movie", watch_progress=0, watch_completed=False)

    host.play_media(channel)

    call_args = host.executor.submit.call_args
    _, *pos_args = call_args[0]
    assert pos_args[-1] == 0


# ---------------------------------------------------------------------------
# 7. _bg_validate_and_play threads start_seconds into the payload
# ---------------------------------------------------------------------------

def test_bg_validate_threads_start_seconds():
    """_bg_validate_and_play emits start_seconds in the _stream_ready payload."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host._stream_ready = MagicMock()

    with patch.object(host, "validate_and_failover_stream_url", return_value=("http://ok.mp4", None)):
        host._bg_validate_and_play(
            "ch1", "My Movie", "http://stream.mp4", "p1", "notif-1",
            False, 450
        )

    emitted = host._stream_ready.emit.call_args[0][0]
    assert emitted["start_seconds"] == 450
    assert emitted["ok"] is True


def test_bg_validate_threads_start_seconds_on_error():
    """_bg_validate_and_play includes start_seconds in the error payload too."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host._stream_ready = MagicMock()

    with patch.object(host, "validate_and_failover_stream_url", return_value=("", "not available")):
        host._bg_validate_and_play(
            "ch1", "My Movie", "http://stream.mp4", "p1", "notif-1",
            False, 450
        )

    emitted = host._stream_ready.emit.call_args[0][0]
    assert emitted["start_seconds"] == 450
    assert emitted["ok"] is False


# ---------------------------------------------------------------------------
# 8. _on_stream_ready passes start_seconds to player_manager.play()
# ---------------------------------------------------------------------------

def _make_host_for_stream_ready():
    """Minimal host for _on_stream_ready tests.

    load_history, load_favorites, and _refresh_queue_section live on MainWindow
    (not the mixin), so we stub them directly on the instance rather than using
    patch.object (which requires the attribute to already exist on the object).
    """
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.status_bar = MagicMock()
    host.loading_channels = set()
    host.notification_manager = MagicMock()
    host.player_manager = MagicMock()
    host.player_manager.play.return_value = True
    host.player_manager.resolve_key.return_value = "__shared__"
    host.executor = MagicMock()
    host._watch_tracking = {}
    host._provider_icons = {}
    # MainWindow-only methods stubbed directly (not in the mixin):
    host.load_history = MagicMock()
    host.load_favorites = MagicMock()
    host._refresh_queue_section = MagicMock()
    host._start_watch_capture = MagicMock()
    host._lookup_provider_icon = MagicMock(return_value="")
    host._start_playback_health = MagicMock()
    return host


def test_on_stream_ready_passes_start_seconds():
    """_on_stream_ready calls player_manager.play with start_seconds from the payload."""
    host = _make_host_for_stream_ready()

    host._on_stream_ready({
        "ok": True,
        "channel_id": "ch1",
        "channel_name": "My Movie",
        "original_url": "http://stream.mp4",
        "final_url": "http://stream.mp4",
        "stream_err": "",
        "notif_id": "notif-1",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 720,
    })

    host.player_manager.play.assert_called_once_with(
        "http://stream.mp4", "My Movie",
        provider_id="p1",
        force_new_window=False,
        start_seconds=720,
    )


def test_on_stream_ready_defaults_start_seconds_to_zero():
    """_on_stream_ready passes start_seconds=0 when key is absent from payload."""
    host = _make_host_for_stream_ready()

    host._on_stream_ready({
        "ok": True,
        "channel_id": "ch1",
        "channel_name": "My Movie",
        "original_url": "http://stream.mp4",
        "final_url": "http://stream.mp4",
        "stream_err": "",
        "notif_id": "notif-1",
        "provider_id": "p1",
        "force_new_window": False,
        # no "start_seconds" key — backward-compat
    })

    host.player_manager.play.assert_called_once_with(
        "http://stream.mp4", "My Movie",
        provider_id="p1",
        force_new_window=False,
        start_seconds=0,
    )


# ---------------------------------------------------------------------------
# 9. PlayerManager.play() passes start_seconds to MPVPlayer.play()
# ---------------------------------------------------------------------------

def test_player_manager_play_threads_start_seconds():
    """PlayerManager.play() forwards start_seconds to the underlying player."""
    from metatv.core.player_manager import PlayerManager
    pm = PlayerManager.__new__(PlayerManager)
    pm.config = MagicMock(
        split_streams_by_source=False,
        max_player_instances=-1,
        player_mode="single-instance",
    )
    pm._key_provider = {}
    pm.running_instances = []
    pm.player = MagicMock()
    pm.player.play.return_value = True

    pm.play("http://stream.mp4", "My Movie", provider_id="p1", start_seconds=360)

    pm.player.play.assert_called_once_with(
        "http://stream.mp4", "My Movie",
        instance_key="__shared__",
        start_seconds=360,
    )


# ---------------------------------------------------------------------------
# 10–11. MPVPlayer.play() per-file start= option
# ---------------------------------------------------------------------------

def _make_mpv_player():
    """Build an MPVPlayer with mocked IPC so we can inspect loadfile commands."""
    from metatv.core.players.mpv import MPVPlayer
    from metatv.core.config import Config
    player = MPVPlayer.__new__(MPVPlayer)
    player.config = MagicMock(spec=Config)
    player.config.mpv_socket_path = "/tmp/test.sock"
    player.config.player_mode = "single-instance"
    player.single_instance = True
    player._instances = {}
    player._last_key = None
    player._request_id = 100
    return player


def test_mpv_play_includes_start_option_when_nonzero():
    """MPVPlayer.play() sends loadfile with start=N per-file option when start_seconds > 0."""
    player = _make_mpv_player()
    sent_commands = []

    with patch.object(player, "_ensure_instance_running", return_value=True), \
         patch.object(player, "_send_ipc_command", side_effect=lambda cmd, key: sent_commands.append(cmd) or True):

        result = player.play("http://stream.mp4", "My Movie", start_seconds=300)

    assert result is True
    # First command sent is the loadfile
    loadfile_cmd = sent_commands[0]
    assert loadfile_cmd["command"][0] == "loadfile"
    assert loadfile_cmd["command"][2] == "replace"
    # Per-file options argument must contain start=300
    per_file_opts = loadfile_cmd["command"][4]
    assert "start=300" in per_file_opts


def test_mpv_play_omits_per_file_opts_when_zero():
    """MPVPlayer.play() sends a plain loadfile (no per-file opts) when start_seconds == 0."""
    player = _make_mpv_player()
    sent_commands = []

    with patch.object(player, "_ensure_instance_running", return_value=True), \
         patch.object(player, "_send_ipc_command", side_effect=lambda cmd, key: sent_commands.append(cmd) or True):

        result = player.play("http://stream.mp4", "My Movie", start_seconds=0)

    assert result is True
    loadfile_cmd = sent_commands[0]
    assert loadfile_cmd["command"][0] == "loadfile"
    # Only 3 args: ["loadfile", url, "replace"] — no per-file opts
    assert len(loadfile_cmd["command"]) == 3
