"""Behavioral tests for the open-ended buffer play action.

Covers:
1. _compose_open_ended_buffer_args produces the correct disk-backed cache args
   (cache-on-disk, 3600s readahead, 2GiB max-bytes) and NOT bounded profile args.
2. open_ended_buffer=False uses the normal _compose_extra_args path (unchanged).
3. open_ended_buffer=True in single-instance mode relaunches the SAME instance key
   in-place (_relaunch_instance) and sends loadfile over IPC — NOT a new standalone
   process.  This ensures the playback-health readout (keyed by instance key) works.
4. open_ended_buffer=True in multiple-instances mode still uses a standalone process
   (_launch_new_instance), since there is no IPC/keying in that mode.
5. open_ended_buffer=True resolves the SAME instance key as a normal play would
   (shared when split off, provider_id when split on) — never a throwaway key.
6. start_seconds + open_ended_buffer compose correctly (start= per-file option in
   loadfile, --start= flag when falling back to standalone process).
7. mpv_args_override_all=True is honoured by _compose_open_ended_buffer_args.
8. user mpv_extra_args are appended last in open-ended mode.
9. RECONNECT_FLAG and canonical UA are present in open-ended mode.
10. The context-menu action is registered in ACTIONS and listed in the correct surfaces.
11. The action handler calls play_media with open_ended_buffer=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call

import pytest

from metatv.core.http_headers import stream_user_agent
from metatv.core.players.mpv import MPVPlayer, RECONNECT_FLAG
from metatv.gui.channel_menu import ACTIONS, SURFACE_LAYOUTS, ChannelMenuContext, build_channel_menu
from metatv.gui import icons as _icons

_CANONICAL_UA = f"--user-agent={stream_user_agent()}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    """Minimal stand-in for Config used by MPVPlayer."""
    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    mpv_socket_path: str = "/tmp/metatv-test.sock"
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False
    buffer_profile: str = "modest"
    prebuffer_before_play: bool = False
    prebuffer_wait_secs: int = 10
    mpv_args_override_all: bool = False


def _player(
    extra_args: list[str] | None = None,
    buffer_profile: str = "modest",
    mpv_args_override_all: bool = False,
) -> MPVPlayer:
    return MPVPlayer(_FakeConfig(
        mpv_extra_args=extra_args if extra_args is not None else [],
        buffer_profile=buffer_profile,
        mpv_args_override_all=mpv_args_override_all,
    ))


# ---------------------------------------------------------------------------
# _compose_open_ended_buffer_args — the core arg-composition unit
# ---------------------------------------------------------------------------

def test_open_ended_buffer_args_has_cache_on_disk():
    """--cache-on-disk=yes must be present in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert "--cache-on-disk=yes" in args


def test_open_ended_buffer_args_has_cache_yes():
    """--cache=yes must be present in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert "--cache=yes" in args


def test_open_ended_buffer_args_readahead_3600():
    """--demuxer-readahead-secs=3600 must be present in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert "--demuxer-readahead-secs=3600" in args


def test_open_ended_buffer_args_max_bytes_2gib():
    """--demuxer-max-bytes=2GiB must be present in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert "--demuxer-max-bytes=2GiB" in args


def test_open_ended_buffer_args_no_bounded_profile_flags():
    """Open-ended mode must NOT include the bounded profile cache-secs flags."""
    args = _player()._compose_open_ended_buffer_args()
    assert not any(a.startswith("--cache-secs") for a in args)


def test_open_ended_buffer_args_has_reconnect_flag():
    """RECONNECT_FLAG must be present in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert RECONNECT_FLAG in args


def test_open_ended_buffer_args_ua_first():
    """Canonical UA must be the first argument in open-ended mode."""
    args = _player()._compose_open_ended_buffer_args()
    assert args[0] == _CANONICAL_UA


def test_open_ended_buffer_args_user_args_last():
    """User mpv_extra_args must be appended last in open-ended mode."""
    args = _player(extra_args=["--foo"])._compose_open_ended_buffer_args()
    assert args[-1] == "--foo"


def test_open_ended_buffer_args_override_all_returns_only_user_args():
    """mpv_args_override_all=True returns exactly user args in open-ended mode."""
    args = _player(
        extra_args=["--bar"], mpv_args_override_all=True
    )._compose_open_ended_buffer_args()
    assert args == ["--bar"]
    assert _CANONICAL_UA not in args
    assert RECONNECT_FLAG not in args


# ---------------------------------------------------------------------------
# Normal play path unchanged (open_ended_buffer=False)
# ---------------------------------------------------------------------------

def test_normal_path_uses_profile_not_open_ended():
    """open_ended_buffer=False → composed args include bounded profile flags, not cache-on-disk."""
    p = _player(buffer_profile="modest")
    normal_args = p._compose_extra_args()
    open_args = p._compose_open_ended_buffer_args()
    assert "--cache-secs=10" in normal_args          # bounded profile flag
    assert "--cache-secs=10" not in open_args        # absent in open-ended mode
    assert "--cache-on-disk=yes" not in normal_args  # absent from normal path
    assert "--cache-on-disk=yes" in open_args        # present in open-ended mode


# ---------------------------------------------------------------------------
# MPVPlayer.play dispatch — open_ended_buffer=True relaunch in single-instance mode
# ---------------------------------------------------------------------------

def test_play_open_ended_buffer_single_instance_calls_relaunch():
    """open_ended_buffer=True in single-instance mode calls _relaunch_instance, not _launch_new_instance."""
    p = _player()
    with patch.object(p, "_relaunch_instance", return_value=True) as mock_relaunch, \
         patch.object(p, "_launch_new_instance", return_value=True) as mock_launch, \
         patch.object(p, "_send_ipc_command", return_value=True):
        result = p.play("http://example.com/stream", "Test", open_ended_buffer=True)

    assert result is True
    mock_relaunch.assert_called_once()
    # _launch_new_instance must NOT be called when the relaunch succeeds.
    mock_launch.assert_not_called()


def test_play_open_ended_buffer_relaunch_uses_same_key_shared():
    """open_ended_buffer=True resolves the SAME key as a normal play (shared when split off)."""
    p = _player()
    relaunch_key: str | None = None

    def capture_relaunch(key, extra_args):
        nonlocal relaunch_key
        relaunch_key = key
        return True

    with patch.object(p, "_relaunch_instance", side_effect=capture_relaunch), \
         patch.object(p, "_send_ipc_command", return_value=True):
        # No instance_key override → defaults to _SHARED_KEY
        p.play("http://x/s", "Test", instance_key="__shared__", open_ended_buffer=True)

    assert relaunch_key == "__shared__", (
        "open_ended_buffer relaunch must target the SAME key as a normal play — got "
        f"{relaunch_key!r}, expected '__shared__'"
    )


def test_play_open_ended_buffer_relaunch_uses_same_key_provider():
    """open_ended_buffer=True passes the provider_id key when split is on."""
    p = _player()
    relaunch_key: str | None = None

    def capture_relaunch(key, extra_args):
        nonlocal relaunch_key
        relaunch_key = key
        return True

    with patch.object(p, "_relaunch_instance", side_effect=capture_relaunch), \
         patch.object(p, "_send_ipc_command", return_value=True):
        p.play("http://x/s", "Test", instance_key="provider-abc", open_ended_buffer=True)

    assert relaunch_key == "provider-abc", (
        "open_ended_buffer relaunch must use the resolved provider key — got "
        f"{relaunch_key!r}"
    )


def test_play_open_ended_buffer_relaunch_passes_open_ended_args():
    """_relaunch_instance receives the open-ended buffer args, not the normal profile."""
    p = _player(buffer_profile="modest")
    relaunch_args: list[str] | None = None

    def capture_relaunch(key, extra_args):
        nonlocal relaunch_args
        relaunch_args = extra_args
        return True

    with patch.object(p, "_relaunch_instance", side_effect=capture_relaunch), \
         patch.object(p, "_send_ipc_command", return_value=True):
        p.play("http://x/s", "Test", open_ended_buffer=True)

    assert relaunch_args is not None
    assert "--cache-on-disk=yes" in relaunch_args
    assert "--demuxer-max-bytes=2GiB" in relaunch_args
    assert "--demuxer-readahead-secs=3600" in relaunch_args
    # Must NOT carry the bounded profile --cache-secs flag
    assert not any(a.startswith("--cache-secs") for a in relaunch_args)


def test_play_open_ended_buffer_sends_loadfile_over_ipc():
    """After relaunch, play sends loadfile over IPC to the SAME instance key."""
    p = _player()
    ipc_commands: list[tuple[dict, str]] = []

    def capture_ipc(command, key):
        ipc_commands.append((command, key))
        return True

    with patch.object(p, "_relaunch_instance", return_value=True), \
         patch.object(p, "_send_ipc_command", side_effect=capture_ipc):
        p.play("http://example.com/stream", "Test", instance_key="__shared__",
               open_ended_buffer=True)

    # First IPC command must be loadfile
    assert ipc_commands, "No IPC commands were sent"
    first_cmd, first_key = ipc_commands[0]
    assert first_cmd["command"][0] == "loadfile"
    assert first_cmd["command"][1] == "http://example.com/stream"
    assert first_key == "__shared__"


def test_play_open_ended_buffer_loadfile_includes_start_seconds():
    """loadfile for open-ended buffer + start_seconds > 0 includes start= per-file option."""
    p = _player()
    ipc_commands: list[tuple[dict, str]] = []

    def capture_ipc(command, key):
        ipc_commands.append((command, key))
        return True

    with patch.object(p, "_relaunch_instance", return_value=True), \
         patch.object(p, "_send_ipc_command", side_effect=capture_ipc):
        p.play("http://x/s", "Test", start_seconds=120, open_ended_buffer=True)

    assert ipc_commands
    first_cmd, _ = ipc_commands[0]
    assert first_cmd["command"][0] == "loadfile"
    # Per-file options string includes start=120
    opts = first_cmd["command"][-1] if len(first_cmd["command"]) > 3 else ""
    assert "start=120" in str(opts)


def test_play_open_ended_buffer_sets_last_key():
    """After a successful open-ended buffer play, _last_key is set to the resolved key."""
    p = _player()

    with patch.object(p, "_relaunch_instance", return_value=True), \
         patch.object(p, "_send_ipc_command", return_value=True):
        p.play("http://x/s", "Test", instance_key="__shared__", open_ended_buffer=True)

    assert p._last_key == "__shared__"


def test_play_open_ended_buffer_multiple_instances_mode_uses_launch_new():
    """open_ended_buffer=True in multiple-instances mode falls through to _launch_new_instance."""
    cfg = _FakeConfig(player_mode="multiple-instances")
    p = MPVPlayer(cfg)
    with patch.object(p, "_launch_new_instance", return_value=True) as mock_launch, \
         patch.object(p, "_relaunch_instance", return_value=True) as mock_relaunch:
        result = p.play("http://x/s", "Test", open_ended_buffer=True)

    assert result is True
    mock_launch.assert_called_once()
    # _relaunch_instance must NOT be called in multiple-instances mode.
    mock_relaunch.assert_not_called()


def test_play_open_ended_buffer_relaunch_failure_falls_back_to_standalone():
    """If _relaunch_instance fails, open-ended buffer falls back to a standalone process."""
    p = _player()
    with patch.object(p, "_relaunch_instance", return_value=False), \
         patch.object(p, "_launch_new_instance", return_value=True) as mock_launch:
        result = p.play("http://x/s", "Test", open_ended_buffer=True)

    assert result is True
    mock_launch.assert_called_once()
    call_kwargs = mock_launch.call_args.kwargs
    assert call_kwargs.get("open_ended_buffer") is True


def test_play_normal_does_not_call_launch_new_instance_when_ipc_ok():
    """With open_ended_buffer=False and IPC working, _launch_new_instance is NOT called."""
    p = _player()
    with patch.object(p, "_launch_new_instance", return_value=True) as mock_launch, \
         patch.object(p, "_ensure_instance_running", return_value=True), \
         patch.object(p, "_send_ipc_command", return_value=True):
        p.play("http://example.com/stream", "Test", open_ended_buffer=False)

    mock_launch.assert_not_called()


# ---------------------------------------------------------------------------
# start_seconds + open_ended_buffer compose correctly in _launch_new_instance
# (fallback path — standalone process for multiple-instances mode or relaunch failure)
# ---------------------------------------------------------------------------

def test_launch_new_instance_open_ended_uses_open_ended_args():
    """_launch_new_instance with open_ended_buffer=True uses open-ended cache args."""
    p = _player()
    launched_cmd: list[str] | None = None

    def fake_popen(cmd, **_kwargs):
        nonlocal launched_cmd
        launched_cmd = cmd
        return MagicMock(pid=999)

    with patch("metatv.core.players.mpv.subprocess.Popen", side_effect=fake_popen):
        p._launch_new_instance("http://x/s", "Title", open_ended_buffer=True)

    assert launched_cmd is not None
    assert "--cache-on-disk=yes" in launched_cmd
    assert "--demuxer-max-bytes=2GiB" in launched_cmd
    assert "--demuxer-readahead-secs=3600" in launched_cmd
    # Bounded profile flags must be absent
    assert not any(a.startswith("--cache-secs") for a in launched_cmd)


def test_launch_new_instance_open_ended_with_start_seconds():
    """_launch_new_instance with open_ended_buffer=True + start_seconds includes --start=."""
    p = _player()
    launched_cmd: list[str] | None = None

    def fake_popen(cmd, **_kwargs):
        nonlocal launched_cmd
        launched_cmd = cmd
        return MagicMock(pid=999)

    with patch("metatv.core.players.mpv.subprocess.Popen", side_effect=fake_popen):
        p._launch_new_instance(
            "http://x/s", "Title", start_seconds=120, open_ended_buffer=True
        )

    assert launched_cmd is not None
    assert "--start=120" in launched_cmd
    assert "--cache-on-disk=yes" in launched_cmd


def test_launch_new_instance_normal_no_start_seconds():
    """_launch_new_instance with start_seconds=0 does NOT include --start=."""
    p = _player()
    launched_cmd: list[str] | None = None

    def fake_popen(cmd, **_kwargs):
        nonlocal launched_cmd
        launched_cmd = cmd
        return MagicMock(pid=999)

    with patch("metatv.core.players.mpv.subprocess.Popen", side_effect=fake_popen):
        p._launch_new_instance("http://x/s", "Title", start_seconds=0)

    assert launched_cmd is not None
    assert not any(a.startswith("--start=") for a in launched_cmd)


# ---------------------------------------------------------------------------
# channel_menu registry — action wired + surfaces
# ---------------------------------------------------------------------------

def test_play_open_ended_buffer_in_actions():
    """'play_open_ended_buffer' must be registered in the ACTIONS dict."""
    assert "play_open_ended_buffer" in ACTIONS


def test_play_open_ended_buffer_action_has_icon():
    """The action must reference the open_ended_buffer_icon from icons.py."""
    action = ACTIONS["play_open_ended_buffer"]
    assert action.icon == _icons.open_ended_buffer_icon


def test_play_open_ended_buffer_in_channel_surface():
    """'play_open_ended_buffer' must appear in the 'channel' surface layout."""
    assert "play_open_ended_buffer" in SURFACE_LAYOUTS["channel"]


def test_play_open_ended_buffer_in_history_surface():
    """'play_open_ended_buffer' must appear in the 'history' surface layout."""
    assert "play_open_ended_buffer" in SURFACE_LAYOUTS["history"]


def test_play_open_ended_buffer_in_favorites_surface():
    """'play_open_ended_buffer' must appear in the 'favorites' surface layout."""
    assert "play_open_ended_buffer" in SURFACE_LAYOUTS["favorites"]


def test_play_open_ended_buffer_applies_single_channel():
    """The action must apply for a single, found channel."""
    action = ACTIONS["play_open_ended_buffer"]
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        channel_found=True,
    )
    assert action.applies(ctx) is True


def test_play_open_ended_buffer_does_not_apply_multi():
    """The action must NOT apply to multi-select contexts."""
    action = ACTIONS["play_open_ended_buffer"]
    ctx = ChannelMenuContext(
        channel_ids=["ch1", "ch2"],
        surface="channel",
        channel_found=True,
    )
    assert action.applies(ctx) is False


# ---------------------------------------------------------------------------
# build_channel_menu wiring — handler is invoked
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_build_menu_open_ended_buffer_handler_called(qapp):
    """Triggering 'play_open_ended_buffer' in a built menu calls the supplied handler."""
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        channel_found=True,
    )
    called = []
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "play_open_ended_buffer": lambda: called.append(True),
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "mark_watched": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    # Find the action by label prefix (icon + label text)
    target_label_frag = "open-ended buffer"
    for action in menu.actions():
        if target_label_frag in action.text():
            action.trigger()
            break
    else:
        pytest.fail("'play_open_ended_buffer' action not found in built menu")

    assert called == [True], "Handler was not invoked"
