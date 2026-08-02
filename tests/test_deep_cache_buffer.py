"""Behavioral tests for the deep-cache ("Buffer without limit") VOD play action.

Covers (per the wave5/deep-cache slice brief):
1. _compose_deep_cache_args composes the open-ended disk-backed cache flags PLUS
   --stream-record=<path> and --cache-pause-initial=yes (via the "deep" buffer
   profile added to _buffer_profile_args), honoring mpv_args_override_all.
2. play(deep_buffer=True) bypasses an explicit config.default_cache_size and logs
   that it did so (rather than silently deferring to the smaller explicit size).
3. The recording file is purged on the owning instance's stop() / relaunch() /
   cleanup() — symmetric with the existing socket-unlink teardown — and any
   leftover file is swept at MPVPlayer construction (startup).
4. The deep_cache_max_gb soft cap evicts the oldest .ts files first when the
   cache dir already exceeds it; a too-low free-disk-space preflight refuses
   the launch and surfaces a message via last_deep_cache_message.
5. The "play_deep_cache" context-menu action is registered, applies to VOD
   (movie/series) only — never live — and is listed in the VOD-facing surfaces.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from metatv.core.http_headers import stream_user_agent
from metatv.core.players.mpv import MPVPlayer, RECONNECT_FLAG, _Inst
from metatv.gui.channel_menu import ACTIONS, SURFACE_LAYOUTS, ChannelMenuContext

_CANONICAL_UA = f"--user-agent={stream_user_agent()}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    """Minimal stand-in for Config used by MPVPlayer, extended with the
    deep-cache fields this slice adds (mirrors tests/test_open_ended_buffer.py's
    _FakeConfig)."""
    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    mpv_socket_path: str = "/tmp/metatv-test-deep.sock"
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False
    buffer_profile: str = "modest"
    prebuffer_before_play: bool = False
    prebuffer_wait_secs: int = 10
    mpv_args_override_all: bool = False
    deep_cache_dir: str = "/tmp/metatv-test-deepcache-unused"
    deep_cache_max_gb: int = 1


def _player(cache_dir: Path, **overrides) -> MPVPlayer:
    """Build an MPVPlayer whose deep_cache_dir points at *cache_dir* (a real,
    absolute, non-tilde path — e.g. pytest's tmp_path) so tests never touch the
    real user home directory."""
    cfg = _FakeConfig(deep_cache_dir=str(cache_dir), **overrides)
    return MPVPlayer(cfg)


def _disk_usage(free_bytes: int) -> SimpleNamespace:
    """Fake shutil.disk_usage() result — only .free is read by the preflight."""
    return SimpleNamespace(total=free_bytes * 2, used=free_bytes, free=free_bytes)


def _plenty_disk():
    """Patch shutil.disk_usage to report ample free space (preflight always OK)."""
    return patch(
        "metatv.core.players.mpv.shutil.disk_usage",
        return_value=_disk_usage(100 * (1024 ** 3)),
    )


# ---------------------------------------------------------------------------
# 1. _compose_deep_cache_args — the core arg-composition unit
# ---------------------------------------------------------------------------

def test_deep_cache_args_has_stream_record(tmp_path):
    p = _player(tmp_path)
    record_path = str(tmp_path / "abc123.ts")
    args = p._compose_deep_cache_args(record_path)
    assert f"--stream-record={record_path}" in args


def test_deep_cache_args_has_open_ended_cache_flags(tmp_path):
    p = _player(tmp_path)
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert "--cache=yes" in args
    assert "--cache-on-disk=yes" in args
    assert "--demuxer-readahead-secs=3600" in args
    assert "--demuxer-max-bytes=2GiB" in args


def test_deep_cache_args_has_cache_pause_initial(tmp_path):
    p = _player(tmp_path)
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert "--cache-pause-initial=yes" in args


def test_deep_cache_args_ua_first_and_reconnect_present(tmp_path):
    p = _player(tmp_path)
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert args[0] == _CANONICAL_UA
    assert RECONNECT_FLAG in args


def test_deep_cache_args_user_args_last(tmp_path):
    p = _player(tmp_path, mpv_extra_args=["--foo"])
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert args[-1] == "--foo"


def test_deep_cache_args_override_all_returns_only_user_args(tmp_path):
    p = _player(tmp_path, mpv_extra_args=["--bar"], mpv_args_override_all=True)
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert args == ["--bar"]
    assert _CANONICAL_UA not in args
    assert not any(a.startswith("--stream-record") for a in args)


def test_buffer_profile_deep_has_open_ended_and_pause_but_not_record(tmp_path):
    """_buffer_profile_args('deep') is the STATIC portion _compose_deep_cache_args
    builds on — it must not itself carry --stream-record (that's per-play)."""
    profile_args = MPVPlayer._buffer_profile_args("deep")
    assert "--cache-on-disk=yes" in profile_args
    assert "--demuxer-max-bytes=2GiB" in profile_args
    assert "--cache-pause-initial=yes" in profile_args
    assert not any(a.startswith("--stream-record") for a in profile_args)


def test_deep_cache_record_path_is_deterministic_per_channel_id(tmp_path):
    p = _player(tmp_path)
    path1 = p._deep_cache_record_path("chan123")
    path2 = p._deep_cache_record_path("chan123")
    assert path1 == path2
    assert path1.name == "chan123.ts"
    assert path1.parent == tmp_path


# ---------------------------------------------------------------------------
# 2. default_cache_size bypass — logged, not silently honored
# ---------------------------------------------------------------------------

def test_deep_buffer_bypasses_explicit_default_cache_size_and_logs(tmp_path):
    p = _player(tmp_path, default_cache_size="100M")
    with _plenty_disk(), \
         patch.object(p, "_relaunch_instance", return_value=True), \
         patch.object(p, "_send_ipc_command", return_value=True), \
         patch("metatv.core.players.mpv.logger") as mock_logger:
        result = p.play(
            "http://example.com/stream", "Test Movie",
            deep_buffer=True, channel_id="chan1",
        )

    assert result is True
    bypass_logged = any(
        "default_cache_size" in str(c) and "100M" in str(c)
        for c in mock_logger.info.call_args_list
    )
    assert bypass_logged, (
        f"expected a log noting the default_cache_size bypass, got "
        f"{mock_logger.info.call_args_list}"
    )


def test_deep_buffer_args_ignore_default_cache_size(tmp_path):
    """Unlike _compose_extra_args, deep-cache args always use the open-ended
    profile even when an explicit default_cache_size is configured."""
    p = _player(tmp_path, default_cache_size="100M")
    args = p._compose_deep_cache_args(str(tmp_path / "x.ts"))
    assert "--demuxer-max-bytes=2GiB" in args
    assert not any("100M" in a for a in args)


# ---------------------------------------------------------------------------
# 3. Purge on stop / relaunch / cleanup — symmetric with the socket unlink
# ---------------------------------------------------------------------------

def test_stop_purges_deep_cache_recording(tmp_path):
    p = _player(tmp_path)
    record_file = tmp_path / "chan42.ts"
    record_file.write_bytes(b"fake ts data")

    key = "__shared__"
    p._instances[key] = _Inst(process=None, socket_path="", record_path=str(record_file))

    p.stop(key=key)

    assert not record_file.exists()


def test_stop_clears_record_path_after_purge(tmp_path):
    p = _player(tmp_path)
    record_file = tmp_path / "chan7.ts"
    record_file.write_bytes(b"data")
    key = "__shared__"
    inst = _Inst(process=None, socket_path="", record_path=str(record_file))
    p._instances[key] = inst

    p.stop(key=key)

    assert inst.record_path == ""


def test_stop_is_noop_when_no_deep_cache_recording(tmp_path):
    """stop() must not error when the instance never used deep-cache mode."""
    p = _player(tmp_path)
    key = "__shared__"
    p._instances[key] = _Inst(process=None, socket_path="", record_path="")
    result = p.stop(key=key)
    assert result is False  # no running process → no IPC quit sent


def test_relaunch_purges_previous_deep_cache_recording(tmp_path):
    p = _player(tmp_path)
    old_file = tmp_path / "old.ts"
    old_file.write_bytes(b"stale recording")

    key = "__shared__"
    fake_proc = MagicMock()
    fake_proc.poll.return_value = None  # still "running"
    p._instances[key] = _Inst(process=fake_proc, socket_path="", record_path=str(old_file))

    with patch.object(p, "_launch_ipc_instance", return_value=True):
        p._relaunch_instance(key, ["--some-flag"], record_path="")

    assert not old_file.exists()
    fake_proc.terminate.assert_called_once()


def test_cleanup_purges_all_deep_cache_recordings(tmp_path):
    p = _player(tmp_path)
    rec = tmp_path / "z.ts"
    rec.write_bytes(b"data")

    fake_proc = MagicMock()
    fake_proc.poll.return_value = 0  # already exited
    p._instances["__shared__"] = _Inst(process=fake_proc, socket_path="", record_path=str(rec))

    p.cleanup()

    assert not rec.exists()
    assert p._instances == {}


def test_startup_sweep_removes_leftover_files(tmp_path):
    leftover = tmp_path / "leftover.ts"
    leftover.write_bytes(b"stale from a crashed run")

    _player(tmp_path)  # __init__ runs the startup sweep

    assert not leftover.exists()


def test_startup_sweep_never_creates_the_directory(tmp_path):
    """The startup sweep must be a no-op (not create the dir) when it doesn't
    already exist — this must stay side-effect-free for every test/run that
    never used deep-cache mode."""
    missing_dir = tmp_path / "not_created_yet"
    _player(missing_dir)
    assert not missing_dir.exists()


def test_init_safe_without_deep_cache_config_fields():
    """MPVPlayer must not crash when config lacks the new deep_cache_* fields
    entirely — other test files' pre-existing Config stand-ins won't have them."""

    @dataclass
    class _BareConfig:
        default_cache_size: str = "auto"
        mpv_extra_args: list = field(default_factory=list)
        mpv_socket_path: str = "/tmp/metatv-test-bare.sock"
        player_mode: str = "single-instance"
        close_player_when_finished: bool = False
        buffer_profile: str = "modest"
        prebuffer_before_play: bool = False
        prebuffer_wait_secs: int = 10
        mpv_args_override_all: bool = False

    p = MPVPlayer(_BareConfig())
    assert p.last_deep_cache_message == ""


# ---------------------------------------------------------------------------
# 4. Soft cap (deep_cache_max_gb) + free-disk refusal
# ---------------------------------------------------------------------------

def test_cap_sweep_evicts_oldest_files_first(tmp_path):
    # Construct the player FIRST — MPVPlayer.__init__ runs the startup sweep,
    # which would otherwise remove these leftover-looking files immediately.
    p = _player(tmp_path)

    paths = []
    for i in range(3):
        f = tmp_path / f"chan{i}.ts"
        f.write_bytes(b"0" * (1024 * 1024))  # 1 MiB each
        # chan0 oldest, chan2 newest.
        mtime = time.time() - (3 - i) * 100
        os.utime(f, (mtime, mtime))
        paths.append(f)

    max_bytes = 2 * 1024 * 1024  # cap = 2 MiB; total is 3 MiB, so 1 file must go
    p._purge_deep_cache_over_cap(tmp_path, max_bytes)

    remaining = {f.name for f in tmp_path.glob("*.ts")}
    assert "chan0.ts" not in remaining, "oldest file must be evicted first"
    assert "chan2.ts" in remaining, "newest file must survive"


def test_cap_sweep_noop_when_under_cap(tmp_path):
    p = _player(tmp_path)  # construct first — see note above
    f = tmp_path / "small.ts"
    f.write_bytes(b"0" * 1024)
    p._purge_deep_cache_over_cap(tmp_path, max_bytes=10 * 1024 * 1024)
    assert f.exists()


def test_preflight_refuses_when_free_disk_below_2x_cap(tmp_path):
    p = _player(tmp_path, deep_cache_max_gb=10)
    tiny_free = 5 * (1024 ** 3)  # 5 GiB < 2 * 10 GiB cap
    with patch("metatv.core.players.mpv.shutil.disk_usage", return_value=_disk_usage(tiny_free)):
        ok, message = p._deep_cache_preflight()

    assert ok is False
    assert message
    assert "disk" in message.lower() or "space" in message.lower()


def test_play_deep_buffer_refused_sets_last_deep_cache_message(tmp_path):
    p = _player(tmp_path, deep_cache_max_gb=10)
    tiny_free = 5 * (1024 ** 3)
    with patch("metatv.core.players.mpv.shutil.disk_usage", return_value=_disk_usage(tiny_free)):
        result = p.play("http://x/s", "Movie", deep_buffer=True, channel_id="m1")

    assert result is False
    assert p.last_deep_cache_message


def test_preflight_passes_with_ample_free_disk(tmp_path):
    p = _player(tmp_path, deep_cache_max_gb=1)
    with _plenty_disk():
        ok, message = p._deep_cache_preflight()
    assert ok is True
    assert message == ""


# ---------------------------------------------------------------------------
# 5. MPVPlayer.play(deep_buffer=True) dispatch
# ---------------------------------------------------------------------------

def test_play_deep_buffer_single_instance_relaunches_with_record_path(tmp_path):
    p = _player(tmp_path)
    captured = {}

    def fake_relaunch(key, extra_args, record_path=""):
        captured["key"] = key
        captured["extra_args"] = extra_args
        captured["record_path"] = record_path
        return True

    with _plenty_disk(), \
         patch.object(p, "_relaunch_instance", side_effect=fake_relaunch) as mock_relaunch, \
         patch.object(p, "_launch_new_instance", return_value=True) as mock_launch, \
         patch.object(p, "_send_ipc_command", return_value=True):
        result = p.play("http://x/s", "Movie Title", deep_buffer=True, channel_id="movie-7")

    assert result is True
    mock_relaunch.assert_called_once()
    mock_launch.assert_not_called()
    assert captured["record_path"].endswith("movie-7.ts")
    assert f"--stream-record={captured['record_path']}" in captured["extra_args"]


def test_play_deep_buffer_falls_back_to_standalone_when_relaunch_fails(tmp_path):
    p = _player(tmp_path)
    with _plenty_disk(), \
         patch.object(p, "_relaunch_instance", return_value=False), \
         patch.object(p, "_launch_new_instance", return_value=True) as mock_launch:
        result = p.play("http://x/s", "Movie", deep_buffer=True, channel_id="m1")

    assert result is True
    mock_launch.assert_called_once()
    _, kwargs = mock_launch.call_args
    assert kwargs.get("deep_buffer") is True
    assert kwargs.get("record_path", "").endswith("m1.ts")


def test_launch_new_instance_deep_buffer_uses_deep_cache_args(tmp_path):
    p = _player(tmp_path)
    launched_cmd: list[str] | None = None

    def fake_popen(cmd, **_kwargs):
        nonlocal launched_cmd
        launched_cmd = cmd
        return MagicMock(pid=999)

    record_path = str(tmp_path / "m2.ts")
    with patch("metatv.core.players.mpv.subprocess.Popen", side_effect=fake_popen):
        p._launch_new_instance(
            "http://x/s", "Title", deep_buffer=True, record_path=record_path,
        )

    assert launched_cmd is not None
    assert f"--stream-record={record_path}" in launched_cmd
    assert "--cache-on-disk=yes" in launched_cmd


# ---------------------------------------------------------------------------
# 6. Context-menu registry — action registered, VOD-only
# ---------------------------------------------------------------------------

def test_play_deep_cache_action_registered():
    assert "play_deep_cache" in ACTIONS
    action = ACTIONS["play_deep_cache"]
    assert action.icon


def test_play_deep_cache_applies_movie_and_series_not_live():
    movie_ctx = ChannelMenuContext(
        channel_ids=["c1"], surface="channel", media_type="movie", channel_found=True
    )
    series_ctx = ChannelMenuContext(
        channel_ids=["c1"], surface="channel", media_type="series", channel_found=True
    )
    live_ctx = ChannelMenuContext(
        channel_ids=["c1"], surface="channel", media_type="live", channel_found=True
    )
    unknown_ctx = ChannelMenuContext(
        channel_ids=["c1"], surface="channel", media_type="", channel_found=True
    )

    action = ACTIONS["play_deep_cache"]
    assert action.applies(movie_ctx) is True
    assert action.applies(series_ctx) is True
    assert action.applies(live_ctx) is False
    assert action.applies(unknown_ctx) is False


def test_play_deep_cache_listed_in_vod_surfaces_only():
    for surface in ("channel", "favorites", "queue", "history", "recommended"):
        assert "play_deep_cache" in SURFACE_LAYOUTS[surface], surface

    # Live-only / non-VOD surfaces must never offer it.
    for surface in ("alerts", "retry", "epg_on_now", "epg_browse"):
        assert "play_deep_cache" not in SURFACE_LAYOUTS[surface], surface
