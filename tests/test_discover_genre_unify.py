"""D5 — Discover genre unification: cross-language aliases collapse to one shelf.

Drame (fr) / Dramma (it) / Drama (en) must render as a single "Drama" shelf
(get_all_genres), and opening that shelf must pull in all three (get_by_genre) —
not just the English rows. _primary_genre canonicalises a card's genre. This is
the DR-0005 canonicalization pilot, reusing filter_utils.normalize_genre.
"""

from __future__ import annotations

import uuid

import pytest


@pytest.fixture()
def genre_db(tmp_path):
    from metatv.core.database import Database, ChannelDB, ProviderDB

    db = Database(f"sqlite:///{tmp_path / 'genre.db'}")
    db.create_tables()
    session = db.get_session()
    try:
        session.add(ProviderDB(
            id="p1", name="P", type="xtream",
            url="http://x.example.com", is_active=True,
        ))
        # The same genre in three languages + Comedy in two.
        for label, n in [("Drama", 4), ("Drame", 3), ("Dramma", 2),
                         ("Comedy", 1), ("Comédie", 1)]:
            for i in range(n):
                session.add(ChannelDB(
                    id=str(uuid.uuid4()), source_id=f"{label}_{i}", provider_id="p1",
                    name=f"{label} {i}", media_type="movie",
                    raw_data={"genre": label, "rating": "7.0"},
                ))
        session.commit()
    finally:
        session.close()
    yield db
    db.close()


def test_get_all_genres_collapses_language_aliases(genre_db):
    """Drama/Drame/Dramma → one 'Drama'; Comedy/Comédie → one 'Comedy'."""
    from metatv.core.discovery_engine import get_all_genres
    session = genre_db.get_session()
    try:
        genres = get_all_genres(session, min_count=1)
    finally:
        session.close()

    assert "Drama" in genres
    assert "Drame" not in genres and "Dramma" not in genres, (
        f"foreign aliases must not appear as separate shelves; got {genres}"
    )
    assert "Comedy" in genres
    assert "Comédie" not in genres


def test_get_by_genre_matches_foreign_aliases(genre_db):
    """get_by_genre('Drama') pulls Drame + Dramma rows, not just English.

    Note: a plain LIKE '%drama%' would miss 'Dramma' ('dramm', not 'drama') and
    'Drame' — proving the alias OR-match is necessary, not incidental.
    """
    from metatv.core.discovery_engine import get_by_genre
    session = genre_db.get_session()
    try:
        cards = get_by_genre(session, "Drama", limit=50)
    finally:
        session.close()

    titles = [c.title for c in cards]
    assert any(t.startswith("Drama") for t in titles), "English Drama rows missing"
    assert any(t.startswith("Drame") for t in titles), "French Drame rows must be matched"
    assert any(t.startswith("Dramma") for t in titles), "Italian Dramma rows must be matched"
    # No Comedy bleed-in.
    assert not any(t.startswith("Comed") for t in titles)
    # Every returned card's genre is the canonical label.
    assert all(c.genre == "Drama" for c in cards), (
        f"cards must report canonical genre; got {[c.genre for c in cards]}"
    )


def test_primary_genre_canonicalizes():
    """_primary_genre returns the canonical label for a raw alias (first segment)."""
    from metatv.core.discovery_engine import _primary_genre

    drame = type("Ch", (), {"raw_data": {"genre": "Drame"}})()
    assert _primary_genre(drame) == "Drama"

    # First segment of a compound string is canonicalised.
    compound = type("Ch", (), {"raw_data": {"genre": "Drame / Action"}})()
    assert _primary_genre(compound) == "Drama"

    # An unknown genre passes through unchanged.
    unknown = type("Ch", (), {"raw_data": {"genre": "Telenovela"}})()
    assert _primary_genre(unknown) == "Telenovela"


def test_pure_and_compound_genres_stay_distinct():
    """De-pollution: the app never invents a SciFi/Fantasy/Action tag the source
    didn't assert. A pure 'Fantasy' must NOT collapse into 'Sci-Fi & Fantasy'
    (that would drop a pure-Fantasy title like GoT into a SciFi bucket); the
    compound is its own source-defined category (user steer 2026-06-21).
    """
    from metatv.core.filter_utils import normalize_genre

    # Compounds are their own categories — never split, never re-tagged.
    assert normalize_genre("Sci-Fi & Fantasy") == "Sci-Fi & Fantasy"
    assert normalize_genre("Action & Adventure") == "Action & Adventure"

    # Pure forms stay pure — they do NOT fold into the compound.
    assert normalize_genre("Fantasy") == "Fantasy"
    assert normalize_genre("Science Fiction") == "Science Fiction"
    assert normalize_genre("Action") == "Action"
    assert normalize_genre("Adventure") == "Adventure"

    # Abbreviations / cross-language map to the matching PURE canonical…
    assert normalize_genre("sci-fi") == "Science Fiction"
    assert normalize_genre("fantascienza") == "Science Fiction"   # it. (pure)
    assert normalize_genre("abenteuer") == "Adventure"            # de. (pure)
    # …while a cross-language alias of the COMPOUND maps to the compound.
    assert normalize_genre("Science-Fiction & Fantastique") == "Sci-Fi & Fantasy"
