"""Behavioral tests for the movie-genre backfill (recommendations fix).

Root cause: the Xtream VOD (movie) *list* raw_data is sparse — no genre — so every
movie's MetadataDB row shipped with empty ``genres``.  Recommendations score on
genres, so a genreless movie scored 0 and never surfaced.  The fix harvests genres
(plus plot/cast/director) from each movie's ``get_vod_info`` detail blob and fills
the empty metadata fields, going through the SAME single-writer enrichment path.

All provider HTTP is mocked (never a real provider); a file-backed (tmp_path)
SQLite DB is used per CLAUDE.md — real Database/Config, mock ONLY the network.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache
from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'genre_backfill.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def config_obj(tmp_path):
    from metatv.core.config import Config

    c = Config(config_dir=tmp_path / "config")
    c.tmdb_enrichment_throttle_ms = 0
    return c


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _provider(session, pid: str = "p1", *, is_active: bool = True) -> str:
    session.add(
        ProviderDB(
            id=pid, name=f"Provider {pid}", type="xtream", url="http://example.com",
            username="u", password="p", is_active=is_active,
        )
    )
    session.flush()
    return pid


def _movie_with_metadata(
    session,
    *,
    provider_id: str = "p1",
    source_id: str = "100",
    genres=None,
    media_type: str = "movie",
    is_hidden: bool = False,
    genre_enrich_state: str | None = None,
    with_metadata: bool = True,
) -> tuple[str, str | None]:
    """Create a channel (+ optional linked metadata row); return (channel_id, meta_id)."""
    meta_id = None
    if with_metadata:
        meta_id = str(uuid.uuid4())
        session.add(MetadataDB(id=meta_id, title="Title", genres=genres if genres is not None else []))
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid, source_id=source_id, provider_id=provider_id, name="A Movie",
            media_type=media_type, metadata_id=meta_id, is_hidden=is_hidden,
            genre_enrich_state=genre_enrich_state,
        )
    )
    session.flush()
    return cid, meta_id


def _fake_api(*, vod: dict, calls: list):
    """Drop-in XtreamAPI returning canned get_vod_info data keyed by source_id."""

    class _FakeAPI:
        def __init__(self, base_url, username, password):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_vod_info(self, vod_id):
            calls.append(("vod", vod_id))
            return vod.get(vod_id)

        async def get_series_info(self, series_id):
            calls.append(("series", series_id))
            return None

    return _FakeAPI


# ---------------------------------------------------------------------------
# 1. Repository: apply_metadata_harvest (fill-only-empty + marker)
# ---------------------------------------------------------------------------


def test_harvest_fills_empty_genres_and_marks_fetched(db):
    with db.session_scope() as session:
        _provider(session)
        cid, meta_id = _movie_with_metadata(session, genres=[])

    harvest = {cid: {"genres": ["Action", "Thriller"], "plot": "Boom.",
                     "cast": [{"name": "X", "character": None, "photo_url": None}],
                     "director": "Y"}}
    with db.session_scope() as session:
        filled = RepositoryFactory(session).channels.apply_metadata_harvest(harvest)
    assert filled == 1

    with db.session_scope(commit=False) as session:
        meta = session.query(MetadataDB).filter_by(id=meta_id).one()
        assert meta.genres == ["Action", "Thriller"]
        assert meta.plot == "Boom."
        assert meta.director == "Y"
        state = session.query(ChannelDB.genre_enrich_state).filter_by(id=cid).scalar()
        assert state == "fetched"


def test_harvest_never_overwrites_existing_genres(db):
    with db.session_scope() as session:
        _provider(session)
        cid, meta_id = _movie_with_metadata(session, genres=["Documentary"])

    with db.session_scope() as session:
        filled = RepositoryFactory(session).channels.apply_metadata_harvest(
            {cid: {"genres": ["Action"], "plot": None, "cast": [], "director": None}}
        )
    assert filled == 0  # already had genres → untouched

    with db.session_scope(commit=False) as session:
        assert session.query(MetadataDB).filter_by(id=meta_id).one().genres == ["Documentary"]
        # attempted + genre present in blob → 'fetched' (never re-fetched)
        assert session.query(ChannelDB.genre_enrich_state).filter_by(id=cid).scalar() == "fetched"


def test_harvest_empty_blob_marks_none(db):
    with db.session_scope() as session:
        _provider(session)
        cid, meta_id = _movie_with_metadata(session, genres=[])

    with db.session_scope() as session:
        RepositoryFactory(session).channels.apply_metadata_harvest(
            {cid: {"genres": [], "plot": None, "cast": [], "director": None}}
        )
    with db.session_scope(commit=False) as session:
        assert session.query(MetadataDB).filter_by(id=meta_id).one().genres == []
        assert session.query(ChannelDB.genre_enrich_state).filter_by(id=cid).scalar() == "none"


# ---------------------------------------------------------------------------
# 2. Repository: select_genre_backfill_candidates predicate
# ---------------------------------------------------------------------------


def test_candidate_predicate_only_genreless_movies_with_metadata(db):
    with db.session_scope() as session:
        _provider(session, "p1", is_active=True)
        _provider(session, "p2", is_active=False)  # hidden (inactive)
        want, _ = _movie_with_metadata(session, source_id="1", genres=[])
        has_genres, _ = _movie_with_metadata(session, source_id="2", genres=["Drama"])
        series, _ = _movie_with_metadata(session, source_id="3", genres=[], media_type="series")
        no_meta, _ = _movie_with_metadata(session, source_id="4", with_metadata=False)
        hidden, _ = _movie_with_metadata(session, source_id="5", genres=[], is_hidden=True)
        attempted, _ = _movie_with_metadata(session, source_id="6", genres=[],
                                            genre_enrich_state="none")
        p2movie, _ = _movie_with_metadata(session, provider_id="p2", source_id="7", genres=[])

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        rows = repos.channels.select_genre_backfill_candidates(100, excluded)

    assert {r["id"] for r in rows} == {want}
    assert all(set(r) == {"id", "provider_id", "source_id", "media_type"} for r in rows)


# ---------------------------------------------------------------------------
# 3. End-to-end: backfill fills genres AND makes the movie recommendable
# ---------------------------------------------------------------------------


def test_backfill_makes_genreless_movie_recommendable(db, config_obj, monkeypatch, qapp):
    from metatv.core.preference_engine import AttributeWeights, score_candidates

    with db.session_scope() as session:
        _provider(session)
        cid, meta_id = _movie_with_metadata(session, source_id="777", genres=[])

    # Weights that favour "Action" — but the movie has no genres yet, so it scores 0.
    weights = AttributeWeights(genres={"Action": 5.0}, rated_count=1, liked_count=1)

    with db.session_scope(commit=False) as session:
        before = score_candidates(session, weights, limit=30)
    assert cid not in {sc.channel_id for sc in before}, "genreless movie must not surface"

    calls: list = []
    monkeypatch.setattr(
        "metatv.providers.xtream.XtreamAPI",
        _fake_api(vod={"777": {"info": {"genre": "Action / Adventure", "plot": "Kaboom",
                                        "cast": "Lead Actor", "director": "Some Director"}}},
                  calls=calls),
    )

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        attempted = mgr._process_genre_backfill_batch(remaining=100)
    finally:
        mgr.shutdown()

    assert ("vod", "777") in calls
    assert attempted == 1

    with db.session_scope(commit=False) as session:
        meta = session.query(MetadataDB).filter_by(id=meta_id).one()
        assert meta.genres == ["Action", "Adventure"]
        assert meta.plot == "Kaboom"
        assert session.query(ChannelDB.genre_enrich_state).filter_by(id=cid).scalar() == "fetched"

    # Now the movie matches the "Action" weight → it surfaces in recommendations.
    with db.session_scope(commit=False) as session:
        after = score_candidates(session, weights, limit=30)
    assert cid in {sc.channel_id for sc in after}, "movie must surface once genres are filled"


def test_backfill_second_pass_is_idempotent_noop(db, config_obj, monkeypatch, qapp):
    """After a full pass, re-running makes no further provider calls (marker set)."""
    with db.session_scope() as session:
        _provider(session)
        _movie_with_metadata(session, source_id="900", genres=[])

    calls: list = []
    monkeypatch.setattr(
        "metatv.providers.xtream.XtreamAPI",
        _fake_api(vod={"900": {"info": {"genre": "Comedy"}}}, calls=calls),
    )

    mgr = TmdbEnrichmentManager(db, config_obj)
    try:
        assert mgr._process_genre_backfill_batch(remaining=100) == 1
        assert calls == [("vod", "900")]
        calls.clear()
        # No candidates remain (marker 'fetched' + genres now non-empty) → 0, no calls.
        assert mgr._process_genre_backfill_batch(remaining=100) == 0
        assert calls == []
    finally:
        mgr.shutdown()
