"""Behavior tests for EPG staleness surfacing.

A provider's XMLTV endpoint can serve year-old guide data (e.g. ottcst returns a
Jan-2025 snapshot). `epg_is_stale` is the single boundary; `get_stale_epg_providers`
is what the EPG view banner lists. These execute the real logic against a file DB.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.epg_utils import epg_is_stale, epg_status, now_utc
from metatv.core.repositories.provider import ProviderRepository


def test_epg_is_stale_boundary():
    now = datetime(2026, 6, 14, 12, 0, 0)
    assert epg_is_stale(datetime(2025, 2, 2), _now=now) is True       # year-old → stale
    assert epg_is_stale(now - timedelta(minutes=1), _now=now) is True
    assert epg_is_stale(now + timedelta(days=3), _now=now) is False   # future → fresh
    assert epg_is_stale(None, _now=now) is False                      # no data ≠ stale


def test_epg_status_four_states():
    now = datetime(2026, 6, 14, 12, 0, 0)
    assert epg_status(None, datetime(2027, 1, 1), _now=now) == "none"      # no url
    assert epg_status("http://e", None, _now=now) == "none"               # not fetched
    assert epg_status("http://e", now - timedelta(days=400), _now=now) == "stale"
    assert epg_status("http://e", now + timedelta(hours=5), _now=now) == "soon"
    assert epg_status("http://e", now + timedelta(days=5), _now=now) == "current"


@pytest.fixture
def session():
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmp.close()
    db = Database(f"sqlite:///{tmp.name}")
    db.create_tables()
    s = db.get_session()
    yield s
    s.close()
    db.close()
    Path(tmp.name).unlink(missing_ok=True)


def _add(session, pid, *, is_active=True, epg_url="http://e/xmltv.php", data_end=None):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active,
        epg_url=epg_url, epg_data_end=data_end,
    ))
    session.flush()


def test_get_stale_epg_providers_filters_correctly(session):
    past = now_utc() - timedelta(days=400)
    future = now_utc() + timedelta(days=3)
    _add(session, "active-stale", data_end=past)            # ← the only one expected
    _add(session, "active-current", data_end=future)
    _add(session, "inactive-stale", is_active=False, data_end=past)
    _add(session, "active-stale-no-epgurl", epg_url="", data_end=past)
    _add(session, "active-no-data", data_end=None)

    stale = ProviderRepository(session).get_stale_epg_providers()

    assert [row[0] for row in stale] == ["active-stale"]
    # The tuple carries (id, name, epg_data_end) for display.
    assert stale[0][2] == past
