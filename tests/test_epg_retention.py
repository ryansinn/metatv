"""Behavioral tests for age-based EPG hygiene — ``EpgManager.prune_expired()``.

Ground truth (docs/CRITICAL_RULES.md#epg-manager-internals + Wave 3 brief):
no age-based pruning existed before this — ``epg_programmes`` only ever grew,
since each fetch replaces one provider's rows but never reclaims programmes
that simply expired.  ``prune_expired()`` deletes rows across ALL providers
whose ``stop_time`` is older than ``Config.epg_retention_hours`` (default 24h,
floored at 6h), and runs automatically after every successful fetch inside
``_fetch_worker`` (right after the provider-timestamp commit) so a provider
that stopped refreshing still gets its stale rows swept whenever ANY other
provider fetches.

All tests execute the real changed code paths against a file-backed Database
(NOT :memory:) and assert observable DB state, not source shape.
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_manager import EpgManager, _MIN_EPG_RETENTION_HOURS
from metatv.core.epg_utils import now_utc


@pytest.fixture()
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "retention.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _add_provider(session, pid: str) -> None:
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p", is_active=True,
        epg_url="http://e/xmltv.php", epg_enabled=True,
    ))


def _add_programme(session, provider_id: str, *, stop_offset_hours: float,
                   title: str = "Show") -> None:
    now = now_utc()
    session.add(EpgProgramDB(
        provider_id=provider_id,
        channel_epg_id="ch1",
        channel_db_id=None,
        channel_name="Channel 1",
        title=title,
        description="",
        start_time=now + timedelta(hours=stop_offset_hours - 1),
        stop_time=now + timedelta(hours=stop_offset_hours),
    ))


# ---------------------------------------------------------------------------
# prune_expired() — retention window behavior
# ---------------------------------------------------------------------------

def test_prune_expired_deletes_only_rows_past_retention(db):
    """Rows whose stop_time is older than the retention window are deleted;
    rows still within the window (even if already in the past) survive."""
    with db.session_scope() as session:
        _add_provider(session, "p1")
        # Expired well past the default 24h retention.
        _add_programme(session, "p1", stop_offset_hours=-30, title="Old Show")
        # Stopped recently — inside the 24h retention window.
        _add_programme(session, "p1", stop_offset_hours=-2, title="Recent Show")
        # Still airing / upcoming.
        _add_programme(session, "p1", stop_offset_hours=5, title="Future Show")

    config = MagicMock()
    config.epg_retention_hours = 24
    manager = EpgManager(db, config, notifications=None)

    deleted = manager.prune_expired()
    assert deleted == 1

    with db.session_scope(commit=False) as session:
        titles = {p.title for p in session.query(EpgProgramDB).all()}
    assert titles == {"Recent Show", "Future Show"}, (
        f"expected only the >24h-expired row pruned, got remaining titles: {titles}"
    )

    manager._executor.shutdown(wait=False)


def test_prune_expired_respects_custom_retention_config(db):
    """A shorter configured retention window prunes more aggressively."""
    with db.session_scope() as session:
        _add_provider(session, "p1")
        _add_programme(session, "p1", stop_offset_hours=-10, title="10h ago")
        _add_programme(session, "p1", stop_offset_hours=-4, title="4h ago")

    config = MagicMock()
    config.epg_retention_hours = 6  # shorter than the 24h default
    manager = EpgManager(db, config, notifications=None)

    deleted = manager.prune_expired()
    assert deleted == 1

    with db.session_scope(commit=False) as session:
        titles = {p.title for p in session.query(EpgProgramDB).all()}
    assert titles == {"4h ago"}

    manager._executor.shutdown(wait=False)


def test_prune_expired_floors_at_minimum_retention(db):
    """A configured retention below the 6h floor is clamped — a programme that
    expired 3h ago must survive even if the config asks for a 1h retention."""
    with db.session_scope() as session:
        _add_provider(session, "p1")
        _add_programme(session, "p1", stop_offset_hours=-3, title="3h ago")

    config = MagicMock()
    config.epg_retention_hours = 1  # below _MIN_EPG_RETENTION_HOURS (6)
    manager = EpgManager(db, config, notifications=None)

    deleted = manager.prune_expired()
    assert deleted == 0, (
        "a 3h-expired row must survive under the 6h floor even though config asked "
        "for a 1h retention"
    )

    with db.session_scope(commit=False) as session:
        remaining = session.query(EpgProgramDB).count()
    assert remaining == 1

    manager._executor.shutdown(wait=False)


def test_prune_expired_sweeps_across_all_providers(db):
    """A single prune_expired() call clears expired rows for EVERY provider, not
    just one — the whole-table sweep that lets a stalled provider's stale rows
    get cleared whenever ANY other provider fetches."""
    with db.session_scope() as session:
        _add_provider(session, "p1")
        _add_provider(session, "p2")
        _add_programme(session, "p1", stop_offset_hours=-48, title="P1 old")
        _add_programme(session, "p2", stop_offset_hours=-48, title="P2 old")
        _add_programme(session, "p2", stop_offset_hours=1, title="P2 upcoming")

    config = MagicMock()
    config.epg_retention_hours = 24
    manager = EpgManager(db, config, notifications=None)

    deleted = manager.prune_expired()
    assert deleted == 2

    with db.session_scope(commit=False) as session:
        titles = {p.title for p in session.query(EpgProgramDB).all()}
    assert titles == {"P2 upcoming"}

    manager._executor.shutdown(wait=False)


def test_prune_expired_default_hours_when_config_missing(db):
    """A config lacking epg_retention_hours entirely falls back to the 24h default
    (getattr fallback), never crashing."""
    with db.session_scope() as session:
        _add_provider(session, "p1")
        _add_programme(session, "p1", stop_offset_hours=-30, title="Old")
        _add_programme(session, "p1", stop_offset_hours=-2, title="Recent")

    class _BareConfig:
        pass

    manager = EpgManager(db, _BareConfig(), notifications=None)
    deleted = manager.prune_expired()
    assert deleted == 1

    manager._executor.shutdown(wait=False)


# ---------------------------------------------------------------------------
# Hook wiring — prune_expired runs automatically after a successful fetch
# ---------------------------------------------------------------------------

def test_fetch_worker_prunes_expired_rows_across_all_providers(db, monkeypatch):
    """A successful _fetch_worker run for provider A also sweeps provider B's
    already-expired rows — the natural post-fetch hook (after the
    provider-timestamp commit) reuses the fetch's own open session."""
    import metatv.core.epg_manager as epgmod
    from metatv.core.xmltv_parser import XmltvProgramme

    with db.session_scope() as session:
        _add_provider(session, "fetch-p")
        _add_provider(session, "stale-p")
        # stale-p stopped refreshing long ago; its guide is well past retention.
        _add_programme(session, "stale-p", stop_offset_hours=-72, title="Stale")

    now = now_utc()
    fresh_progs = [
        XmltvProgramme(channel_id="c1", title="Fresh Show", description="",
                       start_time=now - timedelta(minutes=30),
                       stop_time=now + timedelta(minutes=30)),
    ]
    monkeypatch.setattr(epgmod, "parse_xmltv_url", lambda *a, **k: ([], fresh_progs))

    config = MagicMock()
    config.epg_default_refresh_interval = "3d"
    config.epg_retention_hours = 24
    manager = EpgManager(db, config, notifications=None)

    manager._fetch_worker("fetch-p", "Fetch P", None)

    with db.session_scope(commit=False) as session:
        stale_p_count = session.query(EpgProgramDB).filter_by(provider_id="stale-p").count()
        fetch_p_count = session.query(EpgProgramDB).filter_by(provider_id="fetch-p").count()

    assert stale_p_count == 0, (
        "stale-p's long-expired programme must be pruned by the post-fetch hook, "
        "even though fetch-p (not stale-p) is the one that just refreshed"
    )
    assert fetch_p_count == 1, "fetch-p's freshly-fetched programme must survive the prune"

    manager._executor.shutdown(wait=False)
