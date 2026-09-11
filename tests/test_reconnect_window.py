"""mpv's reconnect window has to cover the source's connection lag, not
ffmpeg's default backoff.

Measured 2026-09-11 on this machine (mpv 0.41.0 / ffmpeg 9.0.1) — do not
re-derive, build on these numbers.

Against a local server that always answers HTTP 500: ``reconnect_delay_max=8``
-> the server saw 5 requests at +0,+0,+1,+4,+11s and ffmpeg then gave up (11s
window). ``reconnect_delay_max=30`` -> 6 requests, the last at +26s (26s
window). ffmpeg's rule: the delay starts at 0, after each failed attempt
``delay = 1 + 2*delay``, and it STOPS once that next delay exceeds the max.
So with 60 the schedule is +0,+0,+1,+4,+11,+26,+57s — 7 requests, a 57s
window.

The PLAY-10 comment ("+1,+3,+7,+15,+23s ... retries about every 10s until the
panel frees the slot") and the test this module replaces
(``test_reconnect_delay_max_lowered_for_same_provider_switching``) encoded a
wrong model: lowering 30 -> 8 SHRANK the window from 26s to 11s. The owner's
one-connection panel answers HTTP 500 ("failed to redirect to stream origin")
to any new connection for 14-26s after the previous one closes (#635
measurement), up to ~40s (2026-09-07 log) — every window below 60 fails that.

Against a local server that ACCEPTS the TCP connection and never sends a
byte: with ``rw_timeout=10000000`` mpv hung for >60s with no reconnect at all
(rw_timeout is not applied on this read path). With ``timeout=10000000`` (the
tcp protocol's socket-I/O timeout, which lavf options pass through to the tcp
layer) ffmpeg logged ``Error reading HTTP response: Connection timed out``
every 10s and entered the reconnect schedule. So PLAY-12's ``rw_timeout``
never worked and the held-socket case was an indefinite hang; ``timeout=`` is
the option that fires — see :func:`test_a_held_socket_times_out_into_the_reconnect_schedule`.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
import threading
import time

import pytest

from metatv.core.players.mpv import (
    RECONNECT_DELAY_MAX_S,
    RECONNECT_FLAG,
    STREAM_IO_TIMEOUT_S,
)


def test_ffmpeg_retry_window_covers_the_measured_slot_lag():
    """Floor + the property that would break: 8 gives 11s and fails, 30 gives
    26s and fails, 60 gives 57s and passes — the panel takes up to ~40s."""
    d = 0
    total = 0
    while d <= RECONNECT_DELAY_MAX_S:
        total += d
        d = 1 + 2 * d
    assert total >= 40, f"mpv gives up after {total}s; the panel takes up to ~40s to free a slot"


def test_the_flag_is_composed_from_the_constants():
    assert f"reconnect_delay_max={RECONNECT_DELAY_MAX_S}" in RECONNECT_FLAG
    assert f"timeout={STREAM_IO_TIMEOUT_S * 1_000_000}" in RECONNECT_FLAG
    assert "rw_timeout" not in RECONNECT_FLAG


@pytest.mark.skipif(shutil.which("mpv") is None, reason="needs a real mpv")
def test_a_held_socket_times_out_into_the_reconnect_schedule():
    """The test that would have caught ``rw_timeout`` being a no-op (PLAY-12).

    A raw TCP server accepts the connection, reads the request once, and then
    never answers — exactly the owner's one-connection panel holding a second
    connection open with zero bytes. mpv must give up on the silent socket via
    ``timeout=`` rather than hanging indefinitely (measured >60s pre-fix).
    Takes ~STREAM_IO_TIMEOUT_S locally; skipped on CI (no mpv there).
    """
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    def _serve() -> None:
        try:
            conn, _ = server_sock.accept()
        except OSError:
            return
        try:
            conn.recv(4096)
            # Never reply — hold the connection open. A blocking recv() here
            # doubles as "sleep until the client closes": mpv (or our own
            # kill()) closing the socket is what unblocks it.
            while conn.recv(4096):
                pass
        except OSError:
            pass
        finally:
            conn.close()

    threading.Thread(target=_serve, daemon=True).start()

    mpv_bin = shutil.which("mpv")
    launched_at = time.monotonic()
    proc = subprocess.Popen(
        [mpv_bin, "--no-config", "--vo=null", "--ao=null", "--ytdl=no",
         "--msg-level=all=warn", "--idle=once", RECONNECT_FLAG,
         f"http://127.0.0.1:{port}/x.mp4"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )

    lines: list[str] = []
    found = threading.Event()

    def _read_output() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            lines.append(line)
            if "Connection timed out" in line:
                found.set()
                return

    threading.Thread(target=_read_output, daemon=True).start()

    try:
        found.wait(STREAM_IO_TIMEOUT_S + 15)
        elapsed = time.monotonic() - launched_at
        assert found.is_set(), (
            f"'Connection timed out' never appeared in mpv output within "
            f"{STREAM_IO_TIMEOUT_S + 15}s — a rw_timeout-style no-op regression?\n"
            + "".join(lines))
        assert elapsed <= STREAM_IO_TIMEOUT_S + 10, (
            f"the timeout fired at {elapsed:.1f}s, later than the "
            f"STREAM_IO_TIMEOUT_S+10={STREAM_IO_TIMEOUT_S + 10}s budget")
    finally:
        proc.kill()
        proc.wait()
        try:
            server_sock.close()
        except OSError:
            pass
