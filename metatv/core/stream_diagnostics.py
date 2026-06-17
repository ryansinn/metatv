"""Headless stream-diagnostics engine.

Given a stream URL, this module measures whether buffering is caused by the
**source provider** (its server/path can't sustain the stream's bitrate even
though the user's pipe is fine) or by the **user's own internet** (the pipe
itself can't carry the bitrate), and recommends tuned mpv cache args.

This is pure core logic — no Qt, no UI. A UI layer (later PR) is expected to
call :func:`run_stream_diagnostic` inside a ``ThreadPoolExecutor`` and render
the returned :class:`DiagnosticResult`.

Credentials embedded in Xtream stream URLs
(``{base}/live|movie|series/{username}/{password}/{id}.{ext}``) are redacted in
**every** log line and in every human-facing string this module produces.
"""

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field

import requests

from loguru import logger

# --- Verdict constants -------------------------------------------------------
VERDICT_HEALTHY = "healthy"
VERDICT_JITTER = "jitter"
VERDICT_PROVIDER_LIMITED = "provider-limited"
VERDICT_INTERNET_LIMITED = "internet-limited"
VERDICT_UNREACHABLE = "unreachable"

# Re-export under the short names referenced by the task spec / callers.
HEALTHY = VERDICT_HEALTHY
JITTER = VERDICT_JITTER
PROVIDER_LIMITED = VERDICT_PROVIDER_LIMITED
INTERNET_LIMITED = VERDICT_INTERNET_LIMITED
UNREACHABLE = VERDICT_UNREACHABLE

# Matches an Xtream stream path: /<kind>/<user>/<pass>/<id>.<ext>
# kind is one of live/movie/series (Xtream also serves bare /<user>/<pass>/<id>).
_XTREAM_PATH_RE = re.compile(
    r"/(live|movie|series)/[^/]+/[^/]+/", re.IGNORECASE
)
_XTREAM_BARE_PATH_RE = re.compile(
    r"^(https?://[^/]+)/([^/]+)/([^/]+)/(\d+)\b", re.IGNORECASE
)

# Classification thresholds (documented for the pure helpers below).
# headroom = throughput_mbps / bitrate_mbps
_HEADROOM_HEALTHY = 1.5   # >= this: comfortable margin over bitrate
_HEADROOM_JITTER = 1.0    # [JITTER, HEALTHY): barely keeping up
# When throughput or bitrate is unknown, a "decent" raw throughput still
# reads as healthy; below it we can't be confident, so call it jitter.
_DECENT_THROUGHPUT_MBPS = 3.0
# A baseline that comfortably exceeds the bitrate means the user's pipe is fine,
# so an under-performing provider is the cap (provider-limited).
_BASELINE_HEADROOM = 1.5


@dataclass(frozen=True)
class DiagnosticResult:
    """Outcome of a single stream-diagnostic probe.

    All numeric fields are ``None`` when the corresponding measurement could not
    be taken (e.g. ffprobe missing, baseline skipped, stream unreachable).
    """

    reachable: bool
    verdict: str
    summary: str
    connect_ms: float | None = None
    ttfb_ms: float | None = None
    throughput_mbps: float | None = None
    baseline_mbps: float | None = None
    bitrate_mbps: float | None = None
    codec: str | None = None
    resolution: str | None = None
    headroom_ratio: float | None = None
    recommended_args: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


# --- Security ----------------------------------------------------------------
def _redact(url: str) -> str:
    """Replace the username/password segments of a stream URL with ``***``.

    Handles the canonical Xtream shapes
    ``{base}/live|movie|series/{user}/{pass}/{id}.{ext}`` and the bare
    ``{base}/{user}/{pass}/{id}.{ext}``. A URL that doesn't match either is
    returned unchanged.

    Args:
        url: The raw stream URL (may contain credentials).

    Returns:
        The URL with the user and password path segments replaced by ``***``.
    """
    if not url:
        return url

    if _XTREAM_PATH_RE.search(url):
        return _XTREAM_PATH_RE.sub(
            lambda m: f"/{m.group(1)}/***/***/", url, count=1
        )

    bare = _XTREAM_BARE_PATH_RE.match(url)
    if bare:
        base, _user, _pwd, ident = bare.groups()
        # Preserve whatever followed the id (e.g. ".ts").
        tail = url[bare.end():]
        return f"{base}/***/***/{ident}{tail}"

    return url


# --- Pure helpers (the half that regresses) ----------------------------------
def classify(
    throughput_mbps: float | None,
    bitrate_mbps: float | None,
    baseline_mbps: float | None,
    reachable: bool,
) -> str:
    """Classify the likely cause of buffering from measured rates.

    Decision rules:
      * not ``reachable`` -> ``UNREACHABLE``.
      * throughput or bitrate unknown -> best-effort: a "decent" raw throughput
        (> 3.0 Mbps) reads as ``HEALTHY``; otherwise ``JITTER``.
      * ``headroom = throughput / bitrate``:
          - ``>= 1.5`` -> ``HEALTHY`` (comfortable margin)
          - ``[1.0, 1.5)`` -> ``JITTER`` (barely keeping up)
          - ``< 1.0`` -> provider not keeping up; split on the baseline:
              * baseline known and ``>= 1.5 * bitrate`` -> ``PROVIDER_LIMITED``
                (the user's pipe is fine, the provider's server/path is the cap)
              * else -> ``INTERNET_LIMITED`` (the pipe itself can't sustain it,
                or we have no baseline and throughput is low)

    Args:
        throughput_mbps: Sustained download rate from the provider stream.
        bitrate_mbps: Stream bitrate (ffprobe or throughput estimate).
        baseline_mbps: Neutral-host speed sample, or ``None`` if unavailable.
        reachable: Whether the stream was reachable at all.

    Returns:
        One of the module ``VERDICT_*`` constants.
    """
    if not reachable:
        return UNREACHABLE

    if throughput_mbps is None or not bitrate_mbps:
        if throughput_mbps is not None and throughput_mbps > _DECENT_THROUGHPUT_MBPS:
            return HEALTHY
        return JITTER

    headroom = throughput_mbps / bitrate_mbps
    if headroom >= _HEADROOM_HEALTHY:
        return HEALTHY
    if headroom >= _HEADROOM_JITTER:
        return JITTER

    # headroom < 1.0 — the provider stream isn't keeping up with its own bitrate.
    if baseline_mbps is not None and baseline_mbps >= _BASELINE_HEADROOM * bitrate_mbps:
        return PROVIDER_LIMITED
    return INTERNET_LIMITED


def recommend_mpv_args(
    verdict: str, bitrate_mbps: float | None
) -> tuple[str, ...]:
    """Recommend tuned mpv cache args for a verdict.

    Buffer sizing converts bitrate (Mbps) to bytes-per-second
    (``bitrate_mbps / 8`` MB/s) times a target buffer duration, then clamps to a
    sane MiB range. When ``bitrate_mbps`` is unknown a fixed default is used.

    Args:
        verdict: One of the module ``VERDICT_*`` constants.
        bitrate_mbps: Stream bitrate, or ``None`` if unknown.

    Returns:
        A tuple of mpv command-line args.
    """
    if verdict == HEALTHY:
        return ("--cache=yes",)

    if verdict == JITTER:
        if bitrate_mbps:
            n = int(bitrate_mbps / 8 * 30)
            n = max(50, min(n, 512))
        else:
            n = 128
        return (
            "--cache=yes",
            f"--demuxer-max-bytes={n}MiB",
            "--demuxer-readahead-secs=30",
            "--cache-secs=30",
        )

    if verdict == PROVIDER_LIMITED:
        if bitrate_mbps:
            n = int(bitrate_mbps / 8 * 60)
            n = max(100, min(n, 1024))
        else:
            n = 256
        return (
            "--cache=yes",
            f"--demuxer-max-bytes={n}MiB",
            "--demuxer-readahead-secs=60",
            "--cache-secs=60",
        )

    if verdict == INTERNET_LIMITED:
        # A bigger buffer can't fix a pipe that's too thin; just enable cache.
        # The summary advises dropping to a lower-quality stream.
        return ("--cache=yes",)

    # UNREACHABLE or anything unexpected.
    return ()


# --- ffprobe -----------------------------------------------------------------
def _probe_ffprobe(
    stream_url: str, redacted: str
) -> tuple[str | None, str | None, float | None]:
    """Run ffprobe and extract (codec, resolution, bitrate_mbps).

    Never raises — on any failure (ffprobe missing, timeout, bad JSON) returns
    ``(None, None, None)``.

    Args:
        stream_url: The raw stream URL (passed to ffprobe).
        redacted: The credential-free URL used for logging.

    Returns:
        ``(codec, resolution, bitrate_mbps)`` with ``None`` for anything that
        couldn't be determined.
    """
    if not shutil.which("ffprobe"):
        logger.debug("ffprobe not found on PATH; skipping codec/bitrate probe")
        return (None, None, None)

    try:
        proc = subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_streams",
                "-show_format",
                stream_url,
            ],
            capture_output=True,
            text=True,
            timeout=12,
        )
        data = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, json.JSONDecodeError, OSError) as exc:
        logger.debug(f"ffprobe failed for {redacted}: {type(exc).__name__}")
        return (None, None, None)

    codec: str | None = None
    resolution: str | None = None
    bitrate_mbps: float | None = None

    video = None
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            video = stream
            break

    if video is not None:
        codec = video.get("codec_name") or None
        width = video.get("width")
        height = video.get("height")
        if width and height:
            resolution = f"{width}x{height}"

    # Prefer format-level bitrate, fall back to the video stream's bitrate.
    raw_bitrate = data.get("format", {}).get("bit_rate")
    if not raw_bitrate and video is not None:
        raw_bitrate = video.get("bit_rate")
    if raw_bitrate:
        try:
            bitrate_mbps = float(raw_bitrate) / 1e6
        except (TypeError, ValueError):
            bitrate_mbps = None

    return (codec, resolution, bitrate_mbps)


# --- Baseline ----------------------------------------------------------------
def _measure_baseline(
    baseline_url: str, timeout: float
) -> float | None:
    """Download from a neutral host briefly to sample the user's raw pipe speed.

    Caps the download at ~25 MB or ~5 s, whichever comes first. Any error
    yields ``None`` (the baseline is optional and must not fail the diagnostic).

    Args:
        baseline_url: A neutral-host download URL (no credentials).
        timeout: Connection timeout in seconds.

    Returns:
        Measured download rate in Mbps, or ``None`` on any error / no data.
    """
    cap_bytes = 25_000_000
    cap_seconds = 5.0
    try:
        with requests.get(baseline_url, stream=True, timeout=timeout) as resp:
            resp.raise_for_status()
            start = time.monotonic()
            total = 0
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if chunk:
                    total += len(chunk)
                elapsed = time.monotonic() - start
                if total >= cap_bytes or elapsed >= cap_seconds:
                    break
            elapsed = time.monotonic() - start
            if elapsed <= 0 or total <= 0:
                return None
            return (total * 8) / elapsed / 1e6
    except (requests.RequestException, OSError) as exc:
        logger.debug(f"baseline measurement failed: {type(exc).__name__}")
        return None


# --- Probe entry point -------------------------------------------------------
def run_stream_diagnostic(
    stream_url: str,
    *,
    sample_seconds: int = 8,
    max_bytes: int = 200_000_000,
    baseline_url: str | None = None,
    timeout: float = 15.0,
) -> DiagnosticResult:
    """Probe a stream and diagnose the likely cause of buffering.

    Measures connect/setup time, time-to-first-byte, sustained provider
    throughput, ffprobe codec/resolution/bitrate, and (optionally) a
    neutral-host baseline speed; then classifies the result and recommends
    mpv cache args.

    Args:
        stream_url: The raw stream URL (may contain Xtream credentials).
        sample_seconds: Max seconds to sample provider throughput.
        max_bytes: Max bytes to read while sampling (whichever limit hits first).
        baseline_url: Optional neutral-host URL for a pipe-speed sample.
        timeout: Connection/read timeout in seconds for the stream request.

    Returns:
        A :class:`DiagnosticResult`. ``summary`` and ``error`` never contain
        credentials.
    """
    redacted = _redact(stream_url)
    logger.info(f"Running stream diagnostic for {redacted}")

    connect_ms: float | None = None
    ttfb_ms: float | None = None
    throughput_mbps: float | None = None

    request_start = time.monotonic()
    try:
        resp = requests.get(stream_url, stream=True, timeout=timeout)
    except (requests.RequestException, OSError) as exc:
        msg = f"Stream unreachable: {type(exc).__name__}"
        logger.warning(f"{msg} for {redacted}")
        return DiagnosticResult(
            reachable=False,
            verdict=UNREACHABLE,
            summary=f"Could not reach {redacted}.",
            error=msg,
        )

    try:
        if not (200 <= resp.status_code < 300):
            msg = f"Stream returned HTTP {resp.status_code}"
            logger.warning(f"{msg} for {redacted}")
            return DiagnosticResult(
                reachable=False,
                verdict=UNREACHABLE,
                summary=f"{redacted} returned HTTP {resp.status_code}.",
                error=msg,
            )

        connect_ms = (time.monotonic() - request_start) * 1000.0

        # Sample the body: time-to-first-byte + sustained throughput.
        sample_start = time.monotonic()
        first_byte_at: float | None = None
        bytes_read = 0
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            now = time.monotonic()
            if chunk:
                if first_byte_at is None:
                    first_byte_at = now
                    ttfb_ms = (now - request_start) * 1000.0
                bytes_read += len(chunk)
            elapsed = now - sample_start
            if elapsed >= sample_seconds or bytes_read >= max_bytes:
                break

        elapsed = max(time.monotonic() - sample_start, 0.0)
        if elapsed > 0 and bytes_read > 0:
            throughput_mbps = (bytes_read * 8) / elapsed / 1e6
    finally:
        resp.close()

    # ffprobe — codec / resolution / bitrate (never raises out).
    codec, resolution, bitrate_mbps = _probe_ffprobe(stream_url, redacted)

    bitrate_estimated = False
    if not bitrate_mbps and throughput_mbps:
        # Live .ts streams commonly expose no bitrate; use measured throughput
        # as a floor estimate.
        bitrate_mbps = throughput_mbps
        bitrate_estimated = True

    # Optional neutral-host baseline.
    baseline_mbps: float | None = None
    if baseline_url:
        baseline_mbps = _measure_baseline(baseline_url, timeout)

    verdict = classify(throughput_mbps, bitrate_mbps, baseline_mbps, reachable=True)
    recommended_args = recommend_mpv_args(verdict, bitrate_mbps)

    headroom_ratio: float | None = None
    if throughput_mbps is not None and bitrate_mbps:
        headroom_ratio = throughput_mbps / bitrate_mbps

    summary = _build_summary(
        redacted=redacted,
        verdict=verdict,
        throughput_mbps=throughput_mbps,
        bitrate_mbps=bitrate_mbps,
        baseline_mbps=baseline_mbps,
        headroom_ratio=headroom_ratio,
        bitrate_estimated=bitrate_estimated,
    )

    logger.info(
        f"Diagnostic for {redacted}: verdict={verdict} "
        f"throughput={throughput_mbps} bitrate={bitrate_mbps} "
        f"baseline={baseline_mbps}"
    )

    return DiagnosticResult(
        reachable=True,
        verdict=verdict,
        summary=summary,
        connect_ms=connect_ms,
        ttfb_ms=ttfb_ms,
        throughput_mbps=throughput_mbps,
        baseline_mbps=baseline_mbps,
        bitrate_mbps=bitrate_mbps,
        codec=codec,
        resolution=resolution,
        headroom_ratio=headroom_ratio,
        recommended_args=recommended_args,
        error=None,
    )


def _build_summary(
    *,
    redacted: str,
    verdict: str,
    throughput_mbps: float | None,
    bitrate_mbps: float | None,
    baseline_mbps: float | None,
    headroom_ratio: float | None,
    bitrate_estimated: bool,
) -> str:
    """Build a short, credential-free human-readable explanation.

    Args:
        redacted: The credential-free stream URL.
        verdict: The computed verdict constant.
        throughput_mbps: Sustained provider throughput.
        bitrate_mbps: Stream bitrate (measured or estimated).
        baseline_mbps: Neutral-host baseline, if measured.
        headroom_ratio: ``throughput / bitrate`` when both known.
        bitrate_estimated: Whether bitrate was estimated from throughput.

    Returns:
        A one-to-two sentence summary string.
    """
    def fmt(x: float | None) -> str:
        return f"{x:.1f}" if x is not None else "?"

    rate = (
        f"throughput {fmt(throughput_mbps)} Mbps vs bitrate {fmt(bitrate_mbps)} Mbps"
    )
    if bitrate_estimated:
        rate += " (bitrate estimated from throughput)"
    if headroom_ratio is not None:
        rate += f", headroom {headroom_ratio:.2f}x"
    if baseline_mbps is not None:
        rate += f"; baseline {fmt(baseline_mbps)} Mbps"

    if verdict == HEALTHY:
        head = "Stream is healthy — comfortable headroom over the bitrate."
    elif verdict == JITTER:
        head = "Stream is barely keeping up — expect occasional buffering; a larger cache helps."
    elif verdict == PROVIDER_LIMITED:
        head = (
            "The provider's server/path is the bottleneck — your connection can "
            "sustain this bitrate but the provider can't deliver it."
        )
    elif verdict == INTERNET_LIMITED:
        head = (
            "Your internet connection can't sustain this bitrate — try a "
            "lower-quality stream; a bigger cache won't fix a too-thin pipe."
        )
    elif verdict == UNREACHABLE:
        head = f"Could not reach {redacted}."
    else:
        head = "Diagnostic complete."

    return f"{head} ({rate})"
