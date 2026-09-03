"""Fixture opponents parsed out of a sports channel name (SPORT-4).

This is the blocker on four settled design features — the Team facet, team
identity, reliable LIVE state, and live status — all of which need to read
``ChannelDB.event_team_a``/``event_team_b`` rather than re-parse the name at
render time (CLAUDE.md: compute once at ingestion, read everywhere else).

Every positive case below is a real string from the owner's live corpus,
2026-09-02, and every negative case is one of the four shapes measured among
the 388 dated fixtures that carry none of the four opponent separators.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from metatv.core.fixture_titles import parse_fixture_opponents


class TestPositiveFixtures:
    """Every measured shape must yield its two opponents."""

    @pytest.mark.parametrize("name,expected", [
        # The MLB-style event-slot form — " x " is the separator, and the
        # start:/stop: schedule tail must be cut before splitting.
        (
            "MLB 12 | Phillies x D-backs start:2026-09-01 02:40:00 "
            "stop:2026-09-01 09:53:20",
            ("Phillies", "D-backs"),
        ),
        # The FLSP provider's "hockey: " kind label plus a trailing
        # "(Home)" annotation and a trailing timestamp paren.
        (
            "(FLSP 204) | hockey:  West Kent Steamers vs Miramichi "
            "Timberwolves (Home) (2026-09-02 18:00:00)",
            ("West Kent Steamers", "Miramichi Timberwolves"),
        ),
        # The FLSP "live: " form: a trailing " _ Field Hockey" decoration
        # AND a trailing parenthesised REPEAT of the same fixture (itself
        # carrying "vs") stacked behind a trailing timestamp — all three
        # must be cut, in the right order, to reach the real pair. Team A
        # keeps its own internal, non-trailing "(MD)" parenthetical.
        (
            "(FLSP 212) | live:  St. Mary's (MD) vs Batten University _ "
            "Field Hockey (St. Mary's (MD) vs Batten) (2026-09-02 18:00:40)",
            ("St. Mary's (MD)", "Batten University"),
        ),
        # The dash-matchup form with a spelled-out league name prefixing
        # team A — trimmed only because "MAJOR LEAGUE BASEBALL" is a KNOWN
        # league name (FIXTURE_LEAGUE_NAME_PREFIXES), not guessed away.
        (
            "NEXT | MAJOR LEAGUE BASEBALL DIAMONDBACKS - PHILLIES | "
            "Tue 01 Sep 03:30 CEST (DK) | …",
            ("DIAMONDBACKS", "PHILLIES"),
        ),
        # The " @ " form — US convention AWAY @ HOME — constructed in the
        # same event-slot style as the MLB example above (not itself in the
        # corpus excerpt, but the same provider grammar).
        (
            "NBA 03 | Lakers @ Celtics start:2026-09-05 23:00:00 "
            "stop:2026-09-06 02:00:00",
            ("Lakers", "Celtics"),
        ),
    ])
    def test_opponents_are_extracted(self, name, expected):
        assert parse_fixture_opponents(name) == expected

    def test_the_at_form_preserves_away_home_order(self):
        """The left side of " @ " is AWAY, the right is HOME — never swapped."""
        team_a, team_b = parse_fixture_opponents(
            "NBA 03 | Lakers @ Celtics start:2026-09-05 23:00:00 "
            "stop:2026-09-06 02:00:00")
        assert (team_a, team_b) == ("Lakers", "Celtics"), (
            "away (Lakers) must come back first, home (Celtics) second — "
            "swapping this would silently misreport who is travelling")


class TestNegativeFixtures:
    """The four non-pair shapes among the 388 must all yield (None, None)."""

    @pytest.mark.parametrize("name", [
        # Racing venue form: "X at Y" names an event AT a venue, not a team
        # pair — "at" is never treated as a separator.
        "(FLSP 616) | floracing: 2026 Short Track Super Series at Afton "
        "Motorsports Park (Short Track Super Series at Afton) "
        "(2026-09-03 04:56:05)",
        # Single-event race: no opponents exist.
        "NEXT | SPAIN: RACE | Sun 13 Sep 11:50 UTC (UK) | …",
        # True non-fixture.
        "NHL Tonight | NHL  2026 | …",
        # A 24/7 rack name — no pipe, no separator at all.
        "ESPN HD",
        # A dash that is NOT a team matchup — "Sunny Dancer" is 18%
        # uppercase, well under the dominance threshold that guards the
        # dash form from an ordinary sentence dash.
        "EN - Sunny Dancer",
    ])
    def test_no_opponents_are_invented(self, name):
        assert parse_fixture_opponents(name) == (None, None)

    def test_empty_name_returns_none_none(self):
        assert parse_fixture_opponents("") == (None, None)


class TestIngestionStoresBothTeams:
    """The parser is only useful if the field actually lands on the row.

    Mirrors ``test_an_event_slot_row_gets_a_start_time`` in
    ``tests/test_event_slot_times.py`` — same real-ChannelDB, no-session
    style.
    """

    def test_a_slot_form_fixture_stores_both_teams(self):
        from metatv.core.database import ChannelDB
        from metatv.core.special_content import update_channel_special_content

        ch = ChannelDB(
            id="p_1",
            name="MLB 04 | Mariners x Red Sox start:2026-08-31 23:45:00 "
                 "stop:2026-09-01 06:58:20",
            media_type="live", category="US| MLB PACKAGE")
        update_channel_special_content(ch)

        assert ch.event_team_a == "Mariners", (
            "the classifier still stores nothing — the Team facet has "
            "nothing to read")
        assert ch.event_team_b == "Red Sox"
        # The pre-existing event-window fields must still land alongside —
        # this slice must not regress SPORT-1's start-time extraction.
        assert ch.event_start_time == datetime(2026, 8, 31, 23, 45)
        assert ch.special_view == "sports"

    def test_a_racing_venue_row_stores_no_opponents(self):
        """A row with genuinely no opponent must not invent one."""
        from metatv.core.database import ChannelDB
        from metatv.core.special_content import update_channel_special_content

        ch = ChannelDB(
            id="p_2",
            name="(FLSP 616) | floracing: 2026 Short Track Super Series at "
                 "Afton Motorsports Park (Short Track Super Series at Afton) "
                 "(2026-09-03 04:56:05)",
            media_type="live", category="US| RACING")
        update_channel_special_content(ch)

        assert ch.event_team_a is None
        assert ch.event_team_b is None
