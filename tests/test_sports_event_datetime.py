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

from metatv.core.event_datetime import (DEFAULT_EVENT_DURATION,
                                        event_is_on_now,
                                        parse_event_datetime,
                                        parse_event_window)
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
    #
    # This is the FLSP idiom (SPORT-5): its clock is US Eastern, not UTC —
    # 19:00 EDT (UTC-4) on 2026-09-03 is 23:00 UTC. See the evidence block
    # above _FLSP_IDIOM_RE in event_datetime.py.
    ("(FLSP 697) | flohockey: 2026 Brockville Braves vs Cornwall Colts (Home) (2026-09-03 19:00:25)",
     datetime.datetime(2026, 9, 3, 23, 0)),
    # A DIFFERENT platform carrying the SAME paren-timestamp grammar — stays
    # UTC unchanged (SPORT-5's scope is strictly the FLSP idiom).
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


# ── the other end of the slot form ───────────────────────────────────────────
#
# The provider sends "start:… stop:…" and only the start was ever read, so
# "still on" was a fixed 4h assumption. Measured on the owner's 56 slot rows
# (2026-09-02): windows run 3.00h to 7.22h, median 7.22h. 32 run LONGER than
# the assumption — a median 3.22h of every slot filed "Finished" while the game
# was on, which is the owner's "Nothing is ever On Now" — and 24 run SHORTER,
# listed as on-now after they ended, on a recycled stream id that then plays a
# different game.

#: The owner's own row, verbatim, and the window is 7h13m20s.
_MLB04 = "MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 stop:2026-09-01 06:58:20"


def test_the_slot_form_yields_both_ends():
    window = parse_event_window(_MLB04, reference=REF)
    assert window.start is not None and window.stop is not None
    assert window.stop - window.start == datetime.timedelta(hours=7, minutes=13)


def test_both_ends_are_converted_the_same_way():
    """Local in, UTC-naive out — for BOTH ends or the window is hours out.

    A start read as local and a stop read as UTC would leave the duration
    intact-looking while placing the window somewhere else entirely, which is
    the failure mode that already shipped once on the start alone.
    """
    window = parse_event_window(_MLB04, reference=REF)
    naive_start = datetime.datetime(2026, 8, 31, 23, 45)
    naive_stop = datetime.datetime(2026, 9, 1, 6, 58)
    shift = window.start - naive_start
    assert window.stop - naive_stop == shift


@pytest.mark.parametrize("name", [
    "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K | US: SOCCER PPV 1",
    "End | Arnold Palmer Cup | Golf Dag 2 | 2026-07-04 | 09:00 (GMT) | 8K",
    "LIVE | 1. FC KOLN U21 VS SPORTFREUNDE LOTTE | Sat 29 Aug 14:00 CEST (DE) | 8K",
    "US Open: Court 5 - Qualifying Third Round @ Aug 27 11:00 AM :Tennis  03",
])
def test_every_other_form_names_a_start_and_no_end(name):
    """Only the slot form carries an end. Inventing one for the rest would put
    a confident wrong duration on 31,240 rows to fix 56."""
    window = parse_event_window(name, reference=REF)
    assert window.start is not None
    assert window.stop is None


def test_a_stop_at_or_before_its_start_is_discarded():
    """Honouring a malformed end reads as "already finished" on a fixture that
    has not begun. The assumed duration is the recoverable answer."""
    name = "MLB 09 | A x B start:2026-08-31 23:45:00 stop:2026-08-31 20:00:00"
    window = parse_event_window(name, reference=REF)
    assert window.start is not None
    assert window.stop is None


def test_parse_event_datetime_still_answers_the_start():
    """The old name is the one nearly every caller uses; it must keep working
    and must agree with the parser rather than walking the regexes again."""
    for name in (_MLB04, "US| FOX SPORTS 1 HD", ""):
        assert (parse_event_datetime(name, reference=REF)
                == parse_event_window(name, reference=REF).start)


# ── what the end time is FOR ─────────────────────────────────────────────────

def test_a_long_slot_is_on_now_past_the_assumed_duration():
    """The owner was watching MLB 04 while the app called it Finished."""
    window = parse_event_window(_MLB04, reference=REF)
    five_hours_in = window.start + datetime.timedelta(hours=5)
    assert five_hours_in > window.start + DEFAULT_EVENT_DURATION, "precondition"
    assert event_is_on_now(window.start, window.stop, five_hours_in)


def test_an_event_is_over_at_its_own_end():
    window = parse_event_window(_MLB04, reference=REF)
    assert event_is_on_now(window.start, window.stop,
                           window.stop - datetime.timedelta(minutes=1))
    assert not event_is_on_now(window.start, window.stop, window.stop)


def test_a_row_with_no_end_falls_back_to_the_assumed_duration():
    start = datetime.datetime(2026, 8, 31, 12, 0)
    assert event_is_on_now(start, None, start + DEFAULT_EVENT_DURATION
                           - datetime.timedelta(minutes=1))
    assert not event_is_on_now(start, None, start + DEFAULT_EVENT_DURATION)


def test_a_row_with_no_start_is_never_on_now():
    """923 live_event rows are "always available" — a different thing, and not
    this predicate's to claim."""
    assert not event_is_on_now(None, None, datetime.datetime(2026, 8, 31, 12, 0))


def test_an_event_has_not_started_before_its_start():
    start = datetime.datetime(2026, 8, 31, 12, 0)
    assert not event_is_on_now(start, None, start - datetime.timedelta(seconds=1))
    assert event_is_on_now(start, None, start)


# ── the wiring, again: a parse that reaches nobody is #591 ───────────────────

def test_a_slot_form_fixture_stores_both_ends():
    """Without the sports-branch wiring the parse is right and the column is
    NULL — the exact shape of #591."""
    channel = ChannelDB(
        id="c3", source_id="3", provider_id="p", media_type="live",
        stream_url="u", category="SPORTS", name=_MLB04,
    )
    update_channel_special_content(channel)
    assert channel.special_view == "sports", "precondition: not the ppv branch"
    assert channel.event_start_time is not None
    assert channel.event_stop_time is not None
    assert (channel.event_stop_time - channel.event_start_time
            == datetime.timedelta(hours=7, minutes=13))


def test_a_24_7_sports_channel_keeps_a_null_end_time():
    channel = ChannelDB(id="c4", source_id="4", provider_id="p", media_type="live",
                        stream_url="u", category="SPORTS", name="US| FOX SPORTS 1 HD")
    update_channel_special_content(channel)
    assert channel.event_stop_time is None


def test_the_reclassify_task_owns_event_stop_time():
    """Existing rows already have a start, so nothing looks broken — only the
    sweep gives them the end time, and only if the field is derived here."""
    assert "event_stop_time" in DERIVED_FIELDS
    assert CURRENT_VERSION >= 6
