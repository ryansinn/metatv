"""The provider's event-slot names must yield a start time.

Owner, 2026-09-01: *"There's a bigger issue with Sports. Nothing is ever 'On
Now'"* and *"the channels do have live events RIGHT now and it's showing none"*.

It was never a clock, a timezone or a refresh problem. The times were never
extracted at all. The MLB PACKAGE slots carry their window inside the name:

    MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 stop:2026-09-01 06:58:20

Neither ``_EVENT_ISO_RE`` nor ``_EVENT_DMY_RE`` could see it: both require the
date to sit between pipes (``| 2026-07-04 | 09:00 |``). Measured on the owner's
live database, read-only, 2026-09-01:

    rows whose name carries start:…stop:      56
    ...of those, with event_start_time set     0
    other rows that DO have event_start_time   4,205
    rows genuinely live at 01:03 (hand-parsed) 7

With no start time a row cannot be classified live, upcoming OR finished, so
every dated game fell through to the catch-all "Channels" lane and both time
lanes were permanently empty.

**These times are UTC**, matching the zone-carrying forms above for the same
fixtures, and stored UTC-naive like every other form in this module.

For one day (2026-09-01 -> 09-02) this module read them as machine-LOCAL
wall-clock instead. That change was made on a single observation: the owner
was watching MLB 04 live while the UTC reading filed it "Finished", because
06:58 UTC had passed while 06:58 local had not. The observation matched what
the owner believed at that moment — but it was CONFOUNDED. These slots recycle
stream ids: a slot keeps playing the provider's NEXT game after its own named
fixture ends, so "I am watching this game right now" is not evidence about the
fixture's own listed window — the owner could easily have been watching the
game the slot had already rolled over to.

What actually decides the zone is a cross-grammar anchor: the SAME fixture
appears in the owner's corpus in both the slot form and the zone-carrying
day-name form —

    "MLB 12 | Phillies x D-backs start:2026-09-01 02:40:00 stop:2026-09-01 09:53:20"
    "NEXT | MAJOR LEAGUE BASEBALL DIAMONDBACKS - PHILLIES | Tue 01 Sep 03:30 CEST (DK) | …"

Read as UTC the two starts are ~70 minutes apart (a slot is a padded window
that opens early). Read as local (owner: UTC-6) they are 7h10m apart. Games do
not start seven hours apart in two listings of themselves. If this is ever
doubted again: find the same fixture in the day-name form and compare the two
— do not reason from which start time looks plausible for the sport. The full
four-point case lives as the comment above ``_EVENT_STARTSTOP_RE`` in
``metatv/core/event_datetime.py``.
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime

import pytest

from metatv.core.event_datetime import parse_event_datetime, parse_event_window


class TestEventSlotForm:

    @pytest.mark.parametrize("name,expected", [
        ("MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 stop:2026-09-01 06:58:20",
         datetime(2026, 8, 31, 23, 45)),
        ("MLB 06 | Tigers x Twins start:2026-09-01 00:40:00 stop:2026-09-01 07:53:20",
         datetime(2026, 9, 1, 0, 40)),
        ("MLB 01 | Giants x Braves start:2026-08-31 23:05:00 stop:2026-09-01 06:18:20",
         datetime(2026, 8, 31, 23, 5)),
    ])
    def test_the_start_field_is_read(self, name, expected):
        assert parse_event_datetime(name) == expected, (
            "this is the form that left On Now permanently empty")

    def test_the_stop_field_is_not_mistaken_for_the_start(self):
        """Both are ISO datetimes; taking the wrong one shifts a game by hours."""
        got = parse_event_datetime(
            "MLB 04 | X x Y start:2026-08-31 23:45:00 stop:2026-09-01 06:58:20")
        assert got == datetime(2026, 8, 31, 23, 45)
        assert got != datetime(2026, 9, 1, 6, 58)

    def test_a_T_separator_is_accepted(self):
        assert parse_event_datetime("A | B start:2026-08-31T23:45:00") == \
            datetime(2026, 8, 31, 23, 45)

    def test_a_name_with_no_schedule_still_returns_none(self):
        """29k+ rows are 24/7 channels; None is correct for them, not a failure."""
        assert parse_event_datetime("MLB NETWORK") is None
        assert parse_event_datetime("DE| MLB NETWORK HD") is None


class TestTheOtherFormsStillWork:
    """Non-degeneracy: 4,205 rows already parsed and must keep parsing."""

    @pytest.mark.parametrize("name,expected", [
        ("Match | 27-08-2026 | 14:00 (GMT) |", datetime(2026, 8, 27, 14, 0)),
        ("Match | 2026-07-04 | 09:00 (GMT) |", datetime(2026, 7, 4, 9, 0)),
    ])
    def test_existing_forms_are_unaffected(self, name, expected):
        assert parse_event_datetime(name) == expected


class TestTheWholeClassifierChain:
    """The parser is only useful if the field actually lands on the row."""

    def test_an_event_slot_row_gets_a_start_time(self):
        from metatv.core.database import ChannelDB
        from metatv.core.special_content import update_channel_special_content

        ch = ChannelDB(
            id="p_1",
            name="MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 stop:2026-09-01 06:58:20",
            media_type="live", category="US| MLB PACKAGE")
        update_channel_special_content(ch)

        assert ch.event_start_time == datetime(2026, 8, 31, 23, 45), (
            "the classifier still stores nothing — the Sports lanes stay empty")
        assert ch.special_view == "sports"
        assert ch.sport_type == "baseball"


class TestExistingRowsAreBackfilled:

    def test_the_reclassify_version_moved_with_the_classifier(self):
        """Existing rows hold NULL; only a version bump re-runs them.

        The owner's 56 rows were written before this fix and would keep their
        NULL until the next full source refresh. ``CURRENT_VERSION`` is, in that
        module's own words, "the executable statement of 'the classifier
        changed'" — so changing the classifier without bumping it leaves the
        fix invisible on every existing library. Floor raised to 7 for the
        UTC-not-local correction below — that fix also needs a recompute pass
        to reach rows already stored (and stored wrong) under the local
        reading. Raised again to 8 for SPORT-4 (fixture opponents): every
        existing dated fixture holds NULL event_team_a/event_team_b until a
        recompute pass reaches it, same reasoning as every version above.
        """
        from metatv.core.migrations.sports_reclassify import CURRENT_VERSION
        assert CURRENT_VERSION >= 8, (
            "the slot-form UTC fix needs a reclassify version bump too — "
            "existing rows keep their machine-local-shifted event_start_time "
            "otherwise")


class TestSlotTimesAreUtc:
    """The decisive regression: slot times must not depend on machine TZ.

    Both tests are meaningless under UTC-as-machine-TZ CI runners, so they
    force a non-UTC zone (``America/Denver``, the owner's own -6h/-7h zone)
    before parsing. ``time.tzset`` is POSIX-only, so this whole class is
    skipped where it does not exist (rare, but real) rather than erroring.
    """

    @pytest.fixture(autouse=True)
    def _require_tzset(self):
        if not hasattr(time, "tzset"):
            pytest.skip("time.tzset is POSIX-only; not available here")

    def _with_denver_tz(self, fn):
        """Run *fn* with TZ=America/Denver, restoring the prior TZ after."""
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        try:
            return fn()
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_slot_times_are_utc_not_machine_local(self):
        """Under the old local reading this test is RED: Denver is UTC-6 in
        September, so 02:40/09:53 in the name would come back as 08:40/15:53.
        """
        window = self._with_denver_tz(lambda: parse_event_window(
            "MLB 12 | Phillies x D-backs start:2026-09-01 02:40:00 "
            "stop:2026-09-01 09:53:20"))
        assert window.start == datetime(2026, 9, 1, 2, 40)
        assert window.stop == datetime(2026, 9, 1, 9, 53)

    def test_slot_and_dayname_forms_agree_on_the_same_fixture(self):
        """The cross-grammar anchor pair — the property that FAILED under the
        local reading (7h10m apart) and holds under UTC (~70 minutes apart,
        since a slot is a padded window that opens early).
        """
        slot_name = (
            "MLB 12 | Phillies x D-backs start:2026-09-01 02:40:00 "
            "stop:2026-09-01 09:53:20")
        dayname_name = (
            "NEXT | MAJOR LEAGUE BASEBALL DIAMONDBACKS - PHILLIES | "
            "Tue 01 Sep 03:30 CEST (DK) | …")

        def _parse_both():
            slot_start = parse_event_datetime(slot_name)
            dayname_start = parse_event_datetime(
                dayname_name, reference=date(2026, 9, 1))
            return slot_start, dayname_start

        slot_start, dayname_start = self._with_denver_tz(_parse_both)

        assert slot_start is not None
        assert dayname_start is not None
        delta_hours = abs((slot_start - dayname_start).total_seconds()) / 3600
        assert delta_hours < 2, (
            f"the same fixture in two grammars should agree within ~70 "
            f"minutes under UTC; got {delta_hours:.2f}h apart — that is the "
            f"7h10m the old local reading produced")


class TestFlspIdiomIsEastern:
    """SPORT-5: the FLSP/flolive paren-timestamp clock is US Eastern.

    Owner-observed, 2026-09-03 — see the evidence block above
    ``_FLSP_IDIOM_RE`` in ``event_datetime.py``: an FLSP fixture listed
    18:00:00 was played dead at 18:37 UTC (18:00 ET = 22:00 UTC, the game had
    not started), and a second row listed 08:00:00 was the app's ONE "On now"
    row while mpv showed a black pre-air slate (08:00 ET = 12:00 UTC, a
    normal cricket start; 08:00 UTC = 09:00 BST is not).

    Forces a non-UTC MACHINE timezone the same way ``TestSlotTimesAreUtc``
    does — ``ZoneInfo("America/New_York")`` conversion must come from the
    IANA zone, never from the machine's own local clock underneath.
    """

    @pytest.fixture(autouse=True)
    def _require_tzset(self):
        if not hasattr(time, "tzset"):
            pytest.skip("time.tzset is POSIX-only; not available here")

    def _with_denver_tz(self, fn):
        old_tz = os.environ.get("TZ")
        os.environ["TZ"] = "America/Denver"
        time.tzset()
        try:
            return fn()
        finally:
            if old_tz is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old_tz
            time.tzset()

    def test_the_flsp_idiom_converts_from_eastern_daylight(self):
        """September is EDT (UTC-4): 08:00 ET -> 12:00 UTC.

        This is the exact row from the owner's second observation — the ONE
        "On now" row while mpv showed a black pre-air slate.
        """
        name = ("(FLSP 246) | live: Ireland vs England _ Women's Cricket "
                "(2026-09-03 08:00:00)")
        got = self._with_denver_tz(lambda: parse_event_datetime(name))
        assert got == datetime(2026, 9, 3, 12, 0), (
            "under the old UTC reading this stays 08:00, which is what "
            "wrongly listed a not-yet-started game as On Now")

    def test_the_flsp_idiom_converts_from_eastern_standard_in_january(self):
        """January is EST (UTC-5): 18:00 ET -> 23:00 UTC — proves DST-awareness.

        A fixed UTC-4 offset (no DST table) would pass the September case
        above and still be wrong here by an hour.
        """
        name = "(FLSP 999) | live: A vs B (2026-01-15 18:00:00)"
        got = self._with_denver_tz(lambda: parse_event_datetime(name))
        assert got == datetime(2026, 1, 15, 23, 0)

    def test_a_non_flsp_platform_sharing_the_same_grammar_is_unaffected(self):
        """SCOPE STRICTLY: the other ~2,800 paren-timestamp rows stay UTC.

        Same clock digits as the FLSP case above, different provider tag —
        must come back UNCHANGED (byte-for-byte UTC), not shifted.
        """
        name = "US (Paramount 001) | Chelsea vs. Luton Town (2026-09-03 08:00:00)"
        got = self._with_denver_tz(lambda: parse_event_datetime(name))
        assert got == datetime(2026, 9, 3, 8, 0), (
            "a non-FLSP platform must not be pulled into the Eastern "
            "conversion — only the FLSP idiom is in scope")
