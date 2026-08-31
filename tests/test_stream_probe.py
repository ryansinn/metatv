"""Is the stream dead, or did the provider just refuse to answer?

The owner abandoned the events work once because *"there was hardly anything
ever actually on those channels, just dead air/black screens even when it said
there was an event."* This module is the check for that, and the fixtures below
are REAL ffmpeg output captured from the owner's ProSat event channels.

The distinction that shapes the whole design was found by running it. A stream
that looked dead was returning **HTTP 403** — the provider declining the
connection, not an empty picture. Every account on this install allows ONE
connection, so a sweep run while something is playing would refuse on every
row; recording those as "dead" would condemn 125 working channels on the
strength of the user having pressed Play.

So there are two families of verdict and they must never be conflated:

    picture      dead / black / frozen / live      we saw what was there
    connection   refused / gone / unknown          we never got to look
"""

import pytest

from metatv.core import stream_probe as sp

# ── Real captures ───────────────────────────────────────────────────────────
# Trimmed from actual runs against line.ottcst.com on 2026-08-30.

LIVE_1080P = """\
  Stream #0:0 -> #0:0 (h264 (native) -> wrapped_avframe (native))
  Stream #0:0: Video: wrapped_avframe, yuv420p(progressive), 1920x1080 [SAR 1:1 DAR 16:9], q=2-31, 200 kb/s, 25 fps, 25 tbn
  Stream #0:1: Audio: pcm_s16le, 44100 Hz, stereo, s16, 1411 kb/s
[Parsed_blackdetect_0 @ 0x7fbe70004080] black_start:0.0586 black_end:1.2986 black_duration:1.24
frame=   74 fps=0.0 q=-0.0 Lsize=N/A time=00:00:03.00 bitrate=N/A speed=32.7x
"""

REFUSED_403 = """\
[http @ 0x5612bd7cb2c0] HTTP error 403 Forbidden
[in#0 @ 0x5612bd7ca9c0] Error opening input: Server returned 403 Forbidden (access denied)
Error opening input file http://line.ottcst.com/live/USER/PASS/283752.ts.
Error opening input files: Server returned 403 Forbidden (access denied)
"""

# Shaped from the same run's detector output; a slate holds one frame.
FROZEN_SLATE = """\
  Stream #0:0: Video: wrapped_avframe, yuv420p(progressive), 1280x720, 25 fps, 25 tbn
[Parsed_freezedetect_1 @ 0x55d0] lavfi.freezedetect.freeze_start: 0.04
[Parsed_freezedetect_1 @ 0x55d0] lavfi.freezedetect.freeze_duration: 3.96
frame=   99 fps=0.0 q=-0.0 Lsize=N/A time=00:00:04.00 bitrate=N/A
"""

BLACK_SCREEN = """\
  Stream #0:0: Video: wrapped_avframe, yuv420p(progressive), 1920x1080, 25 fps, 25 tbn
[Parsed_blackdetect_0 @ 0x7fbe] black_start:0 black_end:3.92 black_duration:3.92
[Parsed_silencedetect_0 @ 0x7fbf] silence_start: 0
[Parsed_silencedetect_0 @ 0x7fbf] silence_end: 3.9 | silence_duration: 3.9
frame=   99 fps=0.0 q=-0.0 Lsize=N/A time=00:00:04.00 bitrate=N/A
"""

OPENED_NO_FRAMES = """\
  Stream #0:0: Video: h264, yuv420p, 1920x1080, 25 fps
[in#0 @ 0x55d0] Error during demuxing: Input/output error
"""

NOT_FOUND = """\
[http @ 0x5612] HTTP error 404 Not Found
[in#0 @ 0x5612] Error opening input: Server returned 404 Not Found
"""

CONNECTION_REFUSED = """\
[tcp @ 0x5612] Connection to tcp://line.example.com:80 failed: Connection refused
[in#0 @ 0x5612] Error opening input: Connection refused
"""


# --------------------------------------------------------------------------
# The picture verdicts
# --------------------------------------------------------------------------

def test_a_moving_picture_is_live():
    r = sp.interpret(LIVE_1080P, 0, seconds=3)
    assert r.verdict == sp.LIVE
    assert r.frames == 74
    assert r.resolution == "1920x1080"
    assert not r.is_failure and not r.is_inconclusive


def test_a_brief_black_run_does_not_condemn_a_live_stream():
    """1.24s of black in a 3s sample is 41% — a bumper or a fade between
    segments, not dead air. The verdict is a FRACTION of the sample for exactly
    this reason; a fixed threshold would call this channel dead."""
    r = sp.interpret(LIVE_1080P, 0, seconds=3)
    assert r.black_seconds == 1.24
    assert r.verdict == sp.LIVE


def test_a_mostly_black_sample_is_black():
    r = sp.interpret(BLACK_SCREEN, 0, seconds=4)
    assert r.verdict == sp.BLACK
    assert r.is_failure
    assert "3.9s of a 4s sample" in r.detail


def test_a_still_picture_is_frozen():
    r = sp.interpret(FROZEN_SLATE, 0, seconds=4)
    assert r.verdict == sp.FROZEN
    assert r.frozen and r.is_failure


def test_opened_but_produced_nothing_is_dead():
    r = sp.interpret(OPENED_NO_FRAMES, 1, seconds=3)
    assert r.verdict == sp.DEAD
    assert r.frames == 0 and r.is_failure


# --------------------------------------------------------------------------
# The connection verdicts — the distinction that shapes the feature
# --------------------------------------------------------------------------

def test_a_403_is_refused_not_dead():
    """Found by running it. This account allows ONE connection, so a sweep
    started while something is playing refuses on every row — and recording
    those as dead would condemn 125 working channels because the user pressed
    Play."""
    r = sp.interpret(REFUSED_403, 251, seconds=3)
    assert r.verdict == sp.REFUSED
    assert not r.is_failure, "a refusal must never count as 'nothing to watch'"
    assert r.is_inconclusive
    assert "in use" in r.detail


@pytest.mark.parametrize("stderr", [NOT_FOUND, CONNECTION_REFUSED])
def test_unreachable_is_gone_not_dead(stderr):
    r = sp.interpret(stderr, 1, seconds=3)
    assert r.verdict == sp.GONE
    assert not r.is_failure and r.is_inconclusive


def test_the_two_families_do_not_overlap():
    """A verdict is about the picture or about the connection, never both."""
    assert not (sp.FAILED_VERDICTS & sp.INCONCLUSIVE_VERDICTS)
    assert sp.LIVE not in sp.FAILED_VERDICTS
    assert sp.LIVE not in sp.INCONCLUSIVE_VERDICTS


def test_a_refusal_is_ruled_on_before_the_frame_count():
    """Order matters: a 403 also has zero frames, and the frame test would
    otherwise reach it first and call it dead."""
    r = sp.interpret(REFUSED_403, 251, seconds=3)
    assert r.frames == 0
    assert r.verdict == sp.REFUSED


# --------------------------------------------------------------------------
# Silence — recorded, never decisive
# --------------------------------------------------------------------------

def test_silence_alone_does_not_make_a_stream_dead():
    """A studio feed between segments is quiet and still live. Silence is
    corroboration for a picture verdict, never one on its own."""
    silent_but_moving = LIVE_1080P + (
        "[Parsed_silencedetect_0 @ 0x1] silence_end: 3 | silence_duration: 3.0\n")
    r = sp.interpret(silent_but_moving, 0, seconds=3)
    assert r.silent_seconds == 3.0
    assert r.verdict == sp.LIVE
    assert "3.0s silent" in r.detail


# --------------------------------------------------------------------------
# Running it
# --------------------------------------------------------------------------

def test_a_missing_ffmpeg_is_unknown_not_dead(monkeypatch):
    """ffmpeg is not a hard dependency — mpv is. Absent tooling means the
    feature is unavailable, not that every channel is dead."""
    monkeypatch.setattr(sp, "ffmpeg_available", lambda: False)
    r = sp.probe_stream("http://x/1.ts")
    assert r.verdict == sp.UNKNOWN
    assert not r.is_failure


def test_an_empty_url_is_unknown():
    assert sp.probe_stream("").verdict == sp.UNKNOWN


def test_a_timeout_is_recorded_as_unreached(monkeypatch):
    """It answered by hanging, and a busy provider hangs too."""
    import subprocess

    monkeypatch.setattr(sp, "ffmpeg_available", lambda: True)

    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=5)

    monkeypatch.setattr(subprocess, "run", _boom)
    r = sp.probe_stream("http://x/1.ts")
    assert r.verdict == sp.GONE
    assert not r.is_failure


def test_the_command_carries_all_three_detectors():
    """One invocation, so the extra signals cost nothing."""
    cmd = " ".join(sp._build_command("http://x/1.ts", 3))
    assert "blackdetect" in cmd
    assert "freezedetect" in cmd
    assert "silencedetect" in cmd
    assert "-rw_timeout" in cmd, (
        "without a socket timeout a hung connection sits until the outer "
        "timeout, turning a 1.2s answer into 17s")
    assert "-t 3" in cmd


# --------------------------------------------------------------------------
# Settings — the thresholds are the owner's, not mine
# --------------------------------------------------------------------------

class _Cfg:
    signal_sample_seconds = 6
    signal_black_fraction = 0.8
    signal_black_pixel_threshold = 0.25
    signal_freeze_seconds = 3


def test_settings_come_from_config():
    s = sp.ProbeSettings.from_config(_Cfg())
    assert (s.sample_seconds, s.black_fraction) == (6, 0.8)
    assert (s.black_pixel_threshold, s.freeze_seconds) == (0.25, 3)


def test_a_freeze_longer_than_the_sample_is_clamped():
    """Otherwise the setting silently does nothing — freezedetect can never
    observe 10 motionless seconds inside a 4-second sample."""
    class _Bad:
        signal_sample_seconds = 4
        signal_freeze_seconds = 10
    assert sp.ProbeSettings.from_config(_Bad()).freeze_seconds == 4


def test_an_older_config_still_yields_the_shipped_defaults():
    """A config file on disk can predate the code that reads it."""
    s = sp.ProbeSettings.from_config(object())
    assert s.sample_seconds == sp.DEFAULT_SAMPLE_SECONDS
    assert 0 < s.black_fraction <= 1


def test_the_black_fraction_actually_changes_the_verdict():
    """The setting has to reach the ruling, not just be stored."""
    lenient = sp.interpret(BLACK_SCREEN, 0, seconds=4, black_fraction=0.99)
    strict = sp.interpret(BLACK_SCREEN, 0, seconds=4, black_fraction=0.5)
    assert strict.verdict == sp.BLACK
    assert lenient.verdict == sp.LIVE, (
        "3.92s of 4s is 98% — a 99% threshold must let it through")


def test_the_thresholds_reach_the_ffmpeg_command():
    cmd = " ".join(sp._build_command("u", 5, black_pixel=0.25, freeze_seconds=3))
    assert "pix_th=0.25" in cmd
    assert "freezedetect=n=-60dB:d=3" in cmd


def test_settings_are_frozen():
    """A worker reading live settings mid-sweep would judge the first half of a
    run by one rule and the second half by another."""
    import dataclasses
    s = sp.ProbeSettings()
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.sample_seconds = 99
