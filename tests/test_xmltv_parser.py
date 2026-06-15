"""Regression tests for the XMLTV datetime parser.

Pins the ingestion-boundary contract that broke EPG refresh in the field:
``_parse_xmltv_datetime`` must return a **naive** UTC datetime matching the
``EpgProgramDB`` storage format (CLAUDE.md: "start_time / stop_time are stored as
UTC-naive datetimes"). When the parser returned tz-aware datetimes,
``_fetch_worker``'s stale-guide check ``max_stop < now_utc()`` raised
"can't compare offset-naive and offset-aware datetimes" and aborted the whole
refresh (parsing 290k programmes, then crashing before persisting timestamps).
"""
from __future__ import annotations

from datetime import datetime

from metatv.core.epg_utils import now_utc
from metatv.core.xmltv_parser import _parse_xmltv_datetime


def test_parse_returns_naive_datetime():
    dt = _parse_xmltv_datetime("20260512153000 +0200")
    assert dt.tzinfo is None  # naive — matches EpgProgramDB storage


def test_parse_converts_offset_to_utc():
    # 15:30 at +0200 == 13:30 UTC
    assert _parse_xmltv_datetime("20260512153000 +0200") == datetime(2026, 5, 12, 13, 30, 0)
    # 08:00 at -0500 == 13:00 UTC
    assert _parse_xmltv_datetime("20260512080000 -0500") == datetime(2026, 5, 12, 13, 0, 0)


def test_parse_zero_offset_is_unchanged():
    assert _parse_xmltv_datetime("20260512153000 +0000") == datetime(2026, 5, 12, 15, 30, 0)


def test_parsed_time_is_comparable_to_now_utc():
    """The exact regression: comparing a parsed time against now_utc() must not raise."""
    parsed = _parse_xmltv_datetime("20260512153000 +0200")
    # Would raise "can't compare offset-naive and offset-aware datetimes" if parser were aware.
    assert (parsed < now_utc()) in (True, False)
