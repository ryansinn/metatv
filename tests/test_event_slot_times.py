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

**Read as UTC**, per this module's documented default for an absent zone. The
values say the same: 23:45, 23:05 and 00:40 are 19:45, 19:05 and 19:40 Eastern
— textbook MLB starts — and are nonsense read as the viewer's local clock.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from metatv.core.event_datetime import parse_event_datetime


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
        fix invisible on every existing library.
        """
        from metatv.core.migrations.sports_reclassify import CURRENT_VERSION
        assert CURRENT_VERSION >= 4, (
            "parse_event_datetime gained a form but the reclassify version did "
            "not move — existing rows keep their NULL event_start_time")
