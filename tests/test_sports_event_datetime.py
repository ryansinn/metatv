"""A sports fixture's start time must survive all three provider date forms.

Measured on the owner's library, 2026-08-31 — 30,851 sports/live-event/PPV rows,
1,358 of which carry a date:

    | 27-08-2026 | 14:00 (GMT) |      654 rows   parsed before this change
    | Sat 29 Aug 14:00 CEST (DK) |    555 rows   NOT PARSED AT ALL
    | 2026-07-04 | 09:00 (GMT) |      149 rows   NOT PARSED AT ALL

Two traps sit inside the second form, and both are silent:

1. **It names a local zone**, and 494 of those 555 rows are not GMT (CEST 301,
   EDT 193, NDT 20, EEST 7, EST 6). A parser that assumes UTC is one to four
   hours out on 89% of them — and *almost* right is the worst kind of wrong,
   because nothing looks broken.
2. **It carries no year.** The weekday name is the checksum that recovers it:
   over 2025-2027, all 555 rows resolve to exactly one year — 0 ambiguous,
   0 unmatched.

And the reach matters as much as the parse: 927 of the dated rows classify as
``sports``, a branch that extracted no time at all, so a parser fix alone would
have reached 431 rows that already had one. That is the #591 failure — a
classifier fix that reached nothing — and the tests below pin the wiring, not
just the regex.
"""

from __future__ import annotations

import datetime

import pytest

from metatv.core.event_datetime import parse_event_datetime
from metatv.core.database import ChannelDB
from metatv.core.migrations.sports_reclassify import CURRENT_VERSION, DERIVED_FIELDS
from metatv.core.special_content import update_channel_special_content


#: A Monday. Every relative-year case below is resolved against this, never the
#: real clock — a function given a reference date must not reach past it.
REF = datetime.date(2026, 8, 31)


# ── the three date forms ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name,expected", [
    # Form 1 — day-month-year. The only one parsed before this change.
    ("End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K | US: SOCCER PPV 1",
     datetime.datetime(2026, 5, 11, 9, 37)),
    # Form 3 — ISO.
    ("End | Arnold Palmer Cup | Golf Dag 2 | 2026-07-04 | 09:00 (GMT) | 8K",
     datetime.datetime(2026, 7, 4, 9, 0)),
    # Form 2 — day-name, no year, local zone. CEST is UTC+2, so 14:00 -> 12:00Z.
    ("LIVE | 1. FC KOLN U21 VS SPORTFREUNDE LOTTE | Sat 29 Aug 14:00 CEST (DE) | 8K",
     datetime.datetime(2026, 8, 29, 12, 0)),
])
def test_every_provider_date_form_parses(name, expected):
    assert parse_event_datetime(name, reference=REF) == expected


@pytest.mark.parametrize("name,expected", [
    # Form 4 — trailing parenthesised timestamp. 2,843 rows carry it and 842
    # stored NOTHING, because parse_platform_event only runs on the
    # 'live_event' branch while 603 of these classify as 'sports'.
    ("(FLSP 697) | flohockey: 2026 Brockville Braves vs Cornwall Colts (Home) (2026-09-03 19:00:25)",
     datetime.datetime(2026, 9, 3, 19, 0)),
    ("US (Paramount 001) | Chelsea vs. Luton Town (2026-08-27 14:20:00)",
     datetime.datetime(2026, 8, 27, 14, 20)),
    # Form 5 — "@ Mon DD H:MM AM/PM". 205 rows, and the exact shape the owner
    # screenshotted: Tennis showing four-day-old qualifiers with no time.
    ("US Open: Court 5 - Qualifying Third Round @ Aug 27 11:00 AM :Tennis  03",
     datetime.datetime(2026, 8, 27, 11, 0)),
    ("US Open: Stars of the Open presented by Chase @ Aug 27 6:00 PM :Tennis  14",
     datetime.datetime(2026, 8, 27, 18, 0)),
])
def test_the_two_later_date_forms_parse(name, expected):
    assert parse_event_datetime(name, reference=REF) == expected


@pytest.mark.parametrize("clock,hour24", [
    ("12:00 AM", 0),    # midnight is 00, not 12 — the classic off-by-twelve
    ("12:30 PM", 12),   # noon stays 12
    ("1:00 AM", 1),
    ("11:45 PM", 23),
])
def test_the_twelve_hour_clock_converts_at_both_ends(clock, hour24):
    name = f"MLB 13 | Baltimore vs Tampa Bay @ Aug 14 {clock}"
    got = parse_event_datetime(name, reference=REF)
    assert got is not None and got.hour == hour24


def test_the_always_available_sentinel_is_not_a_schedule():
    """Providers use a far-future date to mean "always on", not "starts then".

    Rendered as a start it would put every always-on feed at the bottom of
    Upcoming, seventy years out.
    """
    assert parse_event_datetime("Some 24/7 feed (2098-12-31 00:00:00)", reference=REF) is None


def test_a_name_with_no_date_yields_none_rather_than_a_guess():
    """29,493 of 30,851 rows are 24/7 channels. None is the correct answer."""
    for name in ("4K| SKY SPORTS MAIN EVENTS UHD", "US| FOX SPORTS 1 HD", "", "   "):
        assert parse_event_datetime(name, reference=REF) is None


# ── the timezone trap ────────────────────────────────────────────────────────

@pytest.mark.parametrize("zone,offset_hours", [
    ("CEST", 2),    # 301 rows
    ("EDT", -4),    # 193 rows
    ("EEST", 3),    # 7 rows
    ("EST", -5),    # 6 rows
    ("NDT", -2.5),  # 20 rows — a half-hour zone, so an int-hours fix breaks here
    ("UTC", 0),     # 22 rows
    ("GMT", 0),     # 6 rows
])
def test_the_named_zone_is_converted_not_ignored(zone, offset_hours):
    """Every zone the corpus actually contains, converted to UTC.

    This is the assertion that fails if someone builds the datetime naively:
    494 of 555 day-name rows would land 1-4 hours wrong while looking fine.
    """
    name = f"LIVE | Some Fixture | Sat 29 Aug 14:00 {zone} (XX) | 8K"
    got = parse_event_datetime(name, reference=REF)
    expected = datetime.datetime(2026, 8, 29, 14, 0) - datetime.timedelta(hours=offset_hours)
    assert got == expected, f"{zone} should be UTC{offset_hours:+g}"


def test_zones_differing_only_by_dst_are_not_collapsed():
    """CET/CEST and EST/EDT differ by an hour. Treating them as one loses it."""
    winter = parse_event_datetime("LIVE | X | Sat 29 Aug 14:00 CET (DE) | 8K", reference=REF)
    summer = parse_event_datetime("LIVE | X | Sat 29 Aug 14:00 CEST (DE) | 8K", reference=REF)
    assert winter is not None and summer is not None
    assert winter - summer == datetime.timedelta(hours=1)


def test_an_ambiguous_zone_is_not_guessed():
    """CST is US Central (-6) or China Standard (+8). Neither is in the corpus.

    Guessing an offset is worse than declining, so an unknown abbreviation falls
    back to UTC rather than inventing an hour. Pinned so nobody "helpfully" adds
    CST to the table without deciding which one it means.
    """
    got = parse_event_datetime("LIVE | X | Sat 29 Aug 14:00 CST (XX) | 8K", reference=REF)
    assert got == datetime.datetime(2026, 8, 29, 14, 0)


# ── the missing year ─────────────────────────────────────────────────────────

def test_the_weekday_name_recovers_the_missing_year():
    """29 Aug is a Saturday in 2026 and a Friday in 2025 — the name disambiguates."""
    got = parse_event_datetime("LIVE | X | Sat 29 Aug 14:00 UTC (XX) | 8K", reference=REF)
    assert got == datetime.datetime(2026, 8, 29, 14, 0)
    # Same date, wrong weekday for 2026: 2025 is the year where 29 Aug is a Friday.
    got = parse_event_datetime("LIVE | X | Fri 29 Aug 14:00 UTC (XX) | 8K", reference=REF)
    assert got == datetime.datetime(2025, 8, 29, 14, 0)


def test_the_year_is_taken_from_the_reference_not_the_real_clock():
    """A function handed a reference date must not reach for the clock underneath.

    Three injected-clock bugs were found in this codebase in one day; one of them
    silently deleted 29.75 days instead of 30.
    """
    name = "LIVE | X | Sat 29 Aug 14:00 UTC (XX) | 8K"
    in_2020 = parse_event_datetime(name, reference=datetime.date(2020, 8, 31))
    assert in_2020 is not None
    assert in_2020.year == 2020, "resolved against the real clock, not the reference"


def test_a_date_that_cannot_exist_yields_none():
    """31 February is malformed, not a fixture."""
    assert parse_event_datetime("End | X | all | 31-02-2026 | 09:00 (GMT)", reference=REF) is None


def test_a_time_inside_the_title_is_not_mistaken_for_the_start():
    """The old parser took the FIRST HH:MM anywhere in the name.

    A title carrying a clock-like token stole the schedule slot. The form-anchored
    patterns read the time from the date field, so the title cannot poison it.
    """
    name = "End | Match 12:34 Special | all | 11-05-2026 | 09:37 (GMT) | 8K"
    assert parse_event_datetime(name, reference=REF) == datetime.datetime(2026, 5, 11, 9, 37)


# ── the reach: it has to land on the rows that were empty ────────────────────

def test_a_dated_fixture_classified_as_sports_gets_its_start_time():
    """927 dated rows classify as 'sports', a branch that stored no time at all.

    This is the assertion that separates a parser fix from a fix that reaches
    someone: without the sports-branch wiring the parse is correct and the column
    stays NULL, exactly as in #591.
    """
    channel = ChannelDB(
        id="c1", source_id="1", provider_id="p", media_type="live", stream_url="u",
        category="SOCCER PPV",
        name="LIVE | KOLN U21 VS LOTTE | Sat 29 Aug 14:00 CEST (DE) | 8K | DE: SOCCER PPV 3",
    )
    update_channel_special_content(channel)

    assert channel.special_view == "sports", "precondition: this row is not the ppv branch"
    assert channel.event_start_time == datetime.datetime(2026, 8, 29, 12, 0)


def test_a_24_7_sports_channel_keeps_a_null_start_time():
    """The other direction — the rack must not acquire an invented schedule."""
    channel = ChannelDB(id="c2", source_id="2", provider_id="p", media_type="live",
                        stream_url="u", category="SPORTS", name="US| FOX SPORTS 1 HD")
    update_channel_special_content(channel)
    assert channel.special_view == "sports"
    assert channel.event_start_time is None


# ── the backfill ─────────────────────────────────────────────────────────────

def test_the_classifier_version_was_bumped_for_this_change():
    """Without a bump the fix reaches NEW rows only and the stored data drifts.

    sports_reclassify.py's own module note: "A future change to
    special_content.py must bump it." This pins that it happened.
    """
    assert CURRENT_VERSION >= 2


def test_the_reclassify_task_owns_event_start_time():
    """The reset-then-recompute must clear the field this change writes.

    If event_start_time were not in DERIVED_FIELDS, a row whose time was parsed
    wrongly before would keep the stale value through the sweep.
    """
    assert "event_start_time" in DERIVED_FIELDS
