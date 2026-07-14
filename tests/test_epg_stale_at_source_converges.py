"""Regression: a feed that is stale AT SOURCE must not re-fetch every launch.

``needs_refresh`` has an "expiry floor": if the guide has run out
(``epg_data_end < now``) it forces an immediate re-fetch so a time interval never
leaves an empty "On Now". But a provider whose FEED lags real time serves
programme data that is already expired the moment it is fetched
(``epg_data_end < epg_last_fetched``). For such a feed the expiry floor would fire
on EVERY launch and never converge — the BiggyJuke loop, a sibling of the TREX
unmatched-guide loop fixed in #285.

Fix: suppress the expiry floor when the guide was already expired at fetch time,
and fall back to the interval throttle (auto delta, min 6 h) so a genuinely
recovering feed is re-checked periodically rather than hammered every launch. A
guide that was valid at fetch time but has since run out is the legitimate case
the floor exists for and still triggers a re-fetch.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import Database, ProviderDB, EpgProgramDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import now_utc, epg_auto_delta


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _manager(db, *, default_interval="auto"):
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = default_interval
    return EpgManager(db, config, notifications=None)


def _provider(*, last_fetched, data_start, data_end, interval="auto"):
    """A plain (unpersisted) ProviderDB — needs_refresh reads attributes only."""
    return ProviderDB(
        id="p", name="p", type="xtream", url="http://e.com",
        username="u", password="p", is_active=True,
        epg_url="http://e/xmltv.php", epg_enabled=True,
        epg_last_fetched=last_fetched,
        epg_data_start=data_start, epg_data_end=data_end,
        epg_refresh_interval=interval,
    )


def test_stale_at_source_auto_does_not_refetch_right_after_fetch(db):
    """AUTO: guide already expired at fetch time (feed lags) + just fetched → no re-fetch.

    This is the BiggyJuke every-launch loop: without the fix the expiry floor fires
    because epg_data_end < now, and it re-fetches on every launch forever.
    """
    now = now_utc()
    mgr = _manager(db)
    provider = _provider(
        last_fetched=now,                 # fetched this launch
        data_start=now - timedelta(days=2),
        data_end=now - timedelta(hours=4),  # newest programme is already 4 h in the past
    )
    assert mgr.needs_refresh(provider) is False
    mgr._executor.shutdown(wait=False)


def test_stale_at_source_auto_refetches_once_throttle_elapses(db):
    """AUTO: a stale-at-source feed is still re-checked periodically (throttle), not never."""
    now = now_utc()
    mgr = _manager(db)
    data_start = now - timedelta(hours=10)
    data_end = now - timedelta(hours=8)     # stale at source; depth 2 h → auto delta clamps to 6 h
    delta = epg_auto_delta(data_start, data_end)
    provider = _provider(
        last_fetched=now - delta - timedelta(hours=1),  # throttle window elapsed
        data_start=data_start, data_end=data_end,
    )
    assert mgr.needs_refresh(provider) is True
    mgr._executor.shutdown(wait=False)


def test_legitimately_expired_guide_still_refetches(db):
    """AUTO: a guide valid at fetch time that has SINCE run out must still re-fetch.

    epg_data_end >= epg_last_fetched (the guide extended past the fetch) but is now
    in the past — the genuine 'On Now is empty, refill it' case the floor exists for.
    """
    now = now_utc()
    mgr = _manager(db)
    provider = _provider(
        last_fetched=now - timedelta(days=2),
        data_start=now - timedelta(days=4),
        data_end=now - timedelta(hours=1),   # was ~2 days ahead at fetch, ran out an hour ago
    )
    assert mgr.needs_refresh(provider) is True
    mgr._executor.shutdown(wait=False)


def test_stale_at_source_when_stale_is_throttled(db):
    """WHEN_STALE: a permanently-stale-at-source feed is throttled, not re-fetched every launch."""
    now = now_utc()
    mgr = _manager(db, default_interval="when_stale")
    provider = _provider(
        last_fetched=now,
        data_start=now - timedelta(days=2),
        data_end=now - timedelta(hours=4),   # stale at source
        interval="when_stale",
    )
    assert mgr.needs_refresh(provider) is False
    mgr._executor.shutdown(wait=False)


def test_when_stale_still_refetches_a_legitimately_expired_guide(db):
    """WHEN_STALE: guide valid at fetch that has since run out still triggers a re-fetch."""
    now = now_utc()
    mgr = _manager(db, default_interval="when_stale")
    provider = _provider(
        last_fetched=now - timedelta(days=2),
        data_start=now - timedelta(days=4),
        data_end=now - timedelta(hours=1),   # ran out after fetch — legitimately stale
        interval="when_stale",
    )
    assert mgr.needs_refresh(provider) is True
    mgr._executor.shutdown(wait=False)


def test_stale_at_source_end_to_end_no_refetch_every_launch(db):
    """Integration: refresh_all_if_needed must NOT re-fetch a just-fetched stale-at-source
    provider (the observable BiggyJuke symptom)."""
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(
            id="biggy", name="ProSat (BiggyJuke)", type="xtream", url="http://e.com",
            username="u", password="p", is_active=True,
            epg_url="http://e/xmltv.php", epg_enabled=True,
            epg_last_fetched=now,
            epg_data_start=now - timedelta(days=2),
            epg_data_end=now - timedelta(hours=4),   # stale at source
            epg_refresh_interval="auto",
        ))
    mgr = _manager(db)
    with patch.object(mgr, "_start_refresh") as mock_refresh, \
         patch.object(mgr, "_ensure_epg_url"):
        mgr.refresh_all_if_needed()
        mock_refresh.assert_not_called()
    mgr._executor.shutdown(wait=False)
