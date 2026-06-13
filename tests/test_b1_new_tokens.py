"""Test new prefix tokens added in B1 (TASK B1).

Tests verify that the added tokens are correctly recognized and parsed.
For each token added, we test the parse behavior it enables.
"""

import pytest
from metatv.core.channel_name_utils import parse_channel_name


def test_mxc_mexico_token():
    """MXC token should be recognized as Mexico."""
    result = parse_channel_name("MXC ★ Película Española")
    assert result.region == "MXC", f"MXC should be recognized as region, got {result.region}"
    assert result.bare_name == "Película Española"


def test_isr_israel_token():
    """ISR token should be recognized as Israel."""
    result = parse_channel_name("ISR ★ Israeli Channel")
    assert result.region == "ISR", f"ISR should be recognized as region, got {result.region}"
    assert result.bare_name == "Israeli Channel"


def test_som_somalia_token():
    """SOM token should be recognized as Somalia."""
    result = parse_channel_name("SOM ★ Somali TV")
    assert result.region == "SOM", f"SOM should be recognized as region, got {result.region}"
    assert result.bare_name == "Somali TV"


def test_next_platform_token():
    """NEXT platform token should be recognized."""
    result = parse_channel_name("NEXT ★ Show Name")
    assert result.region == "NEXT", f"NEXT should be recognized as region (platform), got {result.region}"
    assert result.bare_name == "Show Name"


def test_joyn_platform_token():
    """JOYN platform token should be recognized."""
    result = parse_channel_name("JOYN - Channel Name")
    assert result.region == "JOYN", f"JOYN should be recognized, got {result.region}"
    assert result.bare_name == "Channel Name"


def test_vix_platform_token():
    """VIX platform token should be recognized."""
    result = parse_channel_name("VIX | Content Title")
    assert result.region == "VIX", f"VIX should be recognized, got {result.region}"
    assert result.bare_name == "Content Title"


def test_city_platform_token():
    """CITY platform token should be recognized."""
    result = parse_channel_name("CITY - Local Show")
    assert result.region == "CITY", f"CITY should be recognized, got {result.region}"
    assert result.bare_name == "Local Show"
