"""Regression: the unmatched-guide re-fetch must CONVERGE, not fire every launch.

`refresh_all_if_needed` re-fetches a time-fresh provider's guide once per session when
it has unmatched rows, to rebuild channel links.  The in-memory guard
(`_unmatched_refresh_attempted`) resets every launch, so for a provider whose guide can
NEVER match its channels (a source serving placeholder/foreign EPG, e.g. TREX) this fired
a network re-fetch on EVERY startup forever.

Fix: only re-fetch the UNNAMED legacy case (rows with no `channel_name` — a fetch is the
only way to populate names so the DB-only relink can then work).  The merely
"unmatched but named" case is handled by `relink_all()` DB-only on every activation, so a
network re-fetch adds nothing — and the unnamed case converges (one fetch stores names →
the trigger goes False).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import Database, ProviderDB, EpgProgramDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _make_manager(db):
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = "auto"
    return EpgManager(db, config, notifications=None)


def _add_fresh_provider(session, pid):
    """A time-FRESH provider (so needs_refresh is False — isolates the unmatched path)."""
    now = now_utc()
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com", username="u", password="p",
        is_active=True, epg_url="http://e/xmltv.php", epg_enabled=True,
        epg_last_fetched=now, epg_data_start=now - timedelta(days=1),
        epg_data_end=now + timedelta(days=1), epg_refresh_interval="auto",
    ))


def _add_epg_row(session, pid, *, channel_name):
    """An UNMATCHED guide row (channel_db_id None); channel_name distinguishes the cases."""
    now = datetime.utcnow()
    session.add(EpgProgramDB(
        provider_id=pid, channel_epg_id="x.tv", channel_db_id=None,
        channel_name=channel_name, title="Show",
        start_time=now, stop_time=now + timedelta(hours=1),
    ))


def test_named_unmatched_does_not_refetch(db):
    """A time-fresh provider whose rows are unmatched but NAMED must NOT re-fetch —
    relink_all() handles named rows DB-only; this was the TREX-every-launch bug."""
    with db.session_scope() as s:
        _add_fresh_provider(s, "trex")
        _add_epg_row(s, "trex", channel_name="TREX Sports 1")  # named, unmatched

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh, \
         patch.object(manager, "_ensure_epg_url"):
        manager.refresh_all_if_needed()
        mock_refresh.assert_not_called()
    manager._executor.shutdown(wait=False)


def test_unnamed_unmatched_refetches_once_then_converges(db):
    """A provider with UNNAMED legacy rows re-fetches once (to populate names), and the
    per-session guard prevents a second fetch in the same session."""
    with db.session_scope() as s:
        _add_fresh_provider(s, "legacy")
        _add_epg_row(s, "legacy", channel_name="")  # unnamed, unmatched

    manager = _make_manager(db)
    with patch.object(manager, "_start_refresh") as mock_refresh, \
         patch.object(manager, "_ensure_epg_url"):
        manager.refresh_all_if_needed()
        assert mock_refresh.call_count == 1, "unnamed legacy guide should re-fetch once"
        manager.refresh_all_if_needed()
        assert mock_refresh.call_count == 1, "same session must not re-fetch again (guard)"
    manager._executor.shutdown(wait=False)
