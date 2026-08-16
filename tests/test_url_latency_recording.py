"""UrlCycler.record_success/record_failure accept response_time_ms — but no
production call site was actually passing it, so median_latency_ms() always
returned 0 and the latency term in Provider.ordered_urls()'s sort key was
inert (#307).

These tests exercise the REAL production call sites (xtream.py's info calls,
xtream.py's fetch_channels, and main_window_streaming.py's alternate-host
failover loop) end to end, patching only the network layer, and assert the
resulting ConnectionAttempt actually carries a non-None integer
response_time_ms — a call-count assertion would pass on exactly the bug this
slice fixes (every one of these sites already called record_success/
record_failure, just without the latency argument).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

import metatv.providers.xtream as xtream_module
from metatv.core.models import Provider, ProviderURL
from metatv.core.repositories import RepositoryFactory
from metatv.providers.xtream import XtreamProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider(urls: list[ProviderURL], provider_id: str = "prov-1") -> Provider:
    """Build a minimal in-memory Provider carrying *urls* (mirrors test_url_cycle.py)."""
    return Provider(
        id=provider_id,
        name="Test Provider",
        type="xtream",
        url=urls[0].url if urls else "http://fallback.example",
        urls=urls,
        username="user",
        password="pass",
    )


class _FakeXtreamAPISuccess:
    """Fake XtreamAPI whose info calls succeed after a small artificial delay."""

    def __init__(self, base_url, username=None, password=None):
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_series_info(self, series_id):
        await asyncio.sleep(0.01)
        return {"info": {"name": "Test Series"}}


class _FakeXtreamAPIFailure:
    """Fake XtreamAPI whose info calls raise a connection error after a delay."""

    def __init__(self, base_url, username=None, password=None):
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_series_info(self, series_id):
        await asyncio.sleep(0.01)
        raise aiohttp.ClientError("connection refused")


class _FakeXtreamAPIBulkFetch:
    """Fake XtreamAPI satisfying the full fetch_channels() call surface with
    empty catalogs — enough to exercise the success path without needing
    convert_to_channel."""

    def __init__(self, base_url, username=None, password=None):
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_live_categories(self):
        return []

    async def get_vod_categories(self):
        return []

    async def get_series_categories(self):
        return []

    async def get_live_streams(self, category_id=None):
        return []

    async def get_vod_streams(self, category_id=None):
        return []

    async def get_series(self, category_id=None):
        return []


# ---------------------------------------------------------------------------
# 1. fetch_series_info success records a non-None integer latency.
# ---------------------------------------------------------------------------

def test_fetch_series_info_success_records_latency(monkeypatch):
    monkeypatch.setattr(xtream_module, "XtreamAPI", _FakeXtreamAPISuccess)

    pu = ProviderURL(url="http://host.example")
    provider = _provider([pu])
    plugin = XtreamProvider()

    result = asyncio.run(plugin.fetch_series_info(provider, "123"))

    assert result is not None
    assert len(pu.recent_attempts) == 1
    attempt = pu.recent_attempts[0]
    assert attempt.success is True
    assert attempt.response_time_ms is not None
    assert isinstance(attempt.response_time_ms, int)


# ---------------------------------------------------------------------------
# 2. fetch_series_info failure ALSO records a non-None integer latency.
# ---------------------------------------------------------------------------

def test_fetch_series_info_failure_records_latency(monkeypatch):
    monkeypatch.setattr(xtream_module, "XtreamAPI", _FakeXtreamAPIFailure)

    pu = ProviderURL(url="http://host.example")
    provider = _provider([pu])
    plugin = XtreamProvider()

    result = asyncio.run(plugin.fetch_series_info(provider, "123"))

    assert result is None
    assert len(pu.recent_attempts) == 1
    attempt = pu.recent_attempts[0]
    assert attempt.success is False
    assert attempt.response_time_ms is not None
    assert isinstance(attempt.response_time_ms, int)


# ---------------------------------------------------------------------------
# 3. fetch_channels (the full-catalog bulk fetch) must NOT record latency —
#    it's deliberately excluded because its elapsed time is payload-dominated.
# ---------------------------------------------------------------------------

def test_fetch_channels_records_no_latency(monkeypatch):
    monkeypatch.setattr(xtream_module, "XtreamAPI", _FakeXtreamAPIBulkFetch)

    pu = ProviderURL(url="http://host.example")
    provider = _provider([pu])
    plugin = XtreamProvider()

    channels = asyncio.run(plugin.fetch_channels(provider))

    assert channels == []
    assert len(pu.recent_attempts) == 1
    attempt = pu.recent_attempts[0]
    assert attempt.success is True
    assert attempt.response_time_ms is None


# ---------------------------------------------------------------------------
# 4. validate_and_failover_stream_url's alternate-host loop records latency
#    on BOTH the success and the failure branch — this is the single most
#    important site (it measures the actual stream host).
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_provider(session, provider_id: str, name: str, url: str, urls=None):
    from metatv.core.database import ProviderDB
    p = ProviderDB(
        id=provider_id,
        name=name,
        type="xtream",
        url=url,
        urls=urls or [],
        is_active=True,
    )
    session.add(p)
    session.flush()
    return p


def _make_mixin(db):
    """A bare ``_StreamingMixin`` instance wired with a real Database
    (mirrors tests/test_failover_sticks.py's ``_make_mixin``)."""
    from tests.conftest import wire_shutdown_flag
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = wire_shutdown_flag(_StreamingMixin.__new__(_StreamingMixin))
    obj.loading_channels = set()
    obj.db = db
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-123"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    return obj


def _reload_url(db, provider_id: str, base_url: str) -> ProviderURL:
    """Re-read a provider's alternate-URL stats from a FRESH session."""
    with db.session_scope(commit=False) as session:
        provider_model = RepositoryFactory(session).providers.to_model(
            RepositoryFactory(session).providers.get_by_id(provider_id)
        )
    return next(u for u in provider_model.urls if u.url.rstrip('/') == base_url.rstrip('/'))


def test_failover_alt_host_success_records_latency(tmp_path):
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://deadhost.example:8080"
    alt_base = "http://goodhost.example:9090"
    path_and_query = "/live/testuser/testpass/11111.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv1", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),   # primary fails, no text error
        (True, None),    # alternate succeeds
    ]):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert final_url == alt_base + path_and_query
    assert err is None

    alt_pu = _reload_url(db, provider_id, alt_base)
    assert len(alt_pu.recent_attempts) == 1
    attempt = alt_pu.recent_attempts[0]
    assert attempt.success is True
    assert attempt.response_time_ms is not None
    assert isinstance(attempt.response_time_ms, int)


def test_failover_alt_host_failure_records_latency(tmp_path):
    db = _make_db(tmp_path)
    provider_id = str(uuid.uuid4())
    primary_base = "http://deadhost.example:8080"
    alt_base = "http://alsobadhost.example:9090"
    path_and_query = "/live/testuser/testpass/22222.ts"
    stream_url = primary_base + path_and_query

    with db.session_scope() as session:
        _insert_provider(
            session, provider_id, "TestProv2", primary_base,
            urls=[{"url": alt_base, "priority": 0, "is_active": True}],
        )

    obj = _make_mixin(db)
    with patch.object(obj, "validate_stream_url", side_effect=[
        (False, None),   # primary fails, no text error
        (False, None),   # alternate ALSO fails, no text error
    ]):
        final_url, err = obj.validate_and_failover_stream_url(stream_url, provider_id)

    assert final_url == ""

    alt_pu = _reload_url(db, provider_id, alt_base)
    assert len(alt_pu.recent_attempts) == 1
    attempt = alt_pu.recent_attempts[0]
    assert attempt.success is False
    assert attempt.response_time_ms is not None
    assert isinstance(attempt.response_time_ms, int)
