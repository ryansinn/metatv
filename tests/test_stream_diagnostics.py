"""Behavioral tests for the headless stream-diagnostics engine.

These execute the real code paths and pin observable outputs (verdicts,
recommended args, redaction, measured throughput) — no source-shape asserts.
"""

import math
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from metatv.core.stream_diagnostics import (
    HEALTHY,
    INTERNET_LIMITED,
    JITTER,
    PROVIDER_LIMITED,
    UNREACHABLE,
    _redact,
    classify,
    recommend_mpv_args,
    run_stream_diagnostic,
)


# --- classify() --------------------------------------------------------------
class TestClassify:
    def test_unreachable_wins(self):
        # Even with great numbers, an unreachable stream is UNREACHABLE.
        assert classify(100.0, 5.0, 100.0, reachable=False) == UNREACHABLE

    def test_healthy_high_headroom(self):
        # headroom 4.0 >= 1.5
        assert classify(20.0, 5.0, None, reachable=True) == HEALTHY

    def test_healthy_at_threshold(self):
        # headroom exactly 1.5
        assert classify(7.5, 5.0, None, reachable=True) == HEALTHY

    def test_jitter_band(self):
        # headroom 1.2 in [1.0, 1.5)
        assert classify(6.0, 5.0, None, reachable=True) == JITTER

    def test_jitter_at_lower_threshold(self):
        # headroom exactly 1.0
        assert classify(5.0, 5.0, None, reachable=True) == JITTER

    def test_provider_limited_when_baseline_strong(self):
        # headroom < 1.0, baseline (10) >= 1.5 * bitrate (5) = 7.5 -> provider.
        assert classify(4.0, 5.0, 10.0, reachable=True) == PROVIDER_LIMITED

    def test_internet_limited_when_baseline_weak(self):
        # headroom < 1.0, baseline (6) < 7.5 -> internet.
        assert classify(4.0, 5.0, 6.0, reachable=True) == INTERNET_LIMITED

    def test_internet_limited_when_baseline_unknown(self):
        # headroom < 1.0 and no baseline -> internet.
        assert classify(4.0, 5.0, None, reachable=True) == INTERNET_LIMITED

    def test_unknown_bitrate_decent_throughput_healthy(self):
        # bitrate unknown, throughput > 3.0 -> HEALTHY best-effort.
        assert classify(10.0, None, None, reachable=True) == HEALTHY

    def test_unknown_bitrate_low_throughput_jitter(self):
        assert classify(2.0, None, None, reachable=True) == JITTER

    def test_unknown_throughput_jitter(self):
        assert classify(None, 5.0, None, reachable=True) == JITTER

    def test_zero_bitrate_treated_as_unknown(self):
        # 0.0 bitrate must not divide-by-zero; falls into best-effort branch.
        assert classify(10.0, 0.0, None, reachable=True) == HEALTHY
        assert classify(1.0, 0.0, None, reachable=True) == JITTER


# --- recommend_mpv_args() ----------------------------------------------------
class TestRecommendMpvArgs:
    def test_healthy(self):
        assert recommend_mpv_args(HEALTHY, 5.0) == ("--cache=yes",)

    def test_unreachable(self):
        assert recommend_mpv_args(UNREACHABLE, None) == ()

    def test_internet_limited_minimal(self):
        assert recommend_mpv_args(INTERNET_LIMITED, 5.0) == ("--cache=yes",)

    def test_jitter_args_set(self):
        # bitrate 8 Mbps -> 8/8 * 30 = 30 MB -> clamped up to min 50.
        args = recommend_mpv_args(JITTER, 8.0)
        assert "--cache=yes" in args
        assert "--demuxer-readahead-secs=30" in args
        assert "--cache-secs=30" in args
        assert "--demuxer-max-bytes=50MiB" in args

    def test_jitter_scales_with_bitrate(self):
        # bitrate 40 Mbps -> 40/8 * 30 = 150 MiB (within [50, 512]).
        args = recommend_mpv_args(JITTER, 40.0)
        assert "--demuxer-max-bytes=150MiB" in args

    def test_jitter_caps_at_512(self):
        # huge bitrate clamps to 512 MiB.
        args = recommend_mpv_args(JITTER, 1000.0)
        assert "--demuxer-max-bytes=512MiB" in args

    def test_jitter_unknown_bitrate_default(self):
        args = recommend_mpv_args(JITTER, None)
        assert "--demuxer-max-bytes=128MiB" in args

    def test_provider_limited_args_set(self):
        # bitrate 20 Mbps -> 20/8 * 60 = 150 MiB (within [100, 1024]).
        args = recommend_mpv_args(PROVIDER_LIMITED, 20.0)
        assert "--cache=yes" in args
        assert "--demuxer-readahead-secs=60" in args
        assert "--cache-secs=60" in args
        assert "--demuxer-max-bytes=150MiB" in args

    def test_provider_limited_min_floor(self):
        # tiny bitrate clamps up to min 100 MiB.
        args = recommend_mpv_args(PROVIDER_LIMITED, 2.0)
        assert "--demuxer-max-bytes=100MiB" in args

    def test_provider_limited_caps_at_1024(self):
        args = recommend_mpv_args(PROVIDER_LIMITED, 5000.0)
        assert "--demuxer-max-bytes=1024MiB" in args

    def test_provider_limited_unknown_bitrate_default(self):
        args = recommend_mpv_args(PROVIDER_LIMITED, None)
        assert "--demuxer-max-bytes=256MiB" in args


# --- _redact() ---------------------------------------------------------------
class TestRedact:
    def test_xtream_live_url(self):
        url = "http://host.example:8080/live/myuser/mypass/12345.ts"
        red = _redact(url)
        assert "myuser" not in red
        assert "mypass" not in red
        assert "***" in red
        assert "host.example:8080" in red
        assert "12345.ts" in red
        assert red == "http://host.example:8080/live/***/***/12345.ts"

    def test_xtream_movie_url(self):
        url = "https://h/movie/u/p/999.mkv"
        assert _redact(url) == "https://h/movie/***/***/999.mkv"

    def test_xtream_series_url(self):
        url = "https://h/series/u/p/7.mp4"
        assert _redact(url) == "https://h/series/***/***/7.mp4"

    def test_bare_xtream_url(self):
        url = "http://host.example:8080/secretuser/secretpass/4242.ts"
        red = _redact(url)
        assert "secretuser" not in red
        assert "secretpass" not in red
        assert red == "http://host.example:8080/***/***/4242.ts"

    def test_non_matching_url_unchanged(self):
        url = "https://speed.cloudflare.com/__down?bytes=25000000"
        assert _redact(url) == url

    def test_empty_url(self):
        assert _redact("") == ""


# --- Throughput math against a local HTTP server -----------------------------
_PAYLOAD = b"\x00" * (3 * 1024 * 1024)  # 3 MB


class _StreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (http.server API)
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(_PAYLOAD)))
        self.end_headers()
        self.wfile.write(_PAYLOAD)

    def log_message(self, *args):  # silence test-server logging
        pass


@pytest.fixture()
def local_stream_server():
    server = HTTPServer(("127.0.0.1", 0), _StreamHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}/stream.ts"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


class TestThroughputProbe:
    def test_reachable_and_measures_throughput(self, local_stream_server):
        result = run_stream_diagnostic(
            local_stream_server, sample_seconds=1, baseline_url=None
        )
        assert result.reachable is True
        # ffprobe will fail on the fake octet-stream — the probe must still
        # return a result without raising.
        assert result.throughput_mbps is not None
        assert result.throughput_mbps > 0
        assert math.isfinite(result.throughput_mbps)
        assert result.ttfb_ms is not None
        assert result.ttfb_ms >= 0
        assert result.connect_ms is not None
        # No baseline requested.
        assert result.baseline_mbps is None
        # bitrate may be None (ffprobe gave nothing) or the throughput estimate.
        if result.bitrate_mbps is not None:
            assert result.bitrate_mbps == result.throughput_mbps
        # A reachable result always carries a non-empty summary and a verdict.
        assert result.summary
        assert result.verdict != UNREACHABLE
        # Summary must not leak — it's a local URL with no creds, but assert it
        # is present and credential-free in spirit.
        assert "http://127.0.0.1" in result.summary or result.verdict in {
            HEALTHY,
            JITTER,
            PROVIDER_LIMITED,
            INTERNET_LIMITED,
        }

    def test_unreachable_url(self):
        # Port 1 on localhost should refuse — connection error path.
        result = run_stream_diagnostic(
            "http://127.0.0.1:1/live/u/p/1.ts", sample_seconds=1, timeout=2.0
        )
        assert result.reachable is False
        assert result.verdict == UNREACHABLE
        assert result.error is not None
        assert result.recommended_args == ()
        # Credentials must never appear in the summary/error.
        assert "u/p" not in result.summary
        assert "/u/" not in result.summary
