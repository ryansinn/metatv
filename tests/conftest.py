"""Shared fixtures for MetaTV tests."""

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB
from metatv.core.repositories.channel import ChannelRepository


@pytest.fixture(autouse=True)
def _isolate_user_config(tmp_path_factory, monkeypatch):
    """Redirect every ``Path.home()``-derived location to a throwaway tmp home.

    ``Config.config_dir`` / ``data_dir`` / ``cache_dir`` default to
    ``Path.home()/…`` and ``Config.load()``/``save()`` hardcode the same paths.
    Without this guard, any test that builds a default ``Config()`` and saves
    (e.g. the On-Now header-state test, ``test_epg_on_now_display``) silently
    overwrites the developer's **real** ``~/.config/metatv/config.yaml`` — wiping
    Global Exclusions, the What's-New cursor, and the migration version fields.
    The running app then re-runs migrations, re-shows old What's New, and loses
    curation. Patching ``Path.home`` makes touching the real config structurally
    impossible for every test (autouse), without each test having to remember to
    pass ``config_dir=tmp_path``.
    """
    fake_home = tmp_path_factory.mktemp("home")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))
    yield


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session — isolated per test."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(scope="function")
def repo(db_session):
    return ChannelRepository(db_session)


_counter = 0


def make_channel(
    session,
    name: str,
    detected_prefix: str | None = None,
    detected_quality: str | None = None,
    detected_region: str | None = None,
    media_type: str = "live",
    is_hidden: bool = False,
    provider_id: str = "test",
    **kwargs,
) -> ChannelDB:
    """Insert a minimal ChannelDB row and return it."""
    global _counter
    _counter += 1
    ch = ChannelDB(
        id=str(uuid.uuid4()),
        source_id=str(_counter),
        provider_id=provider_id,
        name=name,
        detected_prefix=detected_prefix,
        detected_quality=detected_quality,
        detected_region=detected_region,
        media_type=media_type,
        is_hidden=is_hidden,
        **kwargs,
    )
    session.add(ch)
    session.flush()
    return ch
