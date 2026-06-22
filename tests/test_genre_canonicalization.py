"""Behavioral tests for genre canonicalization fixes.

Two bugs fixed in this PR:
  A) HTML entities in genre strings created duplicate shelves:
       "Action &amp; Adventure" and "Action & Adventure" were treated as
       different genres — two shelves would appear in Discover.
  B) Compound/component genre over-matching: the 'Science Fiction' shelf
       pulled in 'Sci-Fi & Fantasy' items because the SQL LIKE %sci-fi% was
       a substring of 'Sci-Fi & Fantasy'.  Same for 'Action' vs
       'Action & Adventure', 'War' vs 'War & Politics', etc.

Tests here execute the actual code paths that could regress.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def genre_compound_db(tmp_path):
    """A file-backed DB with channels covering compound/component edge-cases.

    Genres inserted:
      pure "Science Fiction"      — 5 rows
      compound "Sci-Fi & Fantasy" — 5 rows
      pure "Action"               — 4 rows
      compound "Action & Adventure" — 4 rows
      pure "Fantasy"              — 3 rows
      compound "War & Politics"   — 3 rows
      pure "War"                  — 3 rows
      HTML-entity "Action &amp; Adventure" — 3 rows (should canonicalize to compound)
    """
    from metatv.core.database import Database, ChannelDB, ProviderDB

    db = Database(f"sqlite:///{tmp_path / 'genre_compound.db'}")
    db.create_tables()
    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="P", type="xtream",
            url="http://x.example.com", is_active=True,
        ))
        entries = [
            ("Science Fiction",        5),
            ("Sci-Fi & Fantasy",       5),
            ("Action",                 4),
            ("Action & Adventure",     4),
            ("Fantasy",                3),
            ("War & Politics",         3),
            ("War",                    3),
            # HTML-entity variant — should collapse into "Action & Adventure"
            ("Action &amp; Adventure", 3),
        ]
        for label, n in entries:
            for i in range(n):
                session.add(ChannelDB(
                    id=str(uuid.uuid4()),
                    source_id=f"{label}_{i}",
                    provider_id="p1",
                    name=f"Movie {label} {i}",
                    media_type="movie",
                    raw_data={"genre": label, "rating": "7.0"},
                ))
        session.commit()
    finally:
        session.close()
    yield db
    db.close()


# ---------------------------------------------------------------------------
# Bug A — HTML entities
# ---------------------------------------------------------------------------

class TestHtmlEntityUnescaping:
    """normalize_genre must unescape &amp; (and other HTML entities) before lookup."""

    def test_normalize_genre_unescapes_amp(self):
        """normalize_genre("Action &amp; Adventure") == normalize_genre("Action & Adventure")"""
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Action &amp; Adventure") == normalize_genre("Action & Adventure")

    def test_normalize_genre_unescapes_scifi(self):
        """normalize_genre("Sci-Fi &amp; Fantasy") == normalize_genre("Sci-Fi & Fantasy")"""
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Sci-Fi &amp; Fantasy") == normalize_genre("Sci-Fi & Fantasy")

    def test_normalize_genre_unescapes_war(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("War &amp; Politics") == normalize_genre("War & Politics")

    def test_normalize_genre_idempotent_on_plain(self):
        """normalize_genre on a non-entity string is unchanged."""
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Drama") == "Drama"
        assert normalize_genre("Action & Adventure") == "Action & Adventure"

    def test_get_all_genres_no_html_entity_duplicates(self, genre_compound_db):
        """get_all_genres must NOT return both 'Action & Adventure' and
        'Action &amp; Adventure' as separate genres.

        The HTML-entity variant in raw_data must collapse into the canonical
        unescaped name so only one shelf is produced.
        """
        from metatv.core.discovery_engine import get_all_genres

        session = genre_compound_db.get_session()
        try:
            genres = get_all_genres(session, min_count=1)
        finally:
            session.close()

        # No raw HTML-entity variant must appear as a shelf key
        assert "Action &amp; Adventure" not in genres, (
            f"HTML-entity genre leaked into shelf list: {genres}"
        )
        # The clean canonical form must be present (4 + 3 = 7 items ≥ 1)
        assert "Action & Adventure" in genres, (
            f"'Action & Adventure' missing from genre list: {genres}"
        )

    def test_get_by_genre_html_entity_rows_appear_in_shelf(self, genre_compound_db):
        """get_by_genre('Action & Adventure') must include rows whose raw_data
        genre is 'Action &amp; Adventure' (the HTML-encoded variant).
        """
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "Action & Adventure", limit=50)
        finally:
            session.close()

        # 4 plain "Action & Adventure" rows + 3 "&amp;" rows = 7 total
        assert len(cards) == 7, (
            f"Expected 7 cards (4 plain + 3 &amp; variant), got {len(cards)}: "
            f"{[c.title for c in cards]}"
        )


# ---------------------------------------------------------------------------
# Bug B — compound/component segment boundary
# ---------------------------------------------------------------------------

class TestCompoundComponentSeparation:
    """Components ('sci-fi', 'action', 'war', 'fantasy') must NOT pull in
    compound rows ('Sci-Fi & Fantasy', 'Action & Adventure', 'War & Politics').
    And vice-versa: compounds must not absorb pure components.
    """

    def test_science_fiction_shelf_excludes_scifi_and_fantasy(self, genre_compound_db):
        """get_by_genre('Science Fiction') must NOT return 'Sci-Fi & Fantasy' rows."""
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "Science Fiction", limit=50)
        finally:
            session.close()

        titles = [c.title for c in cards]
        assert all("Sci-Fi" not in t for t in titles), (
            f"'Science Fiction' shelf pulled in Sci-Fi & Fantasy rows: "
            f"{[t for t in titles if 'Sci-Fi' in t]}"
        )
        # And it must have the pure "Science Fiction" rows
        assert any("Science Fiction" in t for t in titles), (
            "Pure 'Science Fiction' rows are missing from the shelf"
        )

    def test_scifi_fantasy_shelf_excludes_pure_science_fiction(self, genre_compound_db):
        """get_by_genre('Sci-Fi & Fantasy') must NOT include pure 'Science Fiction' rows."""
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "Sci-Fi & Fantasy", limit=50)
        finally:
            session.close()

        titles = [c.title for c in cards]
        # Pure "Science Fiction" rows must NOT appear here
        assert all("Science Fiction" not in t or "Sci-Fi" in t for t in titles), (
            f"'Sci-Fi & Fantasy' shelf pulled in pure Science Fiction rows: "
            f"{[t for t in titles if 'Science Fiction' in t]}"
        )
        # Must have the compound "Sci-Fi & Fantasy" rows (5 inserted)
        assert len(cards) == 5, (
            f"Expected 5 'Sci-Fi & Fantasy' rows, got {len(cards)}: {titles}"
        )

    def test_action_shelf_excludes_action_and_adventure(self, genre_compound_db):
        """get_by_genre('Action') must NOT return 'Action & Adventure' rows."""
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "Action", limit=50)
        finally:
            session.close()

        titles = [c.title for c in cards]
        assert all("Adventure" not in t for t in titles), (
            f"'Action' shelf pulled in 'Action & Adventure' rows: "
            f"{[t for t in titles if 'Adventure' in t]}"
        )
        # Must have the 4 pure "Action" rows
        assert len(cards) == 4, (
            f"Expected 4 pure 'Action' rows, got {len(cards)}: {titles}"
        )

    def test_war_shelf_excludes_war_and_politics(self, genre_compound_db):
        """get_by_genre('War') must NOT return 'War & Politics' rows."""
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "War", limit=50)
        finally:
            session.close()

        titles = [c.title for c in cards]
        assert all("Politics" not in t for t in titles), (
            f"'War' shelf pulled in 'War & Politics' rows: "
            f"{[t for t in titles if 'Politics' in t]}"
        )
        assert len(cards) == 3, (
            f"Expected 3 pure 'War' rows, got {len(cards)}: {titles}"
        )

    def test_fantasy_shelf_excludes_scifi_and_fantasy(self, genre_compound_db):
        """get_by_genre('Fantasy') must NOT return 'Sci-Fi & Fantasy' rows."""
        from metatv.core.discovery_engine import get_by_genre

        session = genre_compound_db.get_session()
        try:
            cards = get_by_genre(session, "Fantasy", limit=50)
        finally:
            session.close()

        titles = [c.title for c in cards]
        assert all("Sci-Fi" not in t for t in titles), (
            f"'Fantasy' shelf pulled in 'Sci-Fi & Fantasy' rows: "
            f"{[t for t in titles if 'Sci-Fi' in t]}"
        )
        assert len(cards) == 3, (
            f"Expected 3 pure 'Fantasy' rows, got {len(cards)}: {titles}"
        )

    def test_get_all_genres_no_entity_duplicates_compound(self, genre_compound_db):
        """get_all_genres must not return both 'Action & Adventure' and
        'Action &amp; Adventure' simultaneously.
        """
        from metatv.core.discovery_engine import get_all_genres

        session = genre_compound_db.get_session()
        try:
            genres = get_all_genres(session, min_count=1)
        finally:
            session.close()

        assert genres.count("Action & Adventure") == 1, (
            f"'Action & Adventure' appears multiple times in genre list: {genres}"
        )
        assert "Action &amp; Adventure" not in genres

    def test_multi_segment_genre_matches_correct_shelf(self, tmp_path):
        """A channel with genre 'Action & Adventure / Drama' must appear in
        BOTH the 'Action & Adventure' shelf and the 'Drama' shelf — but NOT
        in the pure 'Action' shelf.
        """
        from metatv.core.database import Database, ChannelDB, ProviderDB
        from metatv.core.discovery_engine import get_by_genre

        db = Database(f"sqlite:///{tmp_path / 'multi.db'}")
        db.create_tables()
        session = db.get_session()
        try:
            session.add(ProviderDB(
                id="p1", name="P", type="xtream",
                url="http://x.example.com", is_active=True,
            ))
            session.add(ChannelDB(
                id=str(uuid.uuid4()), source_id="m1", provider_id="p1",
                name="Multi Genre Movie", media_type="movie",
                raw_data={"genre": "Action & Adventure / Drama", "rating": "7.0"},
            ))
            session.commit()

            # Must appear in 'Action & Adventure' shelf
            cards_aa = get_by_genre(session, "Action & Adventure", limit=50)
            assert len(cards_aa) == 1, (
                f"Expected 1 card in 'Action & Adventure', got {len(cards_aa)}"
            )

            # Must appear in 'Drama' shelf
            cards_d = get_by_genre(session, "Drama", limit=50)
            assert len(cards_d) == 1, (
                f"Expected 1 card in 'Drama', got {len(cards_d)}"
            )

            # Must NOT appear in pure 'Action' shelf
            cards_a = get_by_genre(session, "Action", limit=50)
            assert len(cards_a) == 0, (
                f"Pure 'Action' shelf must not match 'Action & Adventure / Drama'; "
                f"got {len(cards_a)}: {[c.title for c in cards_a]}"
            )
        finally:
            session.close()
            db.close()


# ---------------------------------------------------------------------------
# normalize_genre — unit-level (no DB)
# ---------------------------------------------------------------------------

class TestNormalizeGenreUnit:
    """Unit tests for filter_utils.normalize_genre — executed code path, real assertions."""

    def test_entity_and_plain_produce_same_canonical(self):
        from metatv.core.filter_utils import normalize_genre
        pairs = [
            ("Action &amp; Adventure", "Action & Adventure"),
            ("Sci-Fi &amp; Fantasy",   "Sci-Fi & Fantasy"),
            ("War &amp; Politics",     "War & Politics"),
        ]
        for encoded, plain in pairs:
            assert normalize_genre(encoded) == normalize_genre(plain), (
                f"normalize_genre({encoded!r}) != normalize_genre({plain!r}): "
                f"{normalize_genre(encoded)!r} vs {normalize_genre(plain)!r}"
            )

    def test_pure_genres_stay_distinct_from_compounds(self):
        from metatv.core.filter_utils import normalize_genre
        # Pure forms must NOT map to the compound
        assert normalize_genre("Fantasy") == "Fantasy"
        assert normalize_genre("Fantasy") != "Sci-Fi & Fantasy"
        assert normalize_genre("Action") == "Action"
        assert normalize_genre("Action") != "Action & Adventure"
        assert normalize_genre("War") == "War"
        assert normalize_genre("War") != "War & Politics"

    def test_compound_itself_passes_through_unchanged(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("Sci-Fi & Fantasy") == "Sci-Fi & Fantasy"
        assert normalize_genre("Action & Adventure") == "Action & Adventure"
        assert normalize_genre("War & Politics") == "War & Politics"

    def test_sci_fi_alias_maps_to_pure_science_fiction(self):
        from metatv.core.filter_utils import normalize_genre
        assert normalize_genre("sci-fi") == "Science Fiction"
        assert normalize_genre("Sci-Fi") == "Science Fiction"
        # "sci-fi" must NOT map to the compound
        assert normalize_genre("sci-fi") != "Sci-Fi & Fantasy"
