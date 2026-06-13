"""Test that bare RAW/LIVE/CAM don't consume titles.

Regression for B0: "WWE Raw" was being parsed as title="WWE", quality="RAW",
when it should be title="WWE Raw", quality=[].
"""

import pytest
from metatv.core.channel_name_utils import parse_channel_name, QUALITY_TOKENS


def test_wwe_raw_title_not_eaten():
    """Bare 'RAW' must not strip from end and consume part of title."""
    result = parse_channel_name("EN - WWE Raw (2023)")
    assert result.bare_name == "WWE Raw", (
        f"Title must preserve 'WWE Raw', got '{result.bare_name}'"
    )
    assert "RAW" not in result.quality, (
        f"RAW must not be in quality list when it's part of title: {result.quality}"
    )
    assert result.year == "2023"
    assert result.region == "EN"


def test_bracketed_raw_still_works():
    """Bracketed [RAW] should still be recognized as quality."""
    result = parse_channel_name("EN - WWE [RAW] (2023)")
    assert result.bare_name == "WWE", (
        f"Title should be just 'WWE' when [RAW] is bracketed, got '{result.bare_name}'"
    )
    assert "RAW" in result.quality, (
        f"RAW must be in quality when bracketed: {result.quality}"
    )


def test_live_not_eaten_from_title():
    """Bare 'LIVE' must not strip from end of title."""
    result = parse_channel_name("EN - Live Music Festival")
    assert "Music Festival" in result.bare_name or result.bare_name == "Live Music Festival", (
        f"Title must preserve 'LIVE': got '{result.bare_name}'"
    )
    assert "LIVE" not in result.quality, (
        f"LIVE must not be in quality: {result.quality}"
    )


def test_cam_not_eaten_from_title():
    """Bare 'CAM' must not strip from title."""
    result = parse_channel_name("EN - Cam's Movie")
    # "Cam's" should be preserved in the title
    assert "Cam" in result.bare_name, (
        f"Title must preserve 'Cam': got '{result.bare_name}'"
    )


def test_unambiguous_quality_still_works():
    """HQ and LQ should still work as quality tokens."""
    result_hq = parse_channel_name("EN - Movie HQ")
    assert "HQ" in result_hq.quality, f"HQ should be recognized: {result_hq.quality}"
    assert result_hq.bare_name == "Movie"

    result_lq = parse_channel_name("EN - Movie LQ")
    assert "LQ" in result_lq.quality, f"LQ should be recognized: {result_lq.quality}"
    assert result_lq.bare_name == "Movie"


def test_raw_live_cam_not_in_suffix_regex():
    """RAW, LIVE, CAM are removed from the bare-trailing-strip regex.

    They remain in QUALITY_TOKENS for bracket handling ([RAW], [LIVE], [CAM])
    but must not be stripped from the end of bare titles (e.g., "WWE Raw").
    """
    # Test by parsing — if RAW/LIVE/CAM were still in the regex, they'd be
    # stripped from bare names. Our tests above verify they aren't.
    result = parse_channel_name("EN - Movie RAW")
    assert result.bare_name == "Movie RAW", (
        "Bare RAW at end must not be stripped"
    )


def test_4k_fhd_still_work():
    """Unambiguous quality tokens like 4K, FHD must still work."""
    result = parse_channel_name("EN - Movie 4K")
    assert "4K" in result.quality
    assert result.bare_name == "Movie"

    result2 = parse_channel_name("EN - Movie FHD")
    assert "FHD" in result2.quality
    assert result2.bare_name == "Movie"
