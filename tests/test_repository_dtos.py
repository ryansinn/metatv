"""Tests for repository DTO methods (B7-2).

Key invariant: each DTO method returns plain data whose attributes are
accessible AFTER the SQLAlchemy session is closed — no DetachedInstanceError,
no lazy-load, no live ORM reference in the returned objects.
"""

import uuid
import pytest
from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB, SeasonDB, EpisodeDB
from metatv.core.repositories.dtos import (
    FavoriteDTO, HistoryDTO, SeasonDTO, EpisodeDTO, build_history_dtos,
)
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.season import SeasonRepository
from metatv.core.repositories.episode import EpisodeRepository
from metatv.core.repositories import RepositoryFactory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


def _make_channel(session, name="Test Channel", media_type="live",
                  source_id: str | None = None, **kwargs) -> ChannelDB:
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=source_id or str(uuid.uuid4()),
        provider_id="prov1",
        name=name,
        media_type=media_type,
        **kwargs,
    )
    session.add(ch)
    session.flush()
    return ch


def _make_season(session, series_id="s1", provider_id="prov1", season_number=1,
                 name="Season 1", episode_count=3, raw_data=None) -> SeasonDB:
    s = SeasonDB(
        id=f"{series_id}_s{season_number}",
        series_id=series_id,
        provider_id=provider_id,
        season_number=season_number,
        name=name,
        episode_count=episode_count,
        raw_data=raw_data,
    )
    session.add(s)
    session.flush()
    return s


def _make_episode(session, season_id="s1_s1", series_id="s1", provider_id="prov1",
                  episode_num=1, season_num=1, title="Episode 1",
                  stream_url="http://test/ep1.ts", is_watched=False,
                  raw_data=None) -> EpisodeDB:
    ep = EpisodeDB(
        id=str(uuid.uuid4()),
        season_id=season_id,
        series_id=series_id,
        provider_id=provider_id,
        episode_id=str(episode_num),
        episode_num=episode_num,
        season_num=season_num,
        title=title,
        stream_url=stream_url,
        is_watched=is_watched,
        raw_data=raw_data,
    )
    session.add(ep)
    session.flush()
    return ep


# ---------------------------------------------------------------------------
# FavoriteDTO tests
# ---------------------------------------------------------------------------

def test_favorite_dto_attributes_after_session_close(session):
    """FavoriteDTO attributes must be readable after the session is closed."""
    _make_channel(session, name="My Fave", media_type="movie", is_favorite=True)
    session.commit()

    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto()
    session.close()  # close BEFORE reading DTO attributes

    assert len(dtos) == 1
    dto = dtos[0]
    # All attribute access must succeed — no DetachedInstanceError
    assert dto.name == "My Fave"
    assert dto.media_type == "movie"
    assert dto.last_played is None
    assert isinstance(dto, FavoriteDTO)


def test_favorite_dto_is_frozen(session):
    """FavoriteDTO must be immutable (frozen=True)."""
    _make_channel(session, name="Frozen", is_favorite=True)
    session.commit()
    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto()
    with pytest.raises(Exception):   # FrozenInstanceError
        dtos[0].name = "changed"     # type: ignore[misc]


def test_favorite_dto_last_played_preserved(session):
    """FavoriteDTO.last_played must carry the datetime from the DB row."""
    ts = datetime(2024, 6, 1, 12, 0, 0)
    _make_channel(session, name="Watched", is_favorite=True, last_played=ts)
    session.commit()
    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto()
    session.close()
    assert dtos[0].last_played == ts


def test_favorite_dto_excludes_hidden(session):
    """Hidden channels must be excluded from get_favorites_dto()."""
    _make_channel(session, name="Hidden Fave", is_favorite=True, is_hidden=True)
    _make_channel(session, name="Visible Fave", is_favorite=True, is_hidden=False)
    session.commit()
    repo = ChannelRepository(session)
    dtos = repo.get_favorites_dto()
    assert len(dtos) == 1
    assert dtos[0].name == "Visible Fave"


# ---------------------------------------------------------------------------
# SeasonDTO tests
# ---------------------------------------------------------------------------

def test_season_dto_attributes_after_session_close(session):
    """SeasonDTO attributes must be readable after the session is closed."""
    _make_season(session, season_number=1, name="Season 1", episode_count=5)
    session.commit()

    repo = SeasonRepository(session)
    dtos = repo.get_seasons_dto(series_id="s1", provider_id="prov1")
    session.close()

    assert len(dtos) == 1
    dto = dtos[0]
    assert dto.name == "Season 1"
    assert dto.episode_count == 5
    assert dto.rating is None
    assert isinstance(dto, SeasonDTO)


def test_season_dto_rating_extracted_from_raw_data(session):
    """SeasonDTO.rating must be pre-extracted from raw_data['rating']."""
    _make_season(session, raw_data={"rating": "8.5"})
    session.commit()

    repo = SeasonRepository(session)
    dtos = repo.get_seasons_dto(series_id="s1", provider_id="prov1")
    session.close()

    assert dtos[0].rating == "8.5"


def test_season_dto_rating_none_when_absent(session):
    """SeasonDTO.rating must be None when raw_data has no rating key."""
    _make_season(session, raw_data={"other": "stuff"})
    session.commit()

    repo = SeasonRepository(session)
    dtos = repo.get_seasons_dto(series_id="s1", provider_id="prov1")
    session.close()

    assert dtos[0].rating is None


def test_season_dto_is_frozen(session):
    """SeasonDTO must be immutable."""
    _make_season(session)
    session.commit()
    repo = SeasonRepository(session)
    dtos = repo.get_seasons_dto(series_id="s1", provider_id="prov1")
    with pytest.raises(Exception):
        dtos[0].name = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EpisodeDTO tests
# ---------------------------------------------------------------------------

def test_episode_dto_attributes_after_session_close(session):
    """EpisodeDTO attributes must be readable after the session is closed."""
    _make_episode(session, episode_num=3, season_num=1, title="The Pilot",
                  stream_url="http://test/s01e03.ts", is_watched=True)
    session.commit()

    repo = EpisodeRepository(session)
    dtos = repo.get_episodes_dto_by_season(season_id="s1_s1")
    session.close()

    assert len(dtos) == 1
    dto = dtos[0]
    assert dto.episode_num == 3
    assert dto.season_num == 1
    assert dto.title == "The Pilot"
    assert dto.stream_url == "http://test/s01e03.ts"
    assert dto.is_watched is True
    assert isinstance(dto, EpisodeDTO)


def test_episode_dto_rating_extracted_from_raw_data(session):
    """EpisodeDTO.rating must be pre-extracted from raw_data['info']['rating']."""
    _make_episode(session, raw_data={"info": {"rating": "9.1"}})
    session.commit()

    repo = EpisodeRepository(session)
    dtos = repo.get_episodes_dto_by_season(season_id="s1_s1")
    session.close()

    assert dtos[0].rating == "9.1"


def test_episode_dto_rating_none_when_absent(session):
    """EpisodeDTO.rating must be None when raw_data has no info.rating."""
    _make_episode(session, raw_data={"info": {}})
    session.commit()

    repo = EpisodeRepository(session)
    dtos = repo.get_episodes_dto_by_season(season_id="s1_s1")
    session.close()

    assert dtos[0].rating is None


def test_episode_dto_is_frozen(session):
    """EpisodeDTO must be immutable."""
    _make_episode(session)
    session.commit()
    repo = EpisodeRepository(session)
    dtos = repo.get_episodes_dto_by_season(season_id="s1_s1")
    with pytest.raises(Exception):
        dtos[0].title = "changed"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# build_history_dtos tests
# ---------------------------------------------------------------------------

def test_history_dto_attributes_after_session_close(session):
    """HistoryDTO attributes must be readable after the session is closed."""
    ts = datetime(2024, 5, 10, 8, 0, 0)
    _make_channel(session, name="Action Movie", media_type="movie", last_played=ts)
    session.commit()

    repos = RepositoryFactory(session)
    dtos = build_history_dtos(repos, limit=10)
    session.close()

    assert len(dtos) == 1
    dto = dtos[0]
    assert dto.name == "Action Movie"
    assert dto.media_type == "movie"
    assert dto.episode_code is None
    assert isinstance(dto, HistoryDTO)


def test_history_dto_episode_code_populated_for_series(session):
    """HistoryDTO.episode_code must be 'SxxExx' for series with a played episode."""
    from metatv.core.models import MediaType

    ch = _make_channel(session, name="My Show", media_type=MediaType.SERIES,
                       source_id="series_src_1", last_played=datetime.now())
    session.commit()

    # Add a played episode
    ep = _make_episode(
        session, season_id="series_src_1_s2", series_id="series_src_1",
        provider_id="prov1", episode_num=5, season_num=2, title="Ep 5",
    )
    ep.last_played = datetime.now()
    session.commit()

    repos = RepositoryFactory(session)
    dtos = build_history_dtos(repos, limit=10)
    session.close()

    series_dto = next(d for d in dtos if d.name == "My Show")
    assert series_dto.episode_code == "S02E05"


def test_history_dto_episode_code_none_when_no_episode_played(session):
    """HistoryDTO.episode_code must be None for series with no played episode."""
    from metatv.core.models import MediaType

    _make_channel(session, name="Unwatched Series", media_type=MediaType.SERIES,
                  source_id="series_src_2", last_played=datetime.now())
    session.commit()

    repos = RepositoryFactory(session)
    dtos = build_history_dtos(repos, limit=10)
    session.close()

    dto = next(d for d in dtos if d.name == "Unwatched Series")
    assert dto.episode_code is None
