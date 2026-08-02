"""Behavioral tests: details-pane Cast/Crew and Genre context chips must match
what the details pane actually displays (enriched ``MetadataDB``/``detected_genres``),
not just the raw provider blob.

Bug: the strict ``person_filter`` (Cast/Crew chip) matched only
``json_extract(raw_data, '$.cast')``/``'$.director'`` — the raw provider feed.
The details pane displays the ENRICHED ``MetadataDB.cast``/``director``. A movie
whose raw feed carries no cast field, but whose linked ``MetadataDB`` row does
(the verified "Rocky" shape — provider list rows for movies are frequently
cast-sparse, enrichment fills it in via ``get_vod_info``), was invisible to its
own chip: clicking "Cast/Crew: Carl Weathers" from a movie's own details pane
returned only series (whose raw feed happens to carry cast), never the movie.

Fix: ``person_filter`` now matches the enriched store first (a correlated EXISTS
against ``MetadataDB.cast``/``director``, shared with the free-text search
predicate via ``_metadata_person_exists``), OR the existing raw_data conditions
(kept for un-enriched rows, which are still the majority).

Sibling audit: ``strict_genre_filter`` (details-pane Genre chip) had the same
raw_data-only disease. It's now aligned with ``ChannelDB.detected_genres`` — the
ingestion-computed canonical genre list — via the same exact-match ``json_each``
pattern ``discovery_engine.get_by_genre`` already uses, with a raw_data.genre LIKE
fallback for rows ingested before ``detected_genres`` existed.

All DB tests use file-backed (tmp_path) SQLite — not :memory: — per CLAUDE.md rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


def _make_channel(session, *, name: str, provider_id: str = "p1",
                   media_type: str = "movie", metadata_id: str | None = None,
                   raw_data: dict | None = None,
                   detected_genres: list | None = None) -> str:
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        metadata_id=metadata_id,
        raw_data=raw_data,
        detected_genres=detected_genres,
    ))
    return cid


def _make_metadata(session, *, mid: str, director: str | None = None,
                    cast: list | None = None, title: str = "Some Title"):
    from metatv.core.database import MetadataDB

    session.add(MetadataDB(
        id=mid,
        title=title,
        director=director,
        cast=cast,
    ))


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database

    d = Database(f"sqlite:///{tmp_path / 'test_context_chip.db'}")
    d.create_tables()
    yield d
    d.close()


def test_person_chip_matches_movie_with_enriched_only_cast(db):
    """The verified "Rocky" repro shape: a MOVIE whose raw provider feed has NO
    cast field, but whose linked MetadataDB row has 'Carl Weathers' in cast, must
    be returned by the Cast/Crew chip (person_filter). Before the fix, this row
    was invisible — only raw-data-cast rows (which skew series) ever matched.
    """
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(
            session, mid="m-rocky", title="Rocky",
            cast=[{"name": "Sylvester Stallone"}, {"name": "Carl Weathers"}],
        )
        rocky_id = _make_channel(
            session, name="EN - Rocky (1976)", media_type="movie",
            metadata_id="m-rocky", raw_data={"plot": "A boxer's story"},
        )
        # Distractor: unrelated movie, no metadata, no cast anywhere.
        _make_channel(session, name="EN - Unrelated Movie (1999)", media_type="movie")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_all(person_filter="Carl Weathers")
        result_ids = {r.id for r in results}
        media_types = {r.media_type for r in results}

    assert rocky_id in result_ids, (
        "person_filter must match MetadataDB.cast (the enriched store the "
        "details pane actually displays), not just raw_data.cast."
    )
    assert "movie" in media_types, (
        "Regression guard for the reported bug: the chip must be able to "
        "return movies, not only series."
    )


def test_person_chip_still_matches_raw_only_cast(db):
    """A SERIES whose cast lives only in raw_data (no metadata_id at all) still
    matches — the raw fallback must keep working for un-enriched rows, which
    remain the majority of the catalog.
    """
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        series_id = _make_channel(
            session, name="EN - Forrest Gump Series", media_type="series",
            raw_data={"cast": "Tom Hanks, Robin Wright", "director": "Robert Zemeckis"},
        )

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_all(person_filter="Tom Hanks")
        result_ids = {r.id for r in results}

    assert series_id in result_ids, (
        "The raw_data.cast fallback must still work for channels with no "
        "linked MetadataDB row."
    )


def test_genre_chip_matches_via_detected_genres(db):
    """A movie whose raw_data.genre does NOT literally contain 'Drama' (it was
    canonicalised from a differently-worded/aliased provider string into the
    stored ``detected_genres`` at ingestion) is still returned by the Genre
    chip (strict_genre_filter), because the chip now reads detected_genres —
    the same ingestion-computed field discovery_engine.get_by_genre reads —
    instead of re-deriving from the raw blob.
    """
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        movie_id = _make_channel(
            session, name="EN - The Shawshank Redemption (1994)", media_type="movie",
            raw_data={"genre": "Drame"},  # raw provider string, NOT literally "Drama"
            detected_genres=["Drama"],     # ingestion-canonicalised
        )
        # Distractor: different genre entirely.
        _make_channel(
            session, name="EN - Some Comedy (2001)", media_type="movie",
            raw_data={"genre": "Comedy"}, detected_genres=["Comedy"],
        )

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_all(strict_genre_filter="Drama")
        result_ids = {r.id for r in results}

    assert movie_id in result_ids, (
        "strict_genre_filter must match the canonical detected_genres list, "
        "not require a literal raw_data.genre substring match."
    )
    assert len(results) == 1, f"Expected exactly 1 match, got {len(results)}: {result_ids}"


def test_genre_chip_still_matches_raw_fallback(db):
    """A movie with no detected_genres (e.g. ingested before the field existed)
    but a raw_data.genre literal substring match still returns — the fallback
    must keep working.
    """
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        movie_id = _make_channel(
            session, name="EN - Old Row Movie (1990)", media_type="movie",
            raw_data={"genre": "Action/Drama"}, detected_genres=None,
        )

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_all(strict_genre_filter="Drama")
        result_ids = {r.id for r in results}

    assert movie_id in result_ids, (
        "The raw_data.genre LIKE fallback must still work for rows with no "
        "detected_genres yet."
    )
