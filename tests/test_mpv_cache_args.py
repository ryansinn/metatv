"""Regression and behavioral tests for MPVPlayer._compose_extra_args().

The "Stream cache size" setting (config.default_cache_size) must reach the mpv
command line, and auto-reconnect + UA must be present in every branch.

The canonical --user-agent is always prepended first so any user-supplied
--user-agent in mpv_extra_args appears later and wins (mpv honours last value).
The always-on RECONNECT_FLAG follows immediately after the UA — also before any
cache or user args.

Buffer flags when cache is "auto"/empty/unrecognized are determined by
config.buffer_profile:
  "reconnect_only" → no cache flags
  "modest"         → --cache=yes --cache-secs=10 --demuxer-readahead-secs=20
  "large"          → --cache=yes --cache-secs=30 --demuxer-readahead-secs=30
  <unknown>        → treated as "modest"

An explicit valid size (e.g. "100M") uses the legacy explicit-cache path
(--demuxer-max-bytes) regardless of the profile.

These tests execute _compose_extra_args() directly and assert the composed arg
list — the real observable behavior, not a substring of the source.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from metatv.core.http_headers import stream_user_agent
from metatv.core.players.mpv import MPVPlayer, RECONNECT_FLAG

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
# Reconnect flag presence — required in EVERY branch
# ---------------------------------------------------------------------------

def test_reconnect_flag_present_auto_modest():
    """RECONNECT_FLAG is present when cache='auto' + profile='modest'."""
    args = _player("auto", [], "modest")._compose_extra_args()
    assert RECONNECT_FLAG in args


def test_reconnect_flag_present_explicit_size():
    """RECONNECT_FLAG is present when an explicit size is configured."""
    args = _player("50M", [])._compose_extra_args()
    assert RECONNECT_FLAG in args


def test_reconnect_flag_present_garbage_size():
    """RECONNECT_FLAG is present even for unrecognized cache sizes."""
    args = _player("not-a-size", [])._compose_extra_args()
    assert RECONNECT_FLAG in args


# ---------------------------------------------------------------------------
# UA ordering
# ---------------------------------------------------------------------------

def test_ua_is_first():
    """Canonical UA must be the very first argument in every branch."""
    assert _player("auto", [])._compose_extra_args()[0] == _CANONICAL_UA
    assert _player("50M", [])._compose_extra_args()[0] == _CANONICAL_UA
    assert _player("???", [])._compose_extra_args()[0] == _CANONICAL_UA


def test_reconnect_flag_after_ua_before_cache():
    """RECONNECT_FLAG must follow the UA and precede any cache flags."""
    args = _player("auto", [], "modest")._compose_extra_args()
    ua_idx = args.index(_CANONICAL_UA)
    rc_idx = args.index(RECONNECT_FLAG)
    cache_indices = [i for i, a in enumerate(args) if a.startswith("--cache=") or a.startswith("--cache-secs")]
    assert ua_idx < rc_idx
    if cache_indices:
        assert rc_idx < min(cache_indices)


def test_user_args_last_with_explicit_size():
    """User args remain LAST (after cache flags) for an explicit size."""
    args = _player("100M", ["--foo"])._compose_extra_args()
    assert args[-1] == "--foo"
    assert args[0] == _CANONICAL_UA


def test_user_args_last_with_auto():
    """User args remain LAST even in the auto/profile branch."""
    args = _player("auto", ["--foo"], "modest")._compose_extra_args()
    assert args[-1] == "--foo"


# ---------------------------------------------------------------------------
# Buffer profile: "modest" (default)
# ---------------------------------------------------------------------------

def test_auto_modest_profile_cache_flags():
    """auto + modest → --cache=yes, --cache-secs=10, --demuxer-readahead-secs=20."""
    args = _player("auto", [], "modest")._compose_extra_args()
    assert "--cache=yes" in args
    assert "--cache-secs=10" in args
    assert "--demuxer-readahead-secs=20" in args
    assert not any(a.startswith("--demuxer-max-bytes=") for a in args)


# ---------------------------------------------------------------------------
# Buffer profile: "reconnect_only"
# ---------------------------------------------------------------------------

def test_reconnect_only_profile_no_cache_flags():
    """reconnect_only → UA + reconnect flag, but NO --cache= / --cache-secs= / --demuxer- flags."""
    args = _player("auto", [], "reconnect_only")._compose_extra_args()
    assert _CANONICAL_UA in args
    assert RECONNECT_FLAG in args
    assert not any(
        a.startswith("--cache=") or a.startswith("--cache-secs") or a.startswith("--demuxer-")
        for a in args
    )


# ---------------------------------------------------------------------------
# Buffer profile: "large"
# ---------------------------------------------------------------------------

def test_large_profile_cache_flags():
    """large → --cache=yes, --cache-secs=30, --demuxer-readahead-secs=30."""
    args = _player("auto", [], "large")._compose_extra_args()
    assert "--cache=yes" in args
    assert "--cache-secs=30" in args
    assert "--demuxer-readahead-secs=30" in args


# ---------------------------------------------------------------------------
# Buffer profile: unknown value falls back to "modest"
# ---------------------------------------------------------------------------

def test_unknown_profile_falls_back_to_modest():
    """An unknown profile must not crash and must behave like 'modest'."""
    args = _player("auto", [], "bogus-profile")._compose_extra_args()
    assert "--cache=yes" in args
    assert "--cache-secs=10" in args
    assert "--demuxer-readahead-secs=20" in args


# ---------------------------------------------------------------------------
# Explicit size: legacy --demuxer-max-bytes path (profile is irrelevant)
# ---------------------------------------------------------------------------

def test_configured_size_prepends_cache_flags_user_args_last():
    """A real size uses the legacy explicit-cache path; user args remain LAST."""
    args = _player("100M", ["--foo"])._compose_extra_args()
    assert "--cache=yes" in args
    assert "--demuxer-max-bytes=100MiB" in args
    assert "--demuxer-readahead-secs=30" in args
    assert args[-1] == "--foo"
    assert args[0] == _CANONICAL_UA


def test_explicit_size_ignores_profile():
    """An explicit size always uses the demuxer-max-bytes path, regardless of profile."""
    args_modest = _player("50M", [], "modest")._compose_extra_args()
    args_large = _player("50M", [], "large")._compose_extra_args()
    assert "--demuxer-max-bytes=50MiB" in args_modest
    assert "--demuxer-max-bytes=50MiB" in args_large
    # Neither should have --cache-secs (that's the profile path, not the explicit path).
    assert not any(a.startswith("--cache-secs") for a in args_modest)
    assert not any(a.startswith("--cache-secs") for a in args_large)


def test_size_suffix_conversion_variants():
    """K/M/G suffixes map to binary units; a bare number defaults to MiB."""
    assert "--demuxer-max-bytes=50MiB" in _player("50M", [])._compose_extra_args()
    assert "--demuxer-max-bytes=2GiB" in _player("2G", [])._compose_extra_args()
    assert "--demuxer-max-bytes=512KiB" in _player("512K", [])._compose_extra_args()
    assert "--demuxer-max-bytes=250MiB" in _player("250", [])._compose_extra_args()


# ---------------------------------------------------------------------------
# Garbage size: falls back to profile-driven flags (not a crash)
# ---------------------------------------------------------------------------

def test_garbage_size_falls_back_to_profile():
    """An unrecognized size must not raise; falls back to the profile flags."""
    args = _player("not-a-size", ["--foo"], "modest")._compose_extra_args()
    assert _CANONICAL_UA in args
    assert RECONNECT_FLAG in args
    assert "--foo" in args
    # Profile flags present (modest fallback)
    assert "--cache=yes" in args
    assert "--cache-secs=10" in args


def test_garbage_size_reconnect_only_profile():
    """Garbage size + reconnect_only → UA + reconnect, no cache flags, user args present."""
    args = _player("not-a-size", ["--foo"], "reconnect_only")._compose_extra_args()
    assert _CANONICAL_UA in args
    assert RECONNECT_FLAG in args
    assert "--foo" in args
    assert not any(a.startswith("--cache=") or a.startswith("--cache-secs") for a in args)


# ---------------------------------------------------------------------------
# Prebuffer flags
# ---------------------------------------------------------------------------

def test_prebuffer_off_no_cache_pause_flags():
    """prebuffer_before_play=False (default) → no --cache-pause-* flags in args."""
    args = _player("auto", [], "modest", prebuffer_before_play=False)._compose_extra_args()
    assert not any(a.startswith("--cache-pause-") for a in args)


def test_prebuffer_on_includes_required_flags():
    """prebuffer_before_play=True → --cache=yes, --cache-pause-initial=yes, --cache-pause-wait=<secs>."""
    args = _player("auto", [], "modest", prebuffer_before_play=True, prebuffer_wait_secs=15)._compose_extra_args()
    assert "--cache=yes" in args
    assert "--cache-pause-initial=yes" in args
    assert "--cache-pause-wait=15" in args


def test_prebuffer_wait_respected():
    """prebuffer_wait_secs is reflected in --cache-pause-wait value."""
    args = _player("auto", [], "modest", prebuffer_before_play=True, prebuffer_wait_secs=30)._compose_extra_args()
    assert "--cache-pause-wait=30" in args
    args2 = _player("auto", [], "modest", prebuffer_before_play=True, prebuffer_wait_secs=5)._compose_extra_args()
    assert "--cache-pause-wait=5" in args2


def test_prebuffer_flags_after_buffer_flags_before_user_args():
    """prebuffer flags appear AFTER buffer flags and BEFORE user_args."""
    user_arg = "--foo"
    args = _player("auto", [user_arg], "modest", prebuffer_before_play=True, prebuffer_wait_secs=15)._compose_extra_args()
    cache_pause_idx = args.index("--cache-pause-initial=yes")
    # A buffer flag (modest profile) must precede prebuffer flag
    cache_secs_idx = args.index("--cache-secs=10")
    user_arg_idx = args.index(user_arg)
    assert cache_secs_idx < cache_pause_idx
    assert cache_pause_idx < user_arg_idx


# ---------------------------------------------------------------------------
# Override-all
# ---------------------------------------------------------------------------

def test_override_all_returns_only_user_args():
    """mpv_args_override_all=True → _compose_extra_args returns exactly mpv_extra_args."""
    args = _player("auto", ["--foo"], "modest", mpv_args_override_all=True)._compose_extra_args()
    assert args == ["--foo"]


def test_override_all_strips_ua_reconnect_cache():
    """With override_all=True, canonical UA, RECONNECT_FLAG, and cache flags are ALL absent."""
    args = _player("auto", ["--foo"], "modest", mpv_args_override_all=True)._compose_extra_args()
    assert _CANONICAL_UA not in args
    assert RECONNECT_FLAG not in args
    assert not any(a.startswith("--cache=") or a.startswith("--cache-secs") for a in args)


def test_override_all_off_ua_present():
    """With override_all=False (default), canonical UA is still present."""
    args = _player("auto", ["--foo"], "modest", mpv_args_override_all=False)._compose_extra_args()
    assert _CANONICAL_UA in args


def test_override_all_empty_user_args():
    """override_all=True with no user args → empty list (not a crash)."""
    args = _player("auto", [], "modest", mpv_args_override_all=True)._compose_extra_args()
    assert args == []
