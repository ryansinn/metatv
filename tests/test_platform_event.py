"""EPG-embedded event-feed parsing (TREX/Ninja "REGION (NETWORK CH#) | Title (time)").

Some providers inline a scheduled programme in the channel name:
"US (Peacock 01) | La Vuelta a España: Stage 11 (2025-09-03 07:20:00)". This is both
a channel (region + clean title) and a scheduled event (network, channel#, start time).
`parse_platform_event` decomposes it; `update_channel_special_content` marks it a
live_event and stores the event fields. These tests execute the real parsers.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from metatv.core.channel_name_utils import parse_platform_event, parse_channel_name
from metatv.core.special_content import (
    detect_platform_event_channel,
    update_channel_special_content,
)


# ── parse_platform_event ──────────────────────────────────────────────────────── #

def test_scheduled_event_all_fields():
    pe = parse_platform_event(
        "US (Peacock 01) | La Vuelta a España: Stage 11 (2025-09-03 07:20:00)"
    )
    assert pe is not None
    assert pe.region == "US"
    assert pe.network == "Peacock"
    assert pe.channel_num == "01"
    assert pe.title == "La Vuelta a España: Stage 11"
    assert pe.start_time == datetime(2025, 9, 3, 7, 20, 0)
    assert pe.always_available is False


def test_network_with_plus_and_three_digit_channel():
    pe = parse_platform_event("CA (TSN+ 001) | ATP 250 Tennis: Stuttgart (2026-06-08 05:00:00)")
    assert pe.region == "CA"
    assert pe.network == "TSN+"
    assert pe.channel_num == "001"


def test_far_future_timestamp_is_always_available():
    pe = parse_platform_event("US (ESPN+ 391) | Some Show (2098-12-31 08:00:01)")
    assert pe.always_available is True
    assert pe.start_time is None          # sentinel is not a real schedule time
    assert pe.title == "Some Show"


def test_form_a_network_feed_no_time():
    # "US (P+) AFC Champions League 1" — a network feed, not a scheduled programme.
    pe = parse_platform_event("US (P+) AFC Champions League 1")
    assert pe is not None
    assert pe.network == "P+"
    assert pe.channel_num == ""
    assert pe.start_time is None
    assert pe.always_available is False
    assert pe.title == "AFC Champions League 1"


def test_rejects_unknown_region():
    # "NCIS" is a title word, not a region — must not parse as an event.
    assert parse_platform_event("NCIS (CBS) Episode") is None


def test_rejects_bare_year_paren():
    # "FBI (2024) Reboot" — paren is a year (no leading letter) → not a network.
    assert parse_platform_event("FBI (2024) Reboot") is None


# ── parse_channel_name integration (channel axis) ─────────────────────────────── #

def test_parse_channel_name_clean_title_and_region():
    p = parse_channel_name(
        "US (Peacock 01) | La Vuelta a España: Stage 11 (2025-09-03 07:20:00)"
    )
    assert p.region == "US"
    assert p.bare_name == "La Vuelta a España: Stage 11"   # network/pipe/time stripped


# ── special_content classification (event axis) ───────────────────────────────── #

def _chan(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name, stream_url="http://x", category="",
        special_view=None, event_start_time=None, event_metadata=None,
        sport_type=None, league_name=None, team_name=None,
    )


def test_detect_scheduled_event():
    assert detect_platform_event_channel(
        _chan("AU (STAN 01) | France v Northern Ireland (2026-06-09 05:00:29)")
    ) is True


def test_detect_form_a_is_not_an_event():
    # No timestamp → a network channel, handled by keyword detectors, not here.
    assert detect_platform_event_channel(_chan("US (P+) AFC Champions League 1")) is False


def test_update_sets_live_event_and_metadata():
    c = _chan("CA (TSN+ 001) | ATP 250 Tennis: Stuttgart (2026-06-08 05:00:00)")
    assert update_channel_special_content(c) is True
    assert c.special_view == "live_event"
    assert c.event_start_time == datetime(2026, 6, 8, 5, 0, 0)
    assert c.event_metadata["network"] == "TSN+"
    assert c.event_metadata["channel_num"] == "001"
    assert c.event_metadata["region"] == "CA"
    assert c.event_metadata["availability"] == "scheduled"
    assert c.sport_type == "tennis"


def test_update_always_available_event():
    c = _chan("US (ESPN+ 391) | Some Show (2098-12-31 08:00:01)")
    update_channel_special_content(c)
    assert c.special_view == "live_event"
    assert c.event_start_time is None
    assert c.event_metadata["availability"] == "always"
