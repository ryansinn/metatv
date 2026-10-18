"""Behavioral tests for stream HTTP header parity.

Verifies that validation, diagnostics and mpv (which diagnostics also probes
codec/bitrate through) all use the same
canonical User-Agent (single source of truth in metatv.core.http_headers).

These are pure-core tests — no Qt, no DB, no fixtures needed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch


from metatv.core.http_headers import STREAM_HTTP_HEADERS, stream_user_agent
from metatv.core.players.mpv import MPVPlayer
import metatv.core.stream_diagnostics as _diag_mod
from metatv.core.stream_diagnostics import run_stream_diagnostic


# ---------------------------------------------------------------------------
# 1. Single source of truth
# ---------------------------------------------------------------------------

class TestSingleSourceOfTruth:
    def test_stream_user_agent_matches_dict(self):
        """stream_user_agent() must equal STREAM_HTTP_HEADERS['User-Agent']."""
        assert stream_user_agent() == STREAM_HTTP_HEADERS["User-Agent"]

    def test_xtream_re_exports_same_object(self):
        """xtream._DEFAULT_HEADERS must be the exact same object as STREAM_HTTP_HEADERS."""
        import metatv.providers.xtream as _xtream
        assert _xtream._DEFAULT_HEADERS is STREAM_HTTP_HEADERS

    def test_diagnostics_imports_same_object(self):
        """stream_diagnostics re-imports the same dict object (no copy)."""
        assert _diag_mod.STREAM_HTTP_HEADERS is STREAM_HTTP_HEADERS


# ---------------------------------------------------------------------------
# 2. mpv User-Agent header propagation
# ---------------------------------------------------------------------------

@dataclass
class _FakeConfig:
    """Minimal stand-in for Config — only the fields MPVPlayer reads."""

    default_cache_size: str = "auto"
    mpv_extra_args: list = field(default_factory=list)
    player_mode: str = "single-instance"
    close_player_when_finished: bool = False
    buffer_profile: str = "modest"


def _player(cache_size: str = "auto", extra_args: list[str] | None = None) -> MPVPlayer:
    return MPVPlayer(_FakeConfig(
        default_cache_size=cache_size,
        mpv_extra_args=extra_args if extra_args is not None else [],
    ))


class TestMpvUserAgent:
    def test_ua_present_with_auto_cache(self):
        """--user-agent appears even when cache is 'auto' (no cache flags)."""
        args = _player("auto")._compose_extra_args()
        assert f"--user-agent={stream_user_agent()}" in args

    def test_ua_present_with_configured_cache(self):
        """--user-agent appears alongside cache flags."""
        args = _player("50M")._compose_extra_args()
        assert f"--user-agent={stream_user_agent()}" in args

    def test_ua_before_cache_flags(self):
        """--user-agent must precede --cache=yes / --demuxer-max-bytes."""
        args = _player("50M")._compose_extra_args()
        ua_idx = args.index(f"--user-agent={stream_user_agent()}")
        # At least one cache flag must exist and come AFTER the UA.
        cache_indices = [i for i, a in enumerate(args) if a.startswith(("--cache=", "--demuxer-"))]
        assert cache_indices, "expected cache flags to be present"
        assert ua_idx < min(cache_indices), (
            f"--user-agent (idx {ua_idx}) must precede cache flags (min idx {min(cache_indices)})"
        )

    def test_custom_ua_overrides_canonical(self):
        """A user-supplied --user-agent appears AFTER the canonical one → mpv uses it (last wins)."""
        custom_ua = "--user-agent=CustomUA"
        args = _player("auto", [custom_ua])._compose_extra_args()
        canonical = f"--user-agent={stream_user_agent()}"
        assert canonical in args
        assert custom_ua in args
        assert args.index(canonical) < args.index(custom_ua), (
            "canonical UA must precede the user's so the user's wins"
        )

    def test_ua_before_user_args_when_no_cache(self):
        """With auto cache, canonical UA still precedes user_args."""
        args = _player("auto", ["--foo"])._compose_extra_args()
        ua_idx = args.index(f"--user-agent={stream_user_agent()}")
        foo_idx = args.index("--foo")
        assert ua_idx < foo_idx


# ---------------------------------------------------------------------------
# 4. diagnostics requests.get header propagation
# ---------------------------------------------------------------------------

class TestDiagnosticsRequestsHeaders:
    def test_run_stream_diagnostic_sends_canonical_headers(self):
        """run_stream_diagnostic must call requests.get with the canonical headers."""
        captured_kwargs: dict = {}

        def fake_get(url, **kwargs):
            captured_kwargs.update(kwargs)
            # Raise immediately so we exit early — we only care about the headers kwarg.
            raise __import__("requests").exceptions.ConnectionError("spy abort")

        with patch("metatv.core.stream_diagnostics.requests.get", side_effect=fake_get):
            result = run_stream_diagnostic("http://host.example/live/u/p/1.ts", timeout=1.0)

        assert "headers" in captured_kwargs, "requests.get must be called with headers="
        sent_headers = captured_kwargs["headers"]
        assert sent_headers.get("User-Agent") == stream_user_agent(), (
            f"requests.get headers['User-Agent'] must match canonical UA; got {sent_headers.get('User-Agent')!r}"
        )

    def test_measure_baseline_sends_canonical_headers(self):
        """_measure_baseline must also pass headers to requests.get."""
        from metatv.core.stream_diagnostics import _measure_baseline

        captured_kwargs: dict = {}

        def fake_get(url, **kwargs):
            captured_kwargs.update(kwargs)
            raise __import__("requests").exceptions.ConnectionError("spy abort")

        with patch("metatv.core.stream_diagnostics.requests.get", side_effect=fake_get):
            result = _measure_baseline("http://speed.cloudflare.com/__down", timeout=1.0)

        assert result is None  # error → None, no crash
        assert "headers" in captured_kwargs
        assert captured_kwargs["headers"].get("User-Agent") == stream_user_agent()
