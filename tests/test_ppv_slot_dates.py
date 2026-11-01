"""Dated PPV slots the classifier files under no event view still store their
window (v13), so "Hide finished events" can hide a finished game's black slot.

Owner, 2026-11-01: "all these MLS PPV channels … are just black screens" —
"(Apple) (MLS) 005 | Miami vs. Cincinnati (Spanish) (2026-10-28 19:25:20)"
stored no start time, so nothing could tell it was over.
"""

from __future__ import annotations

from datetime import datetime

from metatv.core.database import ChannelDB
from metatv.core.migrations.sports_reclassify import CURRENT_VERSION
from metatv.core.special_content import update_channel_special_content


def _ch(name: str, media_type: str = "live") -> ChannelDB:
    return ChannelDB(id="x", source_id="x", provider_id="p", name=name, media_type=media_type)


def test_unclassified_dated_slot_stores_its_start():
    ch = _ch("(Apple) (MLS) 005 |  Miami vs. Cincinnati (Spanish) (2026-10-28 19:25:20)")
    update_channel_special_content(ch)
    assert ch.event_start_time == datetime(2026, 10, 28, 19, 25)


def test_placeholder_slot_stores_its_sentinel_start_not_a_real_date():
    # v14: an EMPTY slot keeps its far-future sentinel as its start, so the
    # "start more than N in the future" exclusion hides it; it never reads as
    # a near date and never as finished.
    ch = _ch("(Victory+ 002) |  (2098-12-31 08:00:01)")
    update_channel_special_content(ch)
    assert ch.event_start_time is not None and ch.event_start_time.year == 2098


def test_vod_names_are_never_read_as_schedules():
    ch = _ch("Some Film (2026-10-28 19:25:20)", media_type="movie")
    update_channel_special_content(ch)
    assert ch.event_start_time is None


def test_classifier_version_bumped_so_existing_rows_are_recomputed():
    assert CURRENT_VERSION >= 14
