"""Does this stream actually carry a picture, or is it dead air?

The owner abandoned the events work once already, and not because the view was
missing: *"the data was unreliable and inconsistent and there was hardly
anything ever actually on those channels, just dead air/black screens even when
it said there was an event."* A listing that says a fight is on is worth
nothing if the stream behind it is a black rectangle.

Four failure modes, all of them measured against the owner's real ProSat event
channels before this module existed:

===============  =========================================  ============
no video         ffmpeg exits non-zero, zero frames decoded  ~1.2 s
black picture    ``blackdetect`` — 1.1 s black in a 6 s dip  ~4-10 s
frozen picture   ``freezedetect`` — a static slate            ~9 s
silence          ``silencedetect`` — a real event has crowd   free
===============  =========================================  ============

One ffmpeg invocation carries all four filters, so the extra signals cost
nothing. Silence alone is NOT a failure — a studio feed between segments is
quiet and still live — it is recorded as corroboration for the picture verdict.

Why this is deliberately not part of playback
---------------------------------------------
Every provider on the owner's account has ``max_connections = 1``. A probe
spends THE connection, so it cannot run while something is playing and cannot
run in parallel with itself. That is a scheduling problem for the caller; this
module does one stream and returns.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass

from loguru import logger

#: Seconds of stream to sample. Two is enough for every detector to fire —
#: measured 49 decoded frames at 1080p — and the wall-clock cost is dominated by
#: connect + buffer, not by this number.
DEFAULT_SAMPLE_SECONDS = 3

#: Hard ceiling per probe, on top of the sample. A stream that has not produced
#: a frame by then is answering the question by not answering it.
_TIMEOUT_MARGIN_SECONDS = 14

#: Socket read timeout handed to ffmpeg (microseconds). Without it a hung
#: connection sits until the outer timeout, turning a 1.2 s "dead" into 17 s.
_RW_TIMEOUT_US = 8_000_000

#: A picture darker than this fraction of full scale counts as black.
_BLACK_PIXEL_THRESHOLD = 0.10
#: Minimum run of black before it is reported, in seconds.
_BLACK_MIN_DURATION = 0.5
#: Frames identical to this tolerance for this long count as frozen.
_FREEZE_NOISE_DB = "-60dB"
_FREEZE_MIN_DURATION = 2
_SILENCE_NOISE_DB = "-50dB"
_SILENCE_MIN_DURATION = 2

#: Fraction of the sample that must be black before the verdict is "black"
#: rather than "live". A channel bumper or a fade between segments is black for
#: a moment; half the sample is not a bumper.
_BLACK_VERDICT_RATIO = 0.5

_FRAME_RE = re.compile(r"frame=\s*(\d+)")
_RESOLUTION_RE = re.compile(r"\b(\d{3,4})x(\d{3,4})\b")
_BLACK_DURATION_RE = re.compile(r"black_duration:([0-9.]+)")
_FREEZE_START_RE = re.compile(r"freeze_start")
_SILENCE_DURATION_RE = re.compile(r"silence_duration:\s*([0-9.]+)")

#: Verdicts about the PICTURE — we connected and saw what was there.
DEAD = "dead"          # opened fine, produced no frames at all
BLACK = "black"         # a picture, and it is a black rectangle
FROZEN = "frozen"       # a picture, and it never moves — a slate
LIVE = "live"           # a moving picture

#: Verdicts about the CONNECTION — we never saw the picture, so these say
#: nothing at all about whether the stream has content.
REFUSED = "refused"     # 401/403 — auth, or the connection budget is spent
GONE = "gone"           # 404 / host down — the channel is not there
UNKNOWN = "unknown"     # could not run the probe

#: Verdicts that mean "there is nothing to watch here". REFUSED and GONE are
#: deliberately absent: a 403 is the provider declining to answer, and marking a
#: channel dead on it would be a lie — the likeliest cause on this account is
#: that its ONE connection was already in use.
FAILED_VERDICTS = frozenset({DEAD, BLACK, FROZEN})

#: Verdicts where the stream was never reached, so a retry is warranted.
INCONCLUSIVE_VERDICTS = frozenset({REFUSED, GONE, UNKNOWN})

#: ffmpeg reports the HTTP status in prose, not a field.
_REFUSED_RE = re.compile(r"(40[13]) Forbidden|(40[13]) Unauthorized|"
                         r"HTTP error 40[13]", re.IGNORECASE)
_GONE_RE = re.compile(r"HTTP error 40[04]|404 Not Found|"
                      r"Connection refused|No route to host|"
                      r"Name or service not known", re.IGNORECASE)


@dataclass(frozen=True)
class ProbeResult:
    """What one probe saw.

    Attributes:
        verdict: ``dead`` / ``black`` / ``frozen`` / ``live`` / ``unknown``.
        frames: Video frames decoded. Zero is the strongest dead signal there
            is — the stream produced no picture at all.
        black_seconds: Total black time inside the sample.
        frozen: Whether a frozen run was reported.
        silent_seconds: Total silence. Corroboration, never the verdict on its
            own — a studio feed between segments is quiet and still live.
        resolution: ``"1920x1080"`` when the stream declared one.
        elapsed_ms: Wall-clock cost, for the caller's progress estimate.
        detail: A short human sentence for a tooltip or a log line.
    """

    verdict: str
    frames: int = 0
    black_seconds: float = 0.0
    frozen: bool = False
    silent_seconds: float = 0.0
    resolution: str = ""
    elapsed_ms: int = 0
    detail: str = ""

    @property
    def is_failure(self) -> bool:
        """Whether this verdict means there is nothing to watch.

        False for ``refused`` and ``gone``: those say the stream was never
        reached, which is a different fact and must not be recorded as one.
        """
        return self.verdict in FAILED_VERDICTS

    @property
    def is_inconclusive(self) -> bool:
        """Whether the probe never got to see the picture."""
        return self.verdict in INCONCLUSIVE_VERDICTS


def ffmpeg_available() -> bool:
    """Whether ffmpeg is on PATH.

    The feature is unavailable rather than broken without it — mpv is MetaTV's
    hard dependency, ffmpeg is not, and a user who has one may not have the
    other.
    """
    return shutil.which("ffmpeg") is not None


def _build_command(url: str, seconds: int) -> list[str]:
    """The one ffmpeg invocation, with all three video/audio detectors."""
    return [
        "ffmpeg", "-hide_banner", "-nostdin",
        "-rw_timeout", str(_RW_TIMEOUT_US),
        "-i", url,
        "-t", str(seconds),
        "-vf", (f"blackdetect=d={_BLACK_MIN_DURATION}:"
                f"pix_th={_BLACK_PIXEL_THRESHOLD},"
                f"freezedetect=n={_FREEZE_NOISE_DB}:d={_FREEZE_MIN_DURATION}"),
        "-af", f"silencedetect=n={_SILENCE_NOISE_DB}:d={_SILENCE_MIN_DURATION}",
        "-f", "null", "-",
    ]


def interpret(stderr: str, returncode: int, seconds: int,
              elapsed_ms: int = 0) -> ProbeResult:
    """Turn ffmpeg's stderr into a verdict.

    Split out from :func:`probe_stream` so the ruling can be tested against
    captured ffmpeg output without a network, a subprocess, or a provider
    connection — which is the only way to test the interesting cases at all,
    since a dead stream cannot be summoned on demand.

    Args:
        stderr: ffmpeg's combined output.
        returncode: Its exit status.
        seconds: The sample length that was requested.
        elapsed_ms: Wall-clock cost, passed through to the result.

    Returns:
        The :class:`ProbeResult`.
    """
    frames = 0
    for match in _FRAME_RE.finditer(stderr):
        frames = max(frames, int(match.group(1)))
    black = sum(float(m.group(1)) for m in _BLACK_DURATION_RE.finditer(stderr))
    silent = sum(float(m.group(1))
                 for m in _SILENCE_DURATION_RE.finditer(stderr))
    frozen = bool(_FREEZE_START_RE.search(stderr))
    res_match = _RESOLUTION_RE.search(stderr)
    resolution = f"{res_match.group(1)}x{res_match.group(2)}" if res_match else ""

    common = {
        "frames": frames, "black_seconds": round(black, 2), "frozen": frozen,
        "silent_seconds": round(silent, 2), "resolution": resolution,
        "elapsed_ms": elapsed_ms,
    }

    # The connection first. A refusal is not a verdict about content, and
    # conflating the two is how a sweep run while something is playing would
    # mark 125 working channels dead — this account allows ONE connection.
    if _REFUSED_RE.search(stderr):
        return ProbeResult(
            verdict=REFUSED,
            detail="the provider refused the connection (403) — it may be in "
                   "use, or this channel may need different credentials",
            **common)
    if _GONE_RE.search(stderr):
        return ProbeResult(
            verdict=GONE,
            detail="the stream could not be reached at all",
            **common)

    if frames == 0:
        return ProbeResult(
            verdict=DEAD,
            detail=("no video — the stream produced no frames"
                    if returncode == 0 else
                    f"no video — ffmpeg exited {returncode}"),
            **common)

    # Black is judged as a FRACTION of the sample. A bumper or a fade is black
    # for a moment; half the sample is not a bumper.
    if seconds > 0 and black >= seconds * _BLACK_VERDICT_RATIO:
        return ProbeResult(
            verdict=BLACK,
            detail=f"black for {black:.1f}s of a {seconds}s sample",
            **common)

    if frozen:
        return ProbeResult(
            verdict=FROZEN,
            detail="a still picture — no motion between frames",
            **common)

    bits = [f"{frames} frames"]
    if resolution:
        bits.append(resolution)
    if black:
        bits.append(f"{black:.1f}s black")
    if silent:
        # Recorded, never decisive: a studio feed between segments is quiet.
        bits.append(f"{silent:.1f}s silent")
    return ProbeResult(verdict=LIVE, detail=", ".join(bits), **common)


def probe_stream(url: str, seconds: int = DEFAULT_SAMPLE_SECONDS) -> ProbeResult:
    """Sample one stream and rule on whether it carries a picture.

    Blocking, and it spends one provider connection for its whole duration —
    call it from a worker, never from the UI thread, and never while something
    is playing.

    Args:
        url: The stream URL.
        seconds: Sample length. The wall-clock cost is dominated by connect and
            buffer, so a longer sample is cheaper than it looks.

    Returns:
        A :class:`ProbeResult`; ``UNKNOWN`` when ffmpeg is missing or the probe
        could not be run at all, which is not the same as the stream being dead.
    """
    if not ffmpeg_available():
        return ProbeResult(verdict=UNKNOWN, detail="ffmpeg is not installed")
    if not url:
        return ProbeResult(verdict=UNKNOWN, detail="no stream URL")

    import time
    started = time.monotonic()
    try:
        proc = subprocess.run(
            _build_command(url, seconds),
            capture_output=True, text=True, errors="replace",
            timeout=seconds + _TIMEOUT_MARGIN_SECONDS,
        )
    except subprocess.TimeoutExpired:
        elapsed = int((time.monotonic() - started) * 1000)
        # A stream that will not produce a frame inside the window has
        # answered the question — but it answered it by hanging, which a busy
        # provider also does, so it is recorded as unreached rather than dead.
        return ProbeResult(verdict=GONE, elapsed_ms=elapsed,
                           detail="timed out before producing a picture")
    except OSError as exc:
        logger.warning("probe_stream: could not run ffmpeg: {}", exc)
        return ProbeResult(verdict=UNKNOWN, detail=f"could not run ffmpeg: {exc}")

    elapsed = int((time.monotonic() - started) * 1000)
    return interpret(proc.stderr or "", proc.returncode, seconds, elapsed)
