"""The detail-blob harvest keeps the artwork it reads.

Owner report chain, 2026-08-23: a title showing a poster in the results row
said "No poster available" in the details pane. #438 stopped the metadata cache
from writing empty fields over stored ones. A repair pass then recovered only
**10 of 70** damaged rows, and the 60 that stayed broken all had one thing in
common — ``raw_data.stream_icon: null``.

For those titles the only place a poster ever appears is the provider's
per-title ``get_vod_info`` blob. The enrichment sweep *does* call that endpoint,
once per title, for its tmdb id — and ``harvest_detail_metadata`` took
genre/plot/cast/director out of the response and **dropped the image on the
floor**. So there was no route in the tree that could put a lost poster back.

These tests cover the whole route: the parse keeps it, the shared key list is
shared, the write fills it without overwriting, and the repair seam reaches
rows the lazy sweep will not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from metatv.metadata_providers.raw_parse import (
    extract_artwork,
    first_or_none,
    harvest_detail_metadata,
)


# ---------------------------------------------------------------------------
# 1. The parse.
# ---------------------------------------------------------------------------

def test_the_harvest_keeps_the_poster():
    """THE regression. PRE-FIX the returned dict had no artwork key at all."""
    blob = {"info": {"movie_image": "http://img/poster.jpg", "genre": "Animation"}}
    assert harvest_detail_metadata(blob)["poster_url"] == "http://img/poster.jpg"


def test_the_harvest_keeps_the_backdrop():
    blob = {"info": {"backdrop_path": ["http://img/back.jpg"]}}
    assert harvest_detail_metadata(blob)["backdrop_url"] == "http://img/back.jpg"


def test_cover_wins_over_movie_image():
    """A blob carrying both puts the full poster in ``cover`` and a smaller
    list-grade image in ``movie_image``."""
    blob = {"info": {"cover": "http://img/big.jpg", "movie_image": "http://img/sm.jpg"}}
    assert harvest_detail_metadata(blob)["poster_url"] == "http://img/big.jpg"


def test_a_flat_blob_still_yields_artwork():
    """Some providers return the info fields at the top level."""
    assert harvest_detail_metadata({"movie_image": "http://img/f.jpg"})["poster_url"] == (
        "http://img/f.jpg"
    )


@pytest.mark.parametrize("blob", [None, {}, {"info": {}}, [], "nonsense"])
def test_absent_artwork_is_none_not_a_crash_or_an_empty_string(blob):
    """Callers fill-only-empty, so "" and None must not be confused — an empty
    string is falsy but would still be *written* by a naive guard."""
    harvested = harvest_detail_metadata(blob)
    assert harvested["poster_url"] is None
    assert harvested["backdrop_url"] is None


def test_the_other_harvested_fields_are_untouched():
    """Widening the harvest must not disturb what it already returned."""
    blob = {"info": {"genre": "Drama, Thriller", "plot": "A synopsis.",
                     "cast": "A Actor, B Actor", "director": "D Director"}}
    harvested = harvest_detail_metadata(blob)
    assert harvested["genres"] == ["Drama", "Thriller"]
    assert harvested["plot"] == "A synopsis."
    assert [c["name"] for c in harvested["cast"]] == ["A Actor", "B Actor"]
    assert harvested["director"] == "D Director"


@pytest.mark.parametrize("value,expected", [
    (["a", "b"], "a"), ([], None), ("a", None if False else "a"),
    ("", None), (None, None), (123, None),
])
def test_first_or_none_handles_both_shapes(value, expected):
    """Xtream returns ``backdrop_path`` as a LIST while every other image field
    is a bare string, so a caller assuming either shape is wrong half the
    time."""
    assert first_or_none(value) == expected


# ---------------------------------------------------------------------------
# 2. One key list, not two.
# ---------------------------------------------------------------------------

def test_the_provider_plugin_reads_the_same_helper():
    """``ProviderMetadataProvider`` had its own copy of the artwork keys. Two
    copies is how the sweep and the plugin come to disagree about where a
    poster lives — which is the shape of the original bug."""
    source = Path("metatv/metadata_providers/provider_metadata.py").read_text()
    assert "extract_artwork" in source
    assert "info.get('movie_image')" not in source, (
        "the plugin has grown a second copy of the artwork key list"
    )


def test_the_channel_logo_fallback_stays_with_the_channel():
    """``extract_artwork`` deliberately knows nothing about ``logo_url`` — that
    is a fact about a CHANNEL, not about a detail blob."""
    poster, _backdrop = extract_artwork({})
    assert poster is None
    source = Path("metatv/metadata_providers/provider_metadata.py").read_text()
    assert "channel.logo_url" in source, "the channel-level fallback was lost"


# ---------------------------------------------------------------------------
# 3. The write fills without overwriting.
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'harvest.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed(db, *, poster=None):
    from metatv.core.database import ChannelDB, MetadataDB
    with db.session_scope() as session:
        session.add(MetadataDB(id="m1", title="Sing", poster_url=poster))
        session.add(ChannelDB(id="c1", source_id="940984", provider_id="p1",
                              name="Sing", media_type="movie", metadata_id="m1"))


def _poster(db):
    from metatv.core.database import MetadataDB
    with db.session_scope(commit=False) as session:
        return session.query(MetadataDB).filter_by(id="m1").first().poster_url


def test_apply_metadata_harvest_fills_an_empty_poster(db):
    """PRE-FIX this did nothing: the harvest carried no poster and the writer
    had no branch for one."""
    from metatv.core.repositories import RepositoryFactory

    _seed(db, poster=None)
    with db.session_scope() as session:
        RepositoryFactory(session).channels.apply_metadata_harvest(
            {"c1": harvest_detail_metadata({"info": {"movie_image": "http://img/p.jpg"}})}
        )
    assert _poster(db) == "http://img/p.jpg"


def test_apply_metadata_harvest_never_overwrites_a_stored_poster(db):
    """Fill-only-empty, the same contract the rest of this writer honours — a
    better provider's value or a user edit is never clobbered."""
    from metatv.core.repositories import RepositoryFactory

    _seed(db, poster="http://img/original.jpg")
    with db.session_scope() as session:
        RepositoryFactory(session).channels.apply_metadata_harvest(
            {"c1": harvest_detail_metadata({"info": {"movie_image": "http://img/new.jpg"}})}
        )
    assert _poster(db) == "http://img/original.jpg"


def test_a_blob_with_no_artwork_leaves_the_row_alone(db):
    from metatv.core.repositories import RepositoryFactory

    _seed(db, poster="http://img/original.jpg")
    with db.session_scope() as session:
        RepositoryFactory(session).channels.apply_metadata_harvest(
            {"c1": harvest_detail_metadata({"info": {"genre": "Drama"}})}
        )
    assert _poster(db) == "http://img/original.jpg"


# ---------------------------------------------------------------------------
# 4. The repair seam reaches rows the lazy sweep will not.
# ---------------------------------------------------------------------------

def test_harvest_for_channels_takes_the_ids_it_is_given(db, monkeypatch):
    """``enqueue`` narrows to *candidates* — idless, unattempted rows. A row
    damaged by the cache clobber has usually already been attempted, so it is
    not a candidate and the lazy sweep would never look at it again. The repair
    seam must not apply that filter.
    """
    from metatv.core.database import ProviderDB
    from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager

    _seed(db, poster=None)
    with db.session_scope() as session:
        session.add(ProviderDB(id="p1", name="P", type="xtream", url="http://p",
                               username="u", password="w", is_active=True))

    seen: list[list[str]] = []

    async def _fake_fetch(provider, rows, concurrency, throttle):
        seen.append([r["id"] for r in rows])
        return ({}, [], {r["id"]: harvest_detail_metadata(
            {"info": {"movie_image": "http://img/repaired.jpg"}}) for r in rows}, 0)

    from types import SimpleNamespace
    manager = TmdbEnrichmentManager(db, SimpleNamespace())
    monkeypatch.setattr(manager, "_fetch_provider", _fake_fetch)
    try:
        totals = manager.harvest_for_channels(["c1"])
    finally:
        manager.shutdown()

    assert seen == [["c1"]], "the repair seam filtered out the row it was handed"
    assert totals["attempted"] == 1 and totals["fetched"] == 1
    assert _poster(db) == "http://img/repaired.jpg"


def test_harvest_for_channels_is_a_no_op_for_no_ids(db):
    from types import SimpleNamespace

    from metatv.core.tmdb_enrichment_manager import TmdbEnrichmentManager

    manager = TmdbEnrichmentManager(db, SimpleNamespace())
    try:
        assert manager.harvest_for_channels([])["attempted"] == 0
    finally:
        manager.shutdown()
