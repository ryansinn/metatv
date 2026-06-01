"""Shared fixtures for MetaTV tests."""

import uuid
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, ChannelDB
from metatv.core.repositories.channel import ChannelRepository


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
