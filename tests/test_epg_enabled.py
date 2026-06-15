"""Behavior tests for per-provider EPG enable/disable (PR-2).

All tests execute the real changed code paths against a file-backed Database
(NOT :memory: — pooled connections each get an empty schema there). Assertions
check observable outcomes, not source-code shape.
"""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB, EpgProgramDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.provider import ProviderRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


@pytest.fixture
def session(db):
    s = db.get_session()
    yield s
    s.close()


def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php",
                  epg_enabled=True, exp=None, epg_data_end=None,
                  epg_last_fetched=None, epg_data_start=None):
    """Seed a ProviderDB row."""
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=is_active,
        epg_url=epg_url,
        epg_enabled=epg_enabled,
        account_exp_date=exp,
        epg_data_end=epg_data_end,
        epg_last_fetched=epg_last_fetched,
        epg_data_start=epg_data_start,
    ))
    session.flush()


def _add_programme(session, provider_id, *, title="Show"):
    """Seed an EpgProgramDB row currently airing."""
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id=f"ch.{provider_id}",
        channel_db_id=f"cdb.{provider_id}",
        title=title,
        start_time=now - timedelta(minutes=5),
        stop_time=now + timedelta(minutes=55),
    ))
    session.flush()


# ---------------------------------------------------------------------------
# get_epg_active_provider_ids — epg_enabled filtering
# ---------------------------------------------------------------------------

def test_epg_disabled_provider_excluded_from_active_ids(session):
    """A provider with epg_enabled=False is NOT returned by get_epg_active_provider_ids."""
    _add_provider(session, "enabled-p",  epg_enabled=True)
    _add_provider(session, "disabled-p", epg_enabled=False)

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert "enabled-p"  in result,  "enabled provider must be included"
    assert "disabled-p" not in result, "disabled provider must be excluded"


def test_epg_null_enabled_treated_as_enabled(session):
    """Legacy NULL epg_enabled rows are treated as enabled (backwards compat)."""
    # Insert a row with NULL epg_enabled by bypassing the column default
    from sqlalchemy import text as _text
    session.execute(_text(
        "INSERT INTO providers (id, name, type, url, username, password, "
        "is_active, epg_url, epg_enabled) "
        "VALUES ('null-p', 'null-p', 'xtream', 'http://e.com', 'u', 'p', "
        "1, 'http://e/xmltv.php', NULL)"
    ))
    session.flush()

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert "null-p" in result, "NULL epg_enabled must be treated as enabled"


def test_epg_disabled_provider_excluded_regardless_of_active_status(session):
    """epg_enabled=False takes effect even for an otherwise fully active provider."""
    _add_provider(session, "active-disabled-epg", is_active=True, epg_enabled=False)

    result = ProviderRepository(session).get_epg_active_provider_ids()

    assert result == [], f"Expected empty; got {result}"


# ---------------------------------------------------------------------------
# get_stale_epg_providers — epg_enabled filtering
# ---------------------------------------------------------------------------

def test_stale_epg_disabled_provider_not_surfaced(session):
    """A disabled provider with stale EPG data must NOT appear in get_stale_epg_providers."""
    past = now_utc() - timedelta(days=400)
    _add_provider(session, "stale-enabled",  epg_enabled=True,  epg_data_end=past)
    _add_provider(session, "stale-disabled", epg_enabled=False, epg_data_end=past)

    stale_ids = [r[0] for r in ProviderRepository(session).get_stale_epg_providers()]

    assert "stale-enabled"  in stale_ids,     "enabled stale provider should appear"
    assert "stale-disabled" not in stale_ids, "disabled provider must not be warned about"


def test_stale_epg_null_enabled_is_included(session):
    """A legacy NULL epg_enabled with stale data IS surfaced (treat NULL as enabled)."""
    from sqlalchemy import text as _text
    past = now_utc() - timedelta(days=400)
    past_str = past.strftime("%Y-%m-%d %H:%M:%S")
    session.execute(_text(
        f"INSERT INTO providers (id, name, type, url, username, password, "
        f"is_active, epg_url, epg_enabled, epg_data_end) "
        f"VALUES ('null-stale', 'null-stale', 'xtream', 'http://e.com', 'u', 'p', "
        f"1, 'http://e/xmltv.php', NULL, '{past_str}')"
    ))
    session.flush()

    stale_ids = [r[0] for r in ProviderRepository(session).get_stale_epg_providers()]

    assert "null-stale" in stale_ids, "NULL epg_enabled stale provider must be surfaced"


# ---------------------------------------------------------------------------
# refresh_all_if_needed — skip disabled providers
# ---------------------------------------------------------------------------

def test_refresh_all_skips_epg_disabled_provider(db):
    """refresh_all_if_needed must not queue a refresh for a provider with epg_enabled=False."""
    with db.session_scope() as session:
        # epg_enabled=False, no epg_data_end → would normally refresh (never fetched)
        session.add(ProviderDB(
            id="disabled-refresh", name="disabled-refresh", type="xtream",
            url="http://e.com", username="u", password="p",
            is_active=True,
            epg_url="http://e/xmltv.php",
            epg_enabled=False,
            epg_data_end=None,
        ))

    config = MagicMock()
    config.epg_auto_refresh = True

    manager = EpgManager(db, config, notifications=None)
    manager._start_refresh = MagicMock()  # intercept; don't actually fetch

    manager.refresh_all_if_needed()

    # The disabled provider must never have had _start_refresh called for it.
    called_ids = [call.args[0] for call in manager._start_refresh.call_args_list]
    assert "disabled-refresh" not in called_ids, (
        f"_start_refresh must not be called for epg_enabled=False provider; calls={called_ids}"
    )
    manager._executor.shutdown(wait=False)


def test_refresh_all_includes_enabled_provider(db):
    """refresh_all_if_needed must still queue a refresh for epg_enabled=True providers."""
    with db.session_scope() as session:
        session.add(ProviderDB(
            id="enabled-refresh", name="enabled-refresh", type="xtream",
            url="http://e.com", username="u", password="p",
            is_active=True,
            epg_url="http://e/xmltv.php",
            epg_enabled=True,
            epg_data_end=None,  # never fetched → needs_refresh is True
        ))

    config = MagicMock()
    config.epg_auto_refresh = True

    manager = EpgManager(db, config, notifications=None)
    manager._start_refresh = MagicMock()

    manager.refresh_all_if_needed()

    called_ids = [call.args[0] for call in manager._start_refresh.call_args_list]
    assert "enabled-refresh" in called_ids, (
        f"_start_refresh must be called for epg_enabled=True provider; calls={called_ids}"
    )
    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# purge_provider_epg — deletes programmes and nulls EPG timestamps
# ---------------------------------------------------------------------------

def test_purge_deletes_programmes_and_nulls_timestamps(db):
    """purge_provider_epg removes all EpgProgramDB rows and clears the three
    EPG timestamp columns on the provider."""
    pid = "purge-me"
    now = now_utc()

    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid, name=pid, type="xtream", url="http://e.com",
            username="u", password="p", is_active=True,
            epg_url="http://e/xmltv.php", epg_enabled=True,
            epg_last_fetched=now,
            epg_data_start=now - timedelta(hours=1),
            epg_data_end=now + timedelta(days=7),
        ))
        for i in range(5):
            session.add(EpgProgramDB(
                provider_id=pid,
                channel_epg_id=f"ch{i}",
                channel_db_id=f"cdb{i}",
                title=f"Show {i}",
                start_time=now - timedelta(minutes=5),
                stop_time=now + timedelta(minutes=55),
            ))

    config = MagicMock()
    manager = EpgManager(db, config, notifications=None)

    deleted_count = manager.purge_provider_epg(pid)

    assert deleted_count == 5, f"Expected 5 rows deleted; got {deleted_count}"

    # Verify programmes are gone and timestamps nulled.
    with db.session_scope(commit=False) as session:
        remaining = session.query(EpgProgramDB).filter_by(provider_id=pid).count()
        provider = session.query(ProviderDB).filter_by(id=pid).first()

        assert remaining == 0,                "All EpgProgramDB rows must be deleted"
        assert provider.epg_last_fetched is None, "epg_last_fetched must be NULL after purge"
        assert provider.epg_data_start   is None, "epg_data_start must be NULL after purge"
        assert provider.epg_data_end     is None, "epg_data_end must be NULL after purge"

    manager._executor.shutdown(wait=False)


def test_purge_returns_zero_when_no_programmes(db):
    """purge_provider_epg on a provider with no programmes returns 0."""
    pid = "empty-provider"

    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid, name=pid, type="xtream", url="http://e.com",
            username="u", password="p", is_active=True,
            epg_url="http://e/xmltv.php", epg_enabled=True,
        ))

    config = MagicMock()
    manager = EpgManager(db, config, notifications=None)

    count = manager.purge_provider_epg(pid)

    assert count == 0
    manager._executor.shutdown(wait=False)


def test_purge_only_deletes_target_provider_programmes(db):
    """purge_provider_epg must not delete programmes belonging to other providers."""
    now = now_utc()

    with db.session_scope() as session:
        for pid in ("purge-target", "keep-me"):
            session.add(ProviderDB(
                id=pid, name=pid, type="xtream", url="http://e.com",
                username="u", password="p", is_active=True,
                epg_url="http://e/xmltv.php", epg_enabled=True,
            ))
            session.add(EpgProgramDB(
                provider_id=pid,
                channel_epg_id="ch1",
                channel_db_id="cdb1",
                title="Show",
                start_time=now - timedelta(minutes=5),
                stop_time=now + timedelta(minutes=55),
            ))

    config = MagicMock()
    manager = EpgManager(db, config, notifications=None)
    manager.purge_provider_epg("purge-target")

    with db.session_scope(commit=False) as session:
        remaining = session.query(EpgProgramDB).filter_by(provider_id="keep-me").count()
        assert remaining == 1, "Other provider's programmes must not be deleted"

    manager._executor.shutdown(wait=False)


def test_fetch_worker_persists_timestamps_and_engages_throttle(db, monkeypatch):
    """Regression (PR-2 hotfix): the fetch worker must persist epg_last_fetched /
    epg_data_start / epg_data_end after saving programmes.

    A stale ``_now_utc()`` call crashed the worker right between the bulk-save and the
    timestamp-set (NameError), so the timestamp never persisted — and because
    ``needs_refresh`` keys off ``epg_last_fetched is None``, the EPG view re-fetched on
    every focus. This drives the real worker with a stubbed parser and asserts BOTH
    halves: the timestamps land, and the 3-day throttle then reports no refresh needed.
    """
    import metatv.core.epg_manager as epgmod
    from metatv.core.xmltv_parser import XmltvProgramme

    with db.session_scope() as session:
        _add_provider(session, "fetch-p", epg_url="http://e/xmltv.php",
                      epg_last_fetched=None, epg_data_end=None)

    now = now_utc()
    progs = [
        XmltvProgramme(channel_id="c1", title="On Now", description="",
                       start_time=now - timedelta(hours=1),
                       stop_time=now + timedelta(hours=1)),
        XmltvProgramme(channel_id="c1", title="Later", description="",
                       start_time=now + timedelta(hours=2),
                       stop_time=now + timedelta(hours=3)),
    ]
    monkeypatch.setattr(epgmod, "parse_xmltv_url", lambda *a, **k: ([], progs))

    config = MagicMock()
    config.epg_default_refresh_interval = "3d"
    manager = EpgManager(db, config, notifications=None)

    # Runs synchronously here; this raised NameError('_now_utc') before the fix.
    manager._fetch_worker("fetch-p", "http://e/xmltv.php", "Fetch P", None)

    with db.session_scope(commit=False) as session:
        prov = session.query(ProviderDB).filter_by(id="fetch-p").first()
        assert prov.epg_last_fetched is not None, "worker must persist epg_last_fetched"
        assert prov.epg_data_start is not None
        assert prov.epg_data_end is not None
        assert session.query(EpgProgramDB).filter_by(provider_id="fetch-p").count() == 2
        # Throttle now engaged: just fetched, 3d interval, guide still valid → no refetch.
        assert manager.needs_refresh(prov) is False

    manager._executor.shutdown(wait=False)
