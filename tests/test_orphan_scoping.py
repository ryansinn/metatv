"""Behavioral tests for orphan-channel scoping via get_hidden_provider_ids().

When a provider is deleted its channels remain in the DB with a provider_id that
no longer exists in the providers table (orphans).  These tests confirm that
get_hidden_provider_ids() includes those orphaned provider_ids so every
forward-looking view (channel list, Discover, recommendations) excludes them
automatically via the existing excluded_provider_ids call-sites.

All tests use a file-backed DB (tmp_path) — not :memory: — per project policy
(pooled :memory: connections each start with an empty schema).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB, ChannelDB
from metatv.core.repositories.channel import ChannelRepository
from metatv.core.repositories.provider import ProviderRepository


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def file_db(tmp_path):
    """File-backed SQLite Database with tables created, yields (db, session)."""
    db_path = tmp_path / "test_orphan.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    session = db.get_session()
    yield db, session
    session.close()
    db.close()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _add_provider(session, pid: str, *, is_active: bool = True, exp=None) -> None:
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://example.com",
        username="u", password="p", is_active=is_active, account_exp_date=exp,
    ))
    session.flush()


def _add_channel(session, cid: str, provider_id: str, name: str = "") -> ChannelDB:
    ch = ChannelDB(
        id=cid,
        source_id=cid,
        provider_id=provider_id,
        name=name or cid,
        media_type="live",
    )
    session.add(ch)
    session.flush()
    return ch


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_orphan_detected(file_db):
    """Channels whose provider_id has no matching providers row appear in hidden set."""
    db, session = file_db

    # Two real, active providers with channels
    _add_provider(session, "p-active-1")
    _add_provider(session, "p-active-2")
    _add_channel(session, "ch-1", "p-active-1", "Channel One")
    _add_channel(session, "ch-2", "p-active-2", "Channel Two")

    # Orphaned channels: provider_id "p-deleted" has NO matching providers row
    _add_channel(session, "ch-orphan-1", "p-deleted", "Orphan One")
    _add_channel(session, "ch-orphan-2", "p-deleted", "Orphan Two")
    session.commit()

    hidden = set(ProviderRepository(session).get_hidden_provider_ids())

    assert "p-deleted" in hidden, "orphaned provider_id must be in the hidden set"
    assert "p-active-1" not in hidden, "active provider must NOT be hidden"
    assert "p-active-2" not in hidden, "active provider must NOT be hidden"


def test_combined_set_inactive_expired_orphan(file_db):
    """Hidden set is exactly {inactive, expired, orphan} with no extras."""
    db, session = file_db
    now = datetime.now()

    _add_provider(session, "p-active", is_active=True, exp=now + timedelta(days=30))
    _add_provider(session, "p-inactive", is_active=False, exp=now + timedelta(days=30))
    _add_provider(session, "p-expired", is_active=True, exp=now - timedelta(days=1))

    # Give each provider a channel so the DB is realistic
    _add_channel(session, "ch-active", "p-active")
    _add_channel(session, "ch-inactive", "p-inactive")
    _add_channel(session, "ch-expired", "p-expired")

    # Orphan: provider row deleted, channels remain
    _add_channel(session, "ch-orphan", "p-orphan")
    session.commit()

    hidden = set(ProviderRepository(session).get_hidden_provider_ids())

    assert hidden == {"p-inactive", "p-expired", "p-orphan"}, (
        f"expected exactly {{p-inactive, p-expired, p-orphan}}, got {hidden}"
    )


def test_end_to_end_get_all_excludes_orphan(file_db):
    """ChannelRepository.get_all(excluded_provider_ids=...) does not return orphaned channels."""
    db, session = file_db

    _add_provider(session, "p-real")
    _add_channel(session, "ch-real", "p-real", "Real Channel")
    _add_channel(session, "ch-orphan", "p-gone", "Orphan Channel")
    session.commit()

    hidden = ProviderRepository(session).get_hidden_provider_ids()
    results = ChannelRepository(session).get_all(
        excluded_provider_ids=hidden,
        include_hidden=True,  # don't let is_hidden=False default mask anything
    )

    names = {ch.name for ch in results}
    assert "Real Channel" in names, "active-provider channel must be returned"
    assert "Orphan Channel" not in names, "orphaned channel must be excluded via scoping"


def test_no_false_positives_without_orphans(file_db):
    """When no orphans exist, get_hidden_provider_ids() == inactive ∪ expired (unchanged behaviour)."""
    db, session = file_db
    now = datetime.now()

    _add_provider(session, "p-ok", is_active=True, exp=now + timedelta(days=10))
    _add_provider(session, "p-off", is_active=False)
    _add_provider(session, "p-lapsed", is_active=True, exp=now - timedelta(days=1))

    # All channels have matching provider rows — no orphans
    _add_channel(session, "ch-ok", "p-ok")
    _add_channel(session, "ch-off", "p-off")
    _add_channel(session, "ch-lapsed", "p-lapsed")
    session.commit()

    repo = ProviderRepository(session)
    hidden = set(repo.get_hidden_provider_ids())
    expected = set(repo.get_inactive_provider_ids()) | set(repo.get_expired_provider_ids())

    assert hidden == expected, (
        f"without orphans the set must equal inactive ∪ expired; "
        f"got hidden={hidden}, expected={expected}"
    )
    assert "p-ok" not in hidden
