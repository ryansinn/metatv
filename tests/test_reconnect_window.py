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
the option that fires — and PLAY-18 removed it again, because on the owner's source a reconnect
is worse than a stall (see :func:`test_there_is_no_socket_read_timeout_on_purpose`).
"""

from __future__ import annotations



from metatv.core.players.mpv import (
    RECONNECT_DELAY_MAX_S,
    RECONNECT_FLAG,
)
from metatv.gui.playback_start_watch import ffmpeg_retry_window_s


def test_ffmpeg_retry_window_covers_the_measured_slot_lag():
    """Floor + the property that would break: 8 gives 11s and fails, 30 gives
    26s and fails, 60 gives 57s and passes — the panel takes up to ~40s."""
    total = ffmpeg_retry_window_s(RECONNECT_DELAY_MAX_S)
    assert total >= 40, f"mpv gives up after {total}s; the panel takes up to ~40s to free a slot"


def test_the_schedule_helper_matches_the_measurements():
    """The three ``reconnect_delay_max`` values measured 2026-09-11 (see the
    module docstring): 8 -> 11s, 30 -> 26s, 60 -> 57s. PLAY-16 derives
    ``OPENING_AFTER_TICKS`` from this same helper — pinned here so a change to
    the formula shows up against the real measurements, not just itself."""
    assert ffmpeg_retry_window_s(8) == 11
    assert ffmpeg_retry_window_s(30) == 26
    assert ffmpeg_retry_window_s(60) == 57


def test_the_flag_is_composed_from_the_constants():
    assert f"reconnect_delay_max={RECONNECT_DELAY_MAX_S}" in RECONNECT_FLAG
    assert "rw_timeout" not in RECONNECT_FLAG


def test_there_is_no_socket_read_timeout_on_purpose():
    """PLAY-18. A read timeout (PLAY-14's ``timeout=20s``) turned a stalled
    origin into a reconnect, and on the owner's source every reconnect was
    held unanswered — "it only plays the first 2 minutes of anything"
    (2026-09-13 14:46-14:49: burst to 46 MB, 20s stall, six held reconnects).
    With no read timeout the same source played a 2.6-hour queue with zero
    reconnects (2026-09-10 00:23-03:00). Neither spelling may come back:
    ``rw_timeout`` was a no-op, ``timeout`` was the regression."""
    opts = RECONNECT_FLAG.split("=", 1)[1].split(",")
    assert not any(o.startswith(("timeout=", "rw_timeout=")) for o in opts), opts
