"""Characterization tests for JSONEncoded TypeDecorator (B3-3).

Pins the contract: assign plain Python objects, read back identical objects.
TypeDecorator handles serialization transparently — no json.dumps/loads in app code.
"""

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_meta(db_session, MetadataDB, **kwargs):
    defaults = {"id": "test-1", "title": "Test Title"}
    defaults.update(kwargs)
    m = MetadataDB(**defaults)
    db_session.add(m)
    db_session.commit()
    db_session.expire(m)
    return m


# ---------------------------------------------------------------------------
# cast column
# ---------------------------------------------------------------------------

def test_cast_list_round_trips(db_session):
    """Writing a Python list to cast and reading it back must produce the same list."""
    from metatv.core.database import MetadataDB
    cast = [{"name": "Alice", "character": "Hero"}, {"name": "Bob", "character": None}]
    _make_meta(db_session, MetadataDB, cast=cast)
    result = db_session.query(MetadataDB).filter_by(id="test-1").first().cast
    assert result == cast


def test_cast_none_round_trips(db_session):
    """None cast must read back as None (not empty list)."""
    from metatv.core.database import MetadataDB
    _make_meta(db_session, MetadataDB, cast=None)
    result = db_session.query(MetadataDB).filter_by(id="test-1").first().cast
    assert result is None


def test_cast_empty_list_round_trips(db_session):
    """Empty cast list must read back as empty list."""
    from metatv.core.database import MetadataDB
    _make_meta(db_session, MetadataDB, cast=[])
    result = db_session.query(MetadataDB).filter_by(id="test-1").first().cast
    assert result == []


# ---------------------------------------------------------------------------
# genres column
# ---------------------------------------------------------------------------

def test_genres_list_round_trips(db_session):
    """genres list must survive a DB round-trip."""
    from metatv.core.database import MetadataDB
    genres = ["Drama", "Thriller", "Mystery"]
    _make_meta(db_session, MetadataDB, genres=genres)
    result = db_session.query(MetadataDB).filter_by(id="test-1").first().genres
    assert result == genres


# ---------------------------------------------------------------------------
# ProviderDB.urls column
# ---------------------------------------------------------------------------

def test_provider_urls_list_round_trips(db_session):
    """ProviderDB.urls list of dicts must survive a DB round-trip."""
    from metatv.core.database import ProviderDB
    urls = [{"url": "http://provider.test", "count": 0}]
    p = ProviderDB(
        id="prov-1", name="Test", type="xtream",
        url="http://provider.test",
        urls=urls,
    )
    db_session.add(p)
    db_session.commit()
    db_session.expire(p)
    result = db_session.query(ProviderDB).filter_by(id="prov-1").first().urls
    assert result == urls
