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

from metatv.core.fixture_titles import (
    fixture_display_title, fixture_ingest_title, parse_fixture_opponents,
)


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


class TestFixtureDisplayTitle:
    """SPORT-8: the Sports list's raw provider slot string, replaced by a title.

    "(FLSP 246) | live: Ireland vs England _ Women's Cricket
    (2026-09-03 08:00:00)" is what the row's OWN name looks like; nothing
    derives what should actually be shown.
    """

    def test_a_vs_form_row_becomes_a_matchup(self):
        got = fixture_display_title(
            "(FLSP 204) | hockey:  West Kent Steamers vs Miramichi "
            "Timberwolves (Home) (2026-09-02 18:00:00)")
        assert got == "West Kent Steamers vs Miramichi Timberwolves"

    def test_the_at_form_reads_away_at_home_not_away_vs_home(self):
        """"Lakers @ Celtics" is spoken as "Lakers at Celtics" — the AWAY-@-HOME
        US convention, not a plain "vs" pairing.
        """
        got = fixture_display_title(
            "NBA 03 | Lakers @ Celtics start:2026-09-05 23:00:00 "
            "stop:2026-09-06 02:00:00")
        assert got == "Lakers at Celtics"

    def test_a_no_opponent_row_falls_back_to_the_cleaned_segment(self):
        """The dash-gate rejects "Sunny Dancer" as a team name (not
        uppercase-dominant) — parse_fixture_opponents correctly finds no
        pair, and the fallback still surfaces something better than the
        raw provider slot string: the provider tag and timestamp are gone.
        """
        got = fixture_display_title(
            "(FLSP 900) | horseracing:  EN - Sunny Dancer "
            "(2026-09-03 15:00:00)")
        assert got == "EN - Sunny Dancer"

    def test_a_name_with_no_separator_hint_is_left_alone(self):
        """A racing "X at Y" venue listing has no opponent AND no separator
        hint anywhere — the fallback must not grab a garbage leading
        segment (here, the bare "(FLSP 616)" provider tag would be first).
        """
        got = fixture_display_title(
            "(FLSP 616) | floracing: 2026 Short Track Super Series at "
            "Afton Motorsports Park (Short Track Super Series at Afton) "
            "(2026-09-03 04:56:05)")
        assert got is None

    def test_an_ordinary_ppv_row_with_no_matchup_is_left_alone(self):
        """The exact failure mode a hint-less fallback would have hit: the
        FIRST pipe segment here is "End" (a provider list-ending marker),
        not a title — grabbing it would be worse than leaving the row alone.
        """
        got = fixture_display_title(
            "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | "
            "US: SOCCER PPV 1")
        assert got is None

    def test_empty_and_none_are_declined_not_invented(self):
        assert fixture_display_title("") is None


class TestFixtureIngestTitle:
    """The prefix-detection wrapper: only fixture-classified rows are touched.

    ``update_detected_prefixes`` recomputes ``detected_title`` for EVERY row
    of a provider on EVERY refresh — this wrapper is what stops it from
    deriving a "matchup" out of an ordinary channel name that happens to
    contain a stray " - " or " x ".
    """

    class _Row:
        def __init__(self, name, special_view):
            self.name = name
            self.special_view = special_view

    def test_a_sports_fixture_row_yields_its_title(self):
        row = self._Row(
            "(FLSP 204) | hockey:  West Kent Steamers vs Miramichi "
            "Timberwolves (Home) (2026-09-02 18:00:00)",
            special_view="sports",
        )
        assert fixture_ingest_title(row) == \
            "West Kent Steamers vs Miramichi Timberwolves"

    def test_a_ppv_fixture_row_yields_its_title(self):
        row = self._Row(
            "(FLSP 204) | hockey:  West Kent Steamers vs Miramichi "
            "Timberwolves (Home) (2026-09-02 18:00:00)",
            special_view="ppv",
        )
        assert fixture_ingest_title(row) == \
            "West Kent Steamers vs Miramichi Timberwolves"

    def test_a_non_fixture_row_is_never_touched(self):
        """Un-gated, this exact name IS a "vs" pair — the gate is the whole
        point: an ordinary movie/live channel must never be treated as one.
        """
        row = self._Row("EN - Alien vs Predator (2004)", special_view=None)
        assert fixture_ingest_title(row) is None

    def test_a_live_event_row_is_not_gated_in(self):
        """live_event rows never store opponents in special_content.py either
        — same condition, same exclusion here."""
        row = self._Row(
            "US (Peacock 01) | Lakers vs Celtics (2026-09-05 23:00:00)",
            special_view="live_event",
        )
        assert fixture_ingest_title(row) is None


class TestPrefixDetectionRespectsFixtureTitle:
    """The wiring gap that would make SPORT-8 a no-op in the real app.

    ``update_detected_prefixes`` recomputes ``detected_title`` for EVERY
    channel of a provider on EVERY refresh — and it runs AFTER classification
    within the same provider-load cycle (``ProviderLoader._categorize_special_
    content()`` then ``_update_prefixes_in_thread()``). Without
    ``fixture_ingest_title`` wired into it, the fixture title
    ``update_channel_special_content`` had just written would be silently
    overwritten back to the raw-name parse on the very same refresh, and
    again on every refresh after — this feature would never be visible.
    """

    _FIXTURE_NAME = (
        "(FLSP 204) | hockey:  West Kent Steamers vs Miramichi "
        "Timberwolves (Home) (2026-09-02 18:00:00)")

    @pytest.fixture
    def db(self, tmp_path):
        from metatv.core.database import Database
        d = Database(f"sqlite:///{tmp_path / 'ingest.db'}")
        d.create_tables()
        yield d
        d.close()

    def test_a_fixture_row_keeps_its_matchup_title(self, db):
        """The exact scenario: classify, THEN run prefix detection — the
        title must survive, not revert to the raw provider slot string.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.special_content import update_channel_special_content

        with db.session_scope() as session:
            channel = ChannelDB(
                id="c1", source_id="s1", provider_id="p",
                name=self._FIXTURE_NAME, category="US| SPORTS",
                stream_url="http://x/1", media_type="live",
            )
            update_channel_special_content(channel)   # the categorize phase
            session.add(channel)

        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes()  # the prefix phase, right after

        with db.session_scope(commit=False) as session:
            row = session.query(ChannelDB).filter_by(id="c1").one()
            assert row.detected_title == \
                "West Kent Steamers vs Miramichi Timberwolves", (
                    "the prefix-detection pass overwrote the fixture's "
                    "matchup title back to the raw provider slot string")

    def test_a_second_refresh_does_not_revert_an_already_titled_fixture(self, db):
        """The recurring case: prefix detection runs on EVERY provider
        refresh, whether the row's name changed or not."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.special_content import update_channel_special_content

        with db.session_scope() as session:
            channel = ChannelDB(
                id="c2", source_id="s2", provider_id="p",
                name=self._FIXTURE_NAME, category="US| SPORTS",
                stream_url="http://x/2", media_type="live",
            )
            update_channel_special_content(channel)
            session.add(channel)

        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()
        # A second, unrelated refresh of the same provider.
        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()

        with db.session_scope(commit=False) as session:
            row = session.query(ChannelDB).filter_by(id="c2").one()
            assert row.detected_title == \
                "West Kent Steamers vs Miramichi Timberwolves"

    def test_a_non_fixture_row_is_unaffected(self, db):
        """Non-degeneracy: the ordinary bare-name path still runs for
        everything that is not a title-deriving fixture."""
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            session.add(ChannelDB(
                id="c3", source_id="s3", provider_id="p",
                name="EN - The Godfather (1972)", category="Movies",
                stream_url="http://x/3", media_type="movie",
            ))

        with db.session_scope() as session:
            RepositoryFactory(session).channels.update_detected_prefixes()

        with db.session_scope(commit=False) as session:
            row = session.query(ChannelDB).filter_by(id="c3").one()
            assert row.detected_title == "The Godfather"
