"""A metadata refetch must never leave the user with LESS than was stored.

Owner report, 2026-08-23: a title whose poster was visibly rendering in the
results row reported "No poster available" in the details pane beside it.

Two distinct faults produced that, both on the stale-cache path:

1. ``_save_metadata_cache`` assigned every field unconditionally, so a refetch
   that returned less than the first fetch wrote ``None`` OVER good stored
   values. Silent data loss, triggered by nothing more than opening a details
   pane on a row whose cache had aged past its TTL (30 days, 90 for old
   content) — with the provider chain since returning less than it once did.
2. ``get_metadata`` discarded a stale row outright. If the refetch then came
   back empty it returned ``None``, so the pane showed nothing even though the
   database still held a complete record.

Every test here executes the real path against a real ``Database`` on a
``tmp_path`` file (never ``:memory:``) and asserts the stored/returned VALUE,
not that a function was called.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from pathlib import Path

import pytest


@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'metadata_blanking.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(session, channel_id: str, name: str, media_type: str = "movie") -> None:
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=channel_id, source_id=f"src-{channel_id}", provider_id="p1",
        name=name, media_type=media_type,
    ))


def _provider(handler, *, name="p", media_types=("movie",)):
    """A provider double whose ``get_details`` is *handler*.

    Reuses the sibling suite's factory so both files exercise the same plugin
    surface — a hand-rolled second double is how two test files end up
    disagreeing about what a provider is.
    """
    from tests.test_metadata_manager_session_hygiene import _make_provider

    return _make_provider(list(media_types), handler, name=name)


def _manager(db, *providers):
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry

    registry = MetadataProviderRegistry()
    for p in providers:
        registry.register(p)
    return MetadataManager(registry, db)


_FULL = {
    "title": "Toy Story",
    "plot": "Woody and Buzz.",
    "poster_url": "http://img/toy-story.jpg",
    "cast": ["Tom Hanks", "Tim Allen"],
    "genres": ["Animation"],
    "director": "John Lasseter",
    "runtime": 81,
    "release_date": "1995-11-22",
}


def _prime(db, mgr, channel_id, **overrides):
    """Store a complete metadata row, then age it past its TTL."""
    from metatv.core.database import ChannelDB, MetadataDB
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        channel = session.query(ChannelDB).filter_by(id=channel_id).first()
        mgr._save_metadata_cache(session, channel, MetadataResult(**{**_FULL, **overrides}))
    with db.session_scope() as session:
        channel = session.query(ChannelDB).filter_by(id=channel_id).first()
        row = session.query(MetadataDB).filter_by(id=channel.metadata_id).first()
        row.fetched_at = datetime.now() - timedelta(days=400)


def _stored(db, channel_id):
    from metatv.core.database import ChannelDB, MetadataDB

    with db.session_scope(commit=False) as session:
        channel = session.query(ChannelDB).filter_by(id=channel_id).first()
        row = session.query(MetadataDB).filter_by(id=channel.metadata_id).first()
        return {
            "title": row.title, "plot": row.plot, "poster_url": row.poster_url,
            "cast": list(row.cast or []), "genres": list(row.genres or []),
            "director": row.director, "runtime": row.runtime,
        }


# ---------------------------------------------------------------------------
# 1. A thin refetch must not erase what is stored.
# ---------------------------------------------------------------------------

def test_a_thin_refetch_does_not_blank_the_stored_poster(db):
    """THE reported bug. A provider that now returns only a title must not take
    the poster, plot and cast down with it.

    PRE-FIX: ``metadata.poster_url = result.poster_url`` ran unconditionally,
    so this stored ``None`` over ``http://img/toy-story.jpg``.
    """
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c1", "Toy Story")

    async def _thin(external_id, media_type):
        return MetadataResult(title="Toy Story", confidence=0.9)

    mgr = _manager(db, _provider(_thin))
    _prime(db, mgr, "c1")

    asyncio.run(mgr.get_metadata("c1"))

    stored = _stored(db, "c1")
    assert stored["poster_url"] == _FULL["poster_url"], "the stored poster was erased"
    assert stored["plot"] == _FULL["plot"]
    assert stored["cast"] == _FULL["cast"]
    assert stored["genres"] == _FULL["genres"]
    assert stored["director"] == _FULL["director"]
    assert stored["runtime"] == _FULL["runtime"]


def test_a_thin_refetch_returns_the_full_stored_record(db):
    """…and the details pane is handed the whole record, not just the part that
    came back this time.

    PRE-FIX: ``get_metadata`` returned its own raw provider merge, so the pane
    rendered "No poster available" beside a row still showing the poster.
    """
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c2", "Toy Story")

    async def _thin(external_id, media_type):
        return MetadataResult(title="Toy Story", confidence=0.9)

    mgr = _manager(db, _provider(_thin))
    _prime(db, mgr, "c2")

    result = asyncio.run(mgr.get_metadata("c2"))
    assert result is not None
    assert result.poster_url == _FULL["poster_url"]
    assert result.plot == _FULL["plot"]


def test_an_empty_refetch_still_shows_the_stored_record(db):
    """A provider chain that returns NOTHING is a statement about the
    providers, not about the title.

    PRE-FIX: ``get_metadata`` returned ``None`` here, so the pane showed
    nothing at all while the database held a complete record.
    """
    async def _nothing(external_id, media_type):
        return None

    with db.session_scope() as session:
        _make_channel(session, "c3", "Toy Story")

    mgr = _manager(db, _provider(_nothing))
    _prime(db, mgr, "c3")

    result = asyncio.run(mgr.get_metadata("c3"))
    assert result is not None, "a stale record was discarded when the refetch came back empty"
    assert result.poster_url == _FULL["poster_url"]
    assert _stored(db, "c3")["poster_url"] == _FULL["poster_url"]


# ---------------------------------------------------------------------------
# 2. …while a refetch that DOES know better still wins.
# ---------------------------------------------------------------------------

def test_a_richer_refetch_overwrites_the_stored_values(db):
    """The guard fills gaps; it does not freeze the record. A provider that
    returns a NEW poster must replace the old one — otherwise metadata could
    never be corrected."""
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c4", "Toy Story")

    async def _fresh(external_id, media_type):
        return MetadataResult(
            title="Toy Story", plot="A new synopsis.",
            poster_url="http://img/new.jpg", cast=["Tom Hanks"], confidence=0.9,
        )

    mgr = _manager(db, _provider(_fresh))
    _prime(db, mgr, "c4")

    result = asyncio.run(mgr.get_metadata("c4"))
    stored = _stored(db, "c4")
    assert stored["poster_url"] == "http://img/new.jpg"
    assert stored["plot"] == "A new synopsis."
    assert result.poster_url == "http://img/new.jpg"
    # …and a field the refetch said nothing about is still there.
    assert stored["director"] == _FULL["director"]


def test_zero_and_false_are_real_answers_not_absence(db):
    """``0`` is a rating, not a missing rating. The guard tests for
    ``None``/empty containers rather than plain falsiness, so a genuine zero
    still writes."""
    from metatv.core.database import MetadataDB
    from metatv.core.metadata_manager import MetadataManager

    row = MetadataDB(id="m1")
    row.rating = 8.0
    row.runtime = 100
    MetadataManager._fill_if_present(row, "rating", 0)
    MetadataManager._fill_if_present(row, "runtime", None)
    assert row.rating == 0, "a real zero was treated as absence"
    assert row.runtime == 100, "None overwrote a stored value"


def test_an_empty_list_does_not_erase_a_stored_cast(db):
    """A provider returning ``cast=[]`` is saying "I don't know", not "this
    film has no cast" — the distinction the unconditional assignment lost."""
    from metatv.core.database import MetadataDB
    from metatv.core.metadata_manager import MetadataManager

    row = MetadataDB(id="m2")
    row.cast = ["Tom Hanks"]
    MetadataManager._fill_if_present(row, "cast", [])
    assert row.cast == ["Tom Hanks"]


# ---------------------------------------------------------------------------
# 3. The fresh-cache path is untouched.
# ---------------------------------------------------------------------------

def test_a_fresh_cache_still_short_circuits_the_network(db):
    """None of the above may turn a cache hit into a fetch."""
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c5", "Toy Story")

    async def _must_not_run(external_id, media_type):
        raise AssertionError("provider ran on a FRESH cache hit")

    mgr = _manager(db, _provider(_must_not_run))
    from metatv.core.database import ChannelDB

    with db.session_scope() as session:
        channel = session.query(ChannelDB).filter_by(id="c5").first()
        mgr._save_metadata_cache(session, channel, MetadataResult(**_FULL))

    result = asyncio.run(mgr.get_metadata("c5"))
    assert result.poster_url == _FULL["poster_url"]
