"""Regression: the stream validator must accept real video containers whose headers
are ASCII-heavy (faststart MP4, Matroska), not reject them as text errors.

The bug: ottcst serves moov-first MP4 and Matroska VOD; their first 256 bytes are
dominated by ASCII box/element names (`ftyp`, `isom`, `avc1`, `matroska`), so the
printable-ratio heuristic flagged them as text and surfaced the raw bytes as a
"Stream Unavailable" error. These tests execute the real validation path.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

from metatv.gui.main_window_streaming import _StreamingMixin, _looks_like_video


# Representative first-chunk headers.
MP4_FASTSTART = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2avc1mp41" + b"\x00\x00\x00\x08moovlmvhd" + b"\x00" * 40
MKV_EBML = b"\x1a\x45\xdf\xa3\x01\x00\x00\x00\x00\x00\x00\x1fmatroska" + b"\x42\x82\x88" + b"\x00" * 40
MPEG_TS = b"\x47" + b"\x40\x00\x10" + b"\x00" * 60
TEXT_ERROR = b"This channel is not available. Please contact your provider for details.\n" * 4


def test_looks_like_video_recognises_containers():
    assert _looks_like_video(MP4_FASTSTART)
    assert _looks_like_video(MKV_EBML)
    assert _looks_like_video(MPEG_TS)
    assert _looks_like_video(b"FLV\x01\x05" + b"\x00" * 20)
    assert _looks_like_video(b"\x00\x00\x01\xba" + b"\x00" * 20)  # MPEG program stream


def test_looks_like_video_rejects_text():
    assert not _looks_like_video(TEXT_ERROR)
    assert not _looks_like_video(b"")


def _fake_get(chunk: bytes, *, status=206, content_type="application/octet-stream"):
    """Build a requests.get replacement whose context-managed response yields `chunk`."""
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"Content-Type": content_type}
    resp.iter_content = lambda chunk_size=256: iter([chunk])

    @contextmanager
    def _cm(*a, **kw):
        yield resp

    return _cm


def _validator() -> _StreamingMixin:
    return _StreamingMixin.__new__(_StreamingMixin)


def test_faststart_mp4_validates_ok():
    obj = _validator()
    with patch("metatv.gui.main_window_streaming.requests.get", _fake_get(MP4_FASTSTART)):
        ok, err = obj.validate_stream_url("http://x/movie/u/p/1.mp4")
    assert ok is True and err is None


def test_matroska_validates_ok():
    obj = _validator()
    with patch("metatv.gui.main_window_streaming.requests.get", _fake_get(MKV_EBML)):
        ok, err = obj.validate_stream_url("http://x/movie/u/p/1.mkv")
    assert ok is True and err is None


def test_mpeg_ts_still_validates_ok():
    obj = _validator()
    with patch("metatv.gui.main_window_streaming.requests.get", _fake_get(MPEG_TS)):
        ok, err = obj.validate_stream_url("http://x/live/u/p/1.ts")
    assert ok is True and err is None


def test_text_error_still_rejected_with_message():
    """A genuine text error body must still fail and surface its first line."""
    obj = _validator()
    with patch("metatv.gui.main_window_streaming.requests.get",
               _fake_get(TEXT_ERROR, content_type="text/html")):
        ok, err = obj.validate_stream_url("http://x/movie/u/p/1.mp4")
    assert ok is False
    assert err and "not available" in err
