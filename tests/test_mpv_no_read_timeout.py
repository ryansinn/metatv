"""Regression tests for NO_READ_TIMEOUT_FLAG (PLAY-20) — socket read timeout fix.

On a one-connection IPTV source, mpv's 60s default --network-timeout cuts stalled
connections. When ffmpeg reconnects while still holding the old socket, the source
counts two connections and refuses the reconnect (HTTP 509). Setting --network-timeout=0
(FFmpeg default = no read timeout) lets the stall resume on the original connection,
so a queued series plays through without locking itself out.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metatv.core.http_headers import stream_user_agent
from metatv.core.players.mpv import (
    MPVPlayer,
    RECONNECT_FLAG,
    NO_READ_TIMEOUT_FLAG,
    _base_stream_args,
)

_CANONICAL_UA = f"--user-agent={stream_user_agent()}"


@dataclass
class _FakeConfig:
    """Minimal stand-in for Config — MPVPlayer reads only these fields."""

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
    cache_size: str = "auto",
    extra_args: list[str] | None = None,
    buffer_profile: str = "modest",
    prebuffer_before_play: bool = False,
    prebuffer_wait_secs: int = 10,
    mpv_args_override_all: bool = False,
) -> MPVPlayer:
    return MPVPlayer(_FakeConfig(
        default_cache_size=cache_size,
        mpv_extra_args=extra_args if extra_args is not None else [],
        buffer_profile=buffer_profile,
        prebuffer_before_play=prebuffer_before_play,
        prebuffer_wait_secs=prebuffer_wait_secs,
        mpv_args_override_all=mpv_args_override_all,
    ))


# ---------------------------------------------------------------------------
# NO_READ_TIMEOUT_FLAG presence in all composers
# ---------------------------------------------------------------------------

def test_no_read_timeout_flag_in_compose_extra_args():
    """_compose_extra_args() result contains --network-timeout=0 exactly once."""
    args = _player("auto", [], "modest")._compose_extra_args()
    count = args.count(NO_READ_TIMEOUT_FLAG)
    assert count == 1, f"Expected exactly 1 {NO_READ_TIMEOUT_FLAG}, found {count}"


def test_no_read_timeout_flag_in_compose_open_ended_buffer_args():
    """_compose_open_ended_buffer_args() result contains --network-timeout=0 exactly once."""
    args = _player("auto", [], "open_ended")._compose_open_ended_buffer_args()
    count = args.count(NO_READ_TIMEOUT_FLAG)
    assert count == 1, f"Expected exactly 1 {NO_READ_TIMEOUT_FLAG}, found {count}"


def test_no_read_timeout_flag_in_compose_deep_cache_args():
    """_compose_deep_cache_args() result contains --network-timeout=0 exactly once."""
    args = _player("auto", [])._compose_deep_cache_args("/tmp/test.ts")
    count = args.count(NO_READ_TIMEOUT_FLAG)
    assert count == 1, f"Expected exactly 1 {NO_READ_TIMEOUT_FLAG}, found {count}"


# ---------------------------------------------------------------------------
# Override-all path omits NO_READ_TIMEOUT_FLAG
# ---------------------------------------------------------------------------

def test_no_read_timeout_flag_omitted_with_override_all():
    """With mpv_args_override_all=True, --network-timeout=0 is NOT present."""
    args = _player("auto", ["--foo"], "modest", mpv_args_override_all=True)._compose_extra_args()
    assert NO_READ_TIMEOUT_FLAG not in args


def test_no_read_timeout_flag_omitted_override_all_open_ended():
    """override_all=True in _compose_open_ended_buffer_args() omits --network-timeout=0."""
    args = _player("auto", ["--foo"], "open_ended", mpv_args_override_all=True)._compose_open_ended_buffer_args()
    assert NO_READ_TIMEOUT_FLAG not in args


def test_no_read_timeout_flag_omitted_override_all_deep_cache():
    """override_all=True in _compose_deep_cache_args() omits --network-timeout=0."""
    args = _player("auto", [], mpv_args_override_all=True)._compose_deep_cache_args("/tmp/test.ts")
    assert NO_READ_TIMEOUT_FLAG not in args


# ---------------------------------------------------------------------------
# _base_stream_args() helper — composition and ordering
# ---------------------------------------------------------------------------

def test_base_stream_args_returns_list_of_three():
    """_base_stream_args() returns a list with exactly 3 elements."""
    args = _base_stream_args()
    assert len(args) == 3


def test_base_stream_args_first_element_is_user_agent():
    """_base_stream_args()[0] is --user-agent=<canonical>."""
    args = _base_stream_args()
    assert args[0].startswith("--user-agent=")
    assert args[0] == _CANONICAL_UA


def test_base_stream_args_second_element_is_reconnect_flag():
    """_base_stream_args()[1] is RECONNECT_FLAG."""
    args = _base_stream_args()
    assert args[1] == RECONNECT_FLAG


def test_base_stream_args_third_element_is_no_read_timeout():
    """_base_stream_args()[2] is NO_READ_TIMEOUT_FLAG."""
    args = _base_stream_args()
    assert args[2] == NO_READ_TIMEOUT_FLAG


def test_base_stream_args_order_ua_reconnect_timeout():
    """_base_stream_args() maintains the required order: UA, reconnect, timeout."""
    args = _base_stream_args()
    assert args[0].startswith("--user-agent=")
    assert args[1] == RECONNECT_FLAG
    assert args[2] == NO_READ_TIMEOUT_FLAG
