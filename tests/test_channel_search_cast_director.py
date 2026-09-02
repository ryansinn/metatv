"""Behavioral tests for text search matching metadata director/cast, not just name.

Before this fix, every text-search call site (``_apply_channel_filters``,
``ChannelRepository.search``, ``get_similar_channels``, ``get_hidden_channels``)
only matched ``ChannelDB.name.ilike(...)``. They now all route through the shared
``channel_text_search_predicate`` helper, which also matches
``MetadataDB.director``/``MetadataDB.cast`` (joined via ``ChannelDB.metadata_id``)
so a search for an actor/director finds the title even when the channel *name*
doesn't mention them.

All DB tests use file-backed (tmp_path) SQLite — not :memory: — per CLAUDE.md rule.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest


def _make_channel(session, *, name: str, provider_id: str = "p1",
                   media_type: str = "movie", metadata_id: str | None = None,
                   is_hidden: bool = False) -> str:
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    session.add(ChannelDB(
        id=cid,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        media_type=media_type,
        metadata_id=metadata_id,
        is_hidden=is_hidden,
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

    d = Database(f"sqlite:///{tmp_path / 'test_search_cast.db'}")
    d.create_tables()
    yield d
    d.close()


def test_search_matches_cast_not_name(db):
    """A movie whose name does NOT contain 'Nicole Kidman' but whose metadata
    cast does, is returned by ``ChannelRepository.search('Nicole Kidman')``.
    """
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(
            session, mid="m1", director="Baz Luhrmann",
            cast=[{"name": "Nicole Kidman", "character": "Satine"},
                  {"name": "Ewan McGregor", "character": "Christian"}],
            title="Moulin Rouge!",
        )
        cid = _make_channel(
            session, name="EN - Moulin Rouge (2001)", metadata_id="m1",
        )
        # Distractor: no metadata, name doesn't mention the actor.
        _make_channel(session, name="EN - Unrelated Movie (1999)")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.search("Nicole Kidman")
        result_ids = [r.id for r in results]

    assert cid in result_ids, (
        "Search for 'Nicole Kidman' must return the channel whose linked "
        "metadata cast contains her, even though the channel name doesn't."
    )
    assert len(results) == 1, f"Expected exactly 1 match, got {len(results)}: {result_ids}"


def test_search_matches_director_not_name(db):
    """A movie whose name does NOT contain the director's name is still found."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(session, mid="m1", director="Quentin Tarantino", cast=[])
        cid = _make_channel(session, name="EN - Pulp Fiction (1994)", metadata_id="m1")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.search("Tarantino")
        result_ids = [r.id for r in results]

    assert cid in result_ids, (
        "Search for 'Tarantino' must return the channel whose linked metadata "
        "director contains it."
    )


def test_search_still_matches_name(db):
    """The name-match branch keeps working alongside the new director/cast branch."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        cid = _make_channel(session, name="EN - Moulin Rouge (2001)")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.search("Moulin")
        result_ids = [r.id for r in results]

    assert cid in result_ids


def test_search_no_false_positive_for_unrelated_query(db):
    """A query matching neither name nor director/cast returns nothing."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(session, mid="m1", director="Baz Luhrmann",
                        cast=[{"name": "Nicole Kidman"}])
        _make_channel(session, name="EN - Moulin Rouge (2001)", metadata_id="m1")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.search("Definitely Not Present Zzzqx")

    assert results == []


def test_apply_channel_filters_search_matches_cast(db):
    """The main filter/list pushdown (get_all's search_query) also matches cast."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(session, mid="m1", cast=[{"name": "Nicole Kidman"}])
        cid = _make_channel(session, name="EN - Moulin Rouge (2001)", metadata_id="m1")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_all(search_query="Nicole Kidman")
        result_ids = [r.id for r in results]

    assert cid in result_ids, (
        "get_all(search_query=...) must route through the shared cast/director "
        "predicate too."
    )


def test_get_hidden_channels_search_matches_director(db):
    """get_hidden_channels' search_query branch also matches director."""
    from metatv.core.repositories import RepositoryFactory

    with db.session_scope() as session:
        _make_metadata(session, mid="m1", director="Baz Luhrmann")
        cid = _make_channel(
            session, name="EN - Moulin Rouge (2001)", metadata_id="m1",
            is_hidden=True,
        )

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        results = repos.channels.get_hidden_channels(search_query="Luhrmann")
        result_ids = [r.id for r in results]

    assert cid in result_ids
