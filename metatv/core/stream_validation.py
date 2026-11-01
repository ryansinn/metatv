"""Pre-play stream check: does this URL answer with video, or with an error?

Moved out of ``gui/main_window_streaming.py`` (at its size pin, 2026-11-01):
a network read with no widget in it. ``_StreamingMixin.validate_stream_url``
stays as a thin delegate — the failover loop, the sibling sweep and
``MainWindow``'s stale-source offer all call it by that name, and tests patch it
there.
"""

from __future__ import annotations

import requests
from loguru import logger

from metatv.providers.xtream import _DEFAULT_HEADERS


# ISO-BMFF (MP4/MOV) top-level box types that legitimately appear at the very start of
# a stream. `ftyp`/`moov` lead a faststart (web-optimised) file; the box type lives at
# bytes 4–8, after the 4-byte size field.
_ISO_BMFF_BOXES = frozenset(
    (b"ftyp", b"styp", b"moov", b"moof", b"mdat", b"free", b"skip", b"wide", b"pnot")
)


def _looks_like_video(chunk: bytes) -> bool:
    """Return True if a chunk begins with a known video-container magic number.

    This must take precedence over the printable-ASCII heuristic: a faststart MP4
    (``ftyp``/``moov`` first) and a Matroska/WebM header are dominated by ASCII box/
    element names (`ftyp`, `isom`, `avc1`, `matroska`, …), so `_looks_like_text` would
    false-positive and the validator would reject perfectly good VOD as a text error.
    """
    if not chunk:
        return False
    if chunk[0] == 0x47:                          # MPEG-TS sync byte
        return True
    if chunk[:4] == b"\x1a\x45\xdf\xa3":          # EBML — Matroska / WebM
        return True
    if len(chunk) >= 8 and chunk[4:8] in _ISO_BMFF_BOXES:  # ISO-BMFF — MP4 / MOV
        return True
    if chunk[:3] == b"\x00\x00\x01":              # MPEG PS/ES start code
        return True
    if chunk[:3] == b"FLV":                       # Flash Video
        return True
    return False


def _looks_like_text(chunk: bytes) -> bool:
    """Return True if a stream response chunk looks like text rather than binary video data.

    MPEG-TS sync byte (0x47) as the first byte is a strong binary signal.
    Otherwise we check the printable-ASCII ratio of the first 256 bytes.

    Note: callers must check :func:`_looks_like_video` first — some binary containers
    (faststart MP4, Matroska) are ASCII-heavy in their first bytes and would trip this.
    """
    if not chunk:
        return False
    if chunk[0] == 0x47:   # MPEG-TS sync byte — definitely binary
        return False
    printable = sum(1 for b in chunk[:256] if 0x20 <= b <= 0x7E or b in (0x09, 0x0A, 0x0D))
    return (printable / min(len(chunk), 256)) > 0.85


def validate_stream_url(url: str, timeout: int = 5) -> tuple[bool, str | None]:
    """Validate a stream URL by reading its first bytes.

    Returns ``(is_valid, error_message)``.  ``error_message`` is set when
    the server delivers a text error (e.g. "This channel is not available")
    instead of binary video data so the caller can surface it to the user.

    HEAD requests are unreliable for IPTV (servers often return 5xx on HEAD
    while serving fine on GET), so we use a streaming GET and read one chunk.
    """
    try:
        logger.debug(f"Validating stream URL: {url}")
        with requests.get(
            url,
            stream=True,
            timeout=(timeout, timeout),
            allow_redirects=True,
            headers=_DEFAULT_HEADERS,
        ) as response:
            if response.status_code >= 400:
                logger.warning(f"Stream URL returned HTTP {response.status_code}")
                # A 5xx/429 is the SERVER having a moment, not proof the stream
                # is bad (docstring): on a one-connection account THIS PROBE IS
                # the second connection, so the provider 500s it because it is
                # serving — mpv is the better authority. 511 is auth → 4xx here.
                if (response.status_code >= 500 and response.status_code != 511
                        ) or response.status_code == 429:
                    return True, None
                # Being told no — bad credentials, gone, gated. Reported, with
                # "Play Anyway" still offered by the caller.
                return False, f"HTTP {response.status_code}"
            chunk = next(response.iter_content(chunk_size=256), None)
            if chunk is None:
                logger.warning("Stream URL returned no data")
                return False, None
            # A recognised video container wins outright — even if its ASCII-heavy
            # header (faststart MP4, Matroska) would otherwise look like text, and
            # even if the server mislabels the Content-Type.
            if _looks_like_video(chunk):
                logger.debug(f"Stream URL validated: HTTP {response.status_code}, "
                             f"video container, got {len(chunk)} bytes")
                return True, None
            # Detect text error messages (e.g. "This channel is not available")
            ct = response.headers.get("Content-Type", "").lower()
            is_text_ct = any(t in ct for t in ("text/", "application/json"))
            if is_text_ct or _looks_like_text(chunk):
                msg = chunk.decode("utf-8", errors="replace").strip()
                msg = msg.splitlines()[0][:160]   # first line, ≤160 chars
                logger.warning(f"Stream URL returned text error: {msg!r}")
                return False, msg or "Stream unavailable"
            logger.debug(f"Stream URL validated: HTTP {response.status_code}, got {len(chunk)} bytes")
            return True, None
    except requests.exceptions.Timeout:
        logger.warning(f"Stream URL validation timeout: {url}")
        return False, None
    except requests.exceptions.ConnectionError:
        logger.warning(f"Stream URL connection failed: {url}")
        return False, None
    except Exception as e:
        logger.warning(f"Stream URL validation error: {e}")
        return False, None
