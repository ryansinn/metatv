"""Behavior tests for the EPG-active provider scoping chokepoint.

`ProviderRepository.get_epg_active_provider_ids()` is the include-list counterpart
of `get_hidden_provider_ids()` for EPG/watchlist queries. These execute the real
query path against a file-backed DB (not :memory:, whose pooled connections each
get an empty schema).
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from metatv.core.database import Database, ProviderDB, EpgProgramDB
from metatv.core.repositories.provider import ProviderRepository
from metatv.core.repositories.epg import EpgRepository
from metatv.core.epg_utils import now_utc


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

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


def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php", exp=None):
    """Seed a ProviderDB row; exp=datetime in the past → expired subscription."""
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=is_active,
        epg_url=epg_url, account_exp_date=exp,
    ))
    session.flush()


def _add_programme(session, provider_id, title, channel_db_id, *,
                   minutes_ago: int = 5, duration_minutes: int = 60):
    """Seed an EpgProgramDB row that is currently airing (start in past, stop in future)."""
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{provider_id}",
        channel_db_id=channel_db_id,
        title=title,
        start_time=now - timedelta(minutes=minutes_ago),
        stop_time=now + timedelta(minutes=duration_minutes - minutes_ago),
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Helper: get_epg_active_provider_ids
# ---------------------------------------------------------------------------

def test_epg_active_returns_only_active_with_epg_url(session):
    """Only a provider that is active, non-expired, and has an epg_url is returned."""
    now = datetime.now()
    _add_provider(session, "a-active-epg",    is_active=True,  epg_url="http://e/xmltv")
    _add_provider(session, "b-inactive-epg",  is_active=False, epg_url="http://e/xmltv")
    _add_provider(session, "c-expired-epg",   is_active=True,  epg_url="http://e/xmltv",
                  exp=now - timedelta(days=1))
    _add_provider(session, "d-active-no-epg", is_active=True,  epg_url="")

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert result == ["a-active-epg"], (
        f"Expected only the active+epg provider; got {result}"
    )


def test_epg_active_empty_when_no_qualifying_providers(session):
    now = datetime.now()
    _add_provider(session, "inactive", is_active=False, epg_url="http://e/xmltv")
    _add_provider(session, "expired",  is_active=True,  epg_url="http://e/xmltv",
                  exp=now - timedelta(days=5))

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert result == []


def test_epg_active_excludes_expired_but_not_inactive_expiring_later(session):
    """An active provider whose subscription hasn't expired yet must be included."""
    now = datetime.now()
    _add_provider(session, "future-exp", is_active=True, epg_url="http://e/xmltv",
                  exp=now + timedelta(days=30))

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert "future-exp" in result


# ---------------------------------------------------------------------------
# Watchlist scoping regression
# ---------------------------------------------------------------------------

def test_watchlist_live_excludes_inactive_provider_programme(session):
    """get_live_for_watchlist with provider_ids from get_epg_active_provider_ids
    must exclude a programme whose provider is inactive, even though the programme
    title matches the watchlist pattern.
    """
    now = datetime.now()
    _add_provider(session, "live-provider",     is_active=True,  epg_url="http://e/xmltv")
    _add_provider(session, "inactive-provider", is_active=False, epg_url="http://e/xmltv")

    # Both providers have a matching programme airing right now.
    _add_programme(session, "live-provider",     "Breaking Bad", "ch-live")
    _add_programme(session, "inactive-provider", "Breaking Bad", "ch-inactive")

    repo = ProviderRepository(session)
    active_ids = repo.get_epg_active_provider_ids()

    epg_repo = EpgRepository(session)
    results = epg_repo.get_live_for_watchlist(["Breaking Bad"], provider_ids=active_ids)

    matched_channel_ids = {p.channel_db_id for progs in results.values() for p in progs}
    assert "ch-live"     in matched_channel_ids, "Active-provider programme should appear"
    assert "ch-inactive" not in matched_channel_ids, "Inactive-provider programme must be excluded"


def test_watchlist_live_excludes_expired_provider_programme(session):
    """Programmes from an expired provider are excluded from watchlist live results
    when scoped by get_epg_active_provider_ids().
    """
    past = datetime.now() - timedelta(days=1)
    _add_provider(session, "good-provider",    is_active=True, epg_url="http://e/xmltv")
    _add_provider(session, "expired-provider", is_active=True, epg_url="http://e/xmltv",
                  exp=past)

    _add_programme(session, "good-provider",    "The Wire", "ch-good")
    _add_programme(session, "expired-provider", "The Wire", "ch-expired")

    active_ids = ProviderRepository(session).get_epg_active_provider_ids()
    results = EpgRepository(session).get_live_for_watchlist(["The Wire"], provider_ids=active_ids)

    matched = {p.channel_db_id for progs in results.values() for p in progs}
    assert "ch-good"    in matched,    "Good-provider programme should appear"
    assert "ch-expired" not in matched, "Expired-provider programme must be excluded"


def test_watchlist_live_without_provider_ids_is_unscoped(session):
    """Regression guard: calling without provider_ids returns programmes from all
    providers, demonstrating the prior (broken) behavior — confirms the fix matters.
    """
    now_dt = datetime.now()
    _add_provider(session, "dead-provider", is_active=False, epg_url="http://e/xmltv")
    _add_programme(session, "dead-provider", "Sopranos", "ch-dead")

    # Without provider_ids the query is unscoped and returns the dead-source result.
    results = EpgRepository(session).get_live_for_watchlist(["Sopranos"])

    matched = {p.channel_db_id for progs in results.values() for p in progs}
    assert "ch-dead" in matched, (
        "Unscoped query should return dead-source programme — "
        "confirming provider_ids= kwarg is what enforces scoping"
    )
