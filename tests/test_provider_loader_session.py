"""Regression test for P0-1: session leak in SeriesLoadThread.

Asserts that db.get_session().close() is called after storing series data,
whether an exception occurs or not. Fails if the session is never closed
(i.e. the buggy `with session:` pattern leaks on error paths).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, Database, SeasonDB, EpisodeDB
from metatv.core.provider_loader import SeriesLoadThread
from metatv.core.models import Provider


_MINIMAL_SERIES_DATA = {
    "seasons": [
        {"season_number": 1, "name": "Season 1", "cover": "", "episodes": 2},
    ],
    "episodes": {
        "1": [
            {
                "id": "ep001",
                "episode_num": 1,
                "season": 1,
                "title": "Pilot",
                "container_extension": "mp4",
                "info": {"duration": "45:00", "movie_image": ""},
            },
            {
                "id": "ep002",
                "episode_num": 2,
                "season": 1,
                "title": "Episode 2",
                "container_extension": "mp4",
                "info": {"duration": "44:00", "movie_image": ""},
            },
        ]
    },
}


@pytest.fixture()
def mem_db():
    """In-memory SQLite Database instance with all tables created."""
    db = Database("sqlite:///:memory:")
    db.create_tables()
    yield db
    db.close()


@pytest.fixture()
def fake_provider():
    p = Provider.__new__(Provider)
    p.id = "prov1"
    p.name = "Test"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "user"
    p.password = "pass"
    return p


def _make_thread(fake_provider, mem_db):
    return SeriesLoadThread(
        provider=fake_provider,
        series_id="series123",
        series_name="Test Show",
        db=mem_db,
    )


def test_close_called_after_store(mem_db, fake_provider):
    """close() must be called on the session after successful series storage."""
    close_calls: list[str] = []
    original_get_session = mem_db.get_session

    def spy_get_session():
        session = original_get_session()
        original_close = session.close
        def recording_close():
            close_calls.append("close")
            original_close()
        session.close = recording_close
        return session

    mem_db.get_session = spy_get_session

    fake_plugin = MagicMock()
    fake_plugin.fetch_series_info = AsyncMock(return_value=_MINIMAL_SERIES_DATA)

    thread = _make_thread(fake_provider, mem_db)
    with patch("metatv.core.provider_loader.get_provider", return_value=fake_plugin):
        asyncio.run(thread.load_series())

    assert close_calls == ["close"], "session.close() must be called exactly once"


def test_seasons_and_episodes_stored(mem_db, fake_provider):
    """Seasons and episodes must persist to DB after a successful load."""
    fake_plugin = MagicMock()
    fake_plugin.fetch_series_info = AsyncMock(return_value=_MINIMAL_SERIES_DATA)

    thread = _make_thread(fake_provider, mem_db)
    with patch("metatv.core.provider_loader.get_provider", return_value=fake_plugin):
        asyncio.run(thread.load_series())

    session = mem_db.get_session()
    try:
        seasons = session.query(SeasonDB).all()
        episodes = session.query(EpisodeDB).all()
        assert len(seasons) == 1
        assert len(episodes) == 2
    finally:
        session.close()


def test_close_called_after_api_error(mem_db, fake_provider):
    """close() must not be skipped when an exception occurs mid-store.

    This specifically guards against the `with session:` pattern that may skip
    close() on early-return paths in some SQLAlchemy versions.
    """
    close_calls: list[str] = []
    original_get_session = mem_db.get_session

    def spy_get_session():
        session = original_get_session()
        original_close = session.close
        def recording_close():
            close_calls.append("close")
            original_close()
        session.close = recording_close
        return session

    mem_db.get_session = spy_get_session

    # Return malformed data that triggers the isinstance guard
    bad_data = {"seasons": [], "episodes": "not-a-dict-or-list"}
    fake_plugin = MagicMock()
    fake_plugin.fetch_series_info = AsyncMock(return_value=bad_data)

    thread = _make_thread(fake_provider, mem_db)
    with patch("metatv.core.provider_loader.get_provider", return_value=fake_plugin):
        asyncio.run(thread.load_series())

    assert close_calls == ["close"], "session.close() must be called even on error paths"
