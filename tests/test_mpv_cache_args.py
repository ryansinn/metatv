"""Regression: the "Stream cache size" setting (config.default_cache_size) must
reach the mpv command line.

The bug: MPVPlayer launched mpv with only config.mpv_extra_args, so the saved
default_cache_size control did nothing. MPVPlayer._compose_extra_args() now maps
a non-"auto" cache size to --cache=yes / --demuxer-max-bytes=<N>iB /
--demuxer-readahead-secs=30 and appends the user's args last (so user args win).

The canonical --user-agent is always prepended first so any user-supplied
--user-agent in mpv_extra_args appears later and wins (mpv honours last value).

These tests execute _compose_extra_args() directly and assert the composed arg
list — the real observable behavior, not a substring of the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metatv.core.http_headers import stream_user_agent
from metatv.core.players.mpv import MPVPlayer

_CANONICAL_UA = f"--user-agent={stream_user_agent()}"


@dataclass
class _FakeConfig:
    """Minimal stand-in for Config — MPVPlayer reads only these fields."""

    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    mpv_socket_path: str = "/tmp/metatv-test.sock"
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False


def _player(cache_size: str, extra_args: list[str]) -> MPVPlayer:
    return MPVPlayer(_FakeConfig(default_cache_size=cache_size, mpv_extra_args=extra_args))


def test_auto_preserves_stock_behavior():
    """'auto' adds only the canonical UA + user args — no cache flags."""
    player = _player("auto", ["--foo"])
    args = player._compose_extra_args()
    assert _CANONICAL_UA in args
    assert "--foo" in args
    # No cache-related flags.
    assert not any(a.startswith("--cache=") or a.startswith("--demuxer-") for a in args)
    # User arg must come after the canonical UA.
    assert args.index(_CANONICAL_UA) < args.index("--foo")


def test_falsy_cache_size_preserves_stock_behavior():
    """An empty cache size behaves like 'auto' — canonical UA + user args, no cache flags."""
    player = _player("", ["--foo"])
    args = player._compose_extra_args()
    assert _CANONICAL_UA in args
    assert "--foo" in args
    assert not any(a.startswith("--cache=") or a.startswith("--demuxer-") for a in args)


def test_configured_size_prepends_cache_flags_user_args_last():
    """A real size prepends cache-resilience flags; user args remain LAST so they win."""
    player = _player("100M", ["--foo"])
    args = player._compose_extra_args()

    assert "--cache=yes" in args
    assert "--demuxer-max-bytes=100MiB" in args
    assert "--demuxer-readahead-secs=30" in args
    # User override wins: their arg must be the final element.
    assert args[-1] == "--foo"
    # Canonical UA must be first in the list.
    assert args[0] == _CANONICAL_UA


def test_size_suffix_conversion_variants():
    """K/M/G suffixes map to binary units; a bare number defaults to MiB."""
    assert "--demuxer-max-bytes=50MiB" in _player("50M", [])._compose_extra_args()
    assert "--demuxer-max-bytes=2GiB" in _player("2G", [])._compose_extra_args()
    assert "--demuxer-max-bytes=512KiB" in _player("512K", [])._compose_extra_args()
    assert "--demuxer-max-bytes=250MiB" in _player("250", [])._compose_extra_args()


def test_garbage_size_falls_back_to_user_args():
    """An unrecognized value must not raise; returns canonical UA + user args only."""
    player = _player("not-a-size", ["--foo"])
    args = player._compose_extra_args()
    assert _CANONICAL_UA in args
    assert "--foo" in args
    assert not any(a.startswith("--cache=") or a.startswith("--demuxer-") for a in args)


def test_garbage_size_no_user_args_returns_only_ua():
    """Garbage with no user args yields only the canonical UA (no crash, no cache flags)."""
    player = _player("???", [])
    args = player._compose_extra_args()
    assert args == [_CANONICAL_UA]
