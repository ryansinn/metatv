"""Behavior tests for the canonical provider-scoping chokepoint.

`ProviderRepository.get_hidden_provider_ids()` is the single source of truth every
forward-looking view (channel list, Discover, recommendations) uses to keep content
from inactive/expired sources out. These execute the real query against a file-backed
DB and assert the union — not source-string shape checks.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.repositories.provider import ProviderRepository


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


def _add(session, pid, *, is_active=True, exp=None):
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active, account_exp_date=exp,
    ))
    session.flush()


def test_hidden_ids_union_of_inactive_and_expired(session):
    now = datetime.now()
    _add(session, "active-current", is_active=True, exp=now + timedelta(days=30))
    _add(session, "inactive", is_active=False, exp=now + timedelta(days=30))
    _add(session, "expired-but-active", is_active=True, exp=now - timedelta(days=1))
    _add(session, "inactive-and-expired", is_active=False, exp=now - timedelta(days=1))

    hidden = set(ProviderRepository(session).get_hidden_provider_ids())

    # The only one shown: active AND not expired.
    assert hidden == {"inactive", "expired-but-active", "inactive-and-expired"}
    assert "active-current" not in hidden


def test_hidden_ids_empty_when_all_active_and_current(session):
    now = datetime.now()
    _add(session, "a", is_active=True, exp=now + timedelta(days=10))
    _add(session, "b", is_active=True, exp=None)  # no expiry set → never expired

    assert ProviderRepository(session).get_hidden_provider_ids() == []


def test_inactive_ids_isolated(session):
    _add(session, "on", is_active=True)
    _add(session, "off", is_active=False)
    assert ProviderRepository(session).get_inactive_provider_ids() == ["off"]
