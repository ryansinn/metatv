"""LIVE-1 — the live-only refresh loader path.

Measured live on the owner's two active sources, 2026-09-03:
``get_live_streams`` alone returns the COMPLETE live catalog in one request
(ProSat 17,906 streams/5.0MB/1.6s; Shark 55,761/18.7MB/3.9s), byte-identical
to the live half of a full refresh. ``ProviderLoadThread(kind="live_only")``
is what makes that the actual round trip instead of the whole catalog:

* ``fetch_channels`` is called with ``media_types={"live"}`` — proven against
  a stub plugin, never against the real Xtream implementation (that is
  ``test_xtream_provider.py`` territory, unchanged here).
* The SAME chunked upsert runs over whatever rows came back — no separate
  live-only insert path.
* The vanished-channel PRUNE is skipped for ``kind="live_only"``: it never
  fetched VOD/series, so treating their untouched rows as "the source
  stopped listing them" would delete the catalog out from under itself.
  VOD rows are proven untouched (their stored fields don't move) rather than
  merely "not deleted", which is the sharper claim CLAUDE.md's UI/behavior
  rule asks for.

The stamping half (``last_live_refresh_at`` / ``last_catalog_refresh_at``) is
NOT the loader's job — it's ``_CatalogRefreshTickMixin._mark_catalog_refreshed``,
called from the refresh-success path — and is covered in
``test_catalog_refresh_tick.py`` instead.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatv.core.database import ChannelDB, Database
from metatv.core.models import Channel, MediaType, Provider, StreamQuality
from metatv.core.provider_loader import ProviderLoadThread


@pytest.fixture
def tmp_db():
    """File-backed SQLite Database (not :memory:) — CLAUDE.md tests rule."""
    tmpfile = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    tmpfile.close()
    db_path = tmpfile.name

    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db
    db.close()
    Path(db_path).unlink(missing_ok=True)


@pytest.fixture
def fake_provider() -> Provider:
    p = Provider.__new__(Provider)
    p.id = "test_prov"
    p.name = "Test Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "testuser"
    p.password = "testpass"
    p.urls = []
    return p


def _live_channel(provider_id: str, source_id: str, name: str) -> Channel:
    return Channel(
        id=f"{provider_id}_{source_id}",
        source_id=source_id,
        provider_id=provider_id,
        name=name,
        stream_url=f"http://example.com/live/{source_id}",
        category="Sports",
        category_id="1",
        media_type=MediaType.LIVE,
        quality=StreamQuality.HD,
        raw_data={},
    )


def _run_load(thread: ProviderLoadThread, channels: list[Channel]) -> tuple[bool, str]:
    """Drive ``load_provider()`` with a stub plugin returning *channels*, and
    capture the ``finished`` signal payload."""
    signal_args = []
    thread.finished.connect(lambda s, m: signal_args.append((s, m)))

    stub_plugin = MagicMock()
    stub_plugin.fetch_channels = AsyncMock(return_value=channels)
    stub_plugin.fetch_account_info = None

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    assert len(signal_args) == 1, "finished must fire exactly once"
    return signal_args[0]


# ---------------------------------------------------------------------------
# kind="live_only" restricts the fetch to media_types={"live"}
# ---------------------------------------------------------------------------

def test_live_only_kind_fetches_with_media_types_live_only(tmp_db, fake_provider):
    thread = ProviderLoadThread(fake_provider, tmp_db, kind="live_only")
    stub_plugin = MagicMock()
    stub_plugin.fetch_channels = AsyncMock(
        return_value=[_live_channel(fake_provider.id, "1", "ESPN")]
    )
    stub_plugin.fetch_account_info = None

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    _, kwargs = stub_plugin.fetch_channels.call_args
    assert kwargs.get("media_types") == {"live"}, (
        "kind='live_only' must restrict the provider-plugin fetch to live "
        "streams only — that is the whole point of the round trip being one "
        "get_live_streams call instead of the full catalog"
    )


def test_full_kind_fetches_with_media_types_none(tmp_db, fake_provider):
    """Default kind="full" — unchanged historical behaviour: no restriction."""
    thread = ProviderLoadThread(fake_provider, tmp_db)  # kind defaults to "full"
    stub_plugin = MagicMock()
    stub_plugin.fetch_channels = AsyncMock(
        return_value=[_live_channel(fake_provider.id, "1", "ESPN")]
    )
    stub_plugin.fetch_account_info = None

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    _, kwargs = stub_plugin.fetch_channels.call_args
    assert kwargs.get("media_types") is None


# ---------------------------------------------------------------------------
# The same chunked upsert runs; VOD rows are untouched; no prune
# ---------------------------------------------------------------------------

def test_live_only_upserts_live_rows_and_leaves_vod_rows_untouched(tmp_db, fake_provider):
    """Seed one VOD row (as a prior FULL refresh would have) and one stale
    live row, then run a live_only pass that only re-lists the live row under
    a NEW name. The VOD row's stored fields must not move at all — not
    touched, not pruned — and the live row must pick up the new name."""
    from datetime import datetime, timedelta

    old_seen_at = datetime.utcnow() - timedelta(days=10)
    with tmp_db.session_scope() as session:
        session.add(ChannelDB(
            id=f"{fake_provider.id}_vod1", source_id="vod1",
            provider_id=fake_provider.id, name="Old Movie",
            stream_url="http://example.com/movie/vod1", media_type="movie",
            last_seen_at=old_seen_at,
        ))
        session.add(ChannelDB(
            id=f"{fake_provider.id}_1", source_id="1",
            provider_id=fake_provider.id, name="ESPN (old name)",
            stream_url="http://example.com/live/1", media_type="live",
            last_seen_at=old_seen_at,
        ))

    thread = ProviderLoadThread(fake_provider, tmp_db, kind="live_only")
    success, message = _run_load(
        thread, [_live_channel(fake_provider.id, "1", "ESPN HD")]
    )
    assert success is True, message

    with tmp_db.session_scope(commit=False) as session:
        vod = session.query(ChannelDB).filter_by(id=f"{fake_provider.id}_vod1").first()
        assert vod is not None, (
            "the VOD row must survive a live-only refresh — pruning must be "
            "skipped entirely, not just scoped to live rows"
        )
        assert vod.name == "Old Movie", "a live-only pass must not touch VOD rows at all"
        assert vod.last_seen_at == old_seen_at, (
            "VOD last_seen_at must not be re-stamped by a pass that never "
            "fetched VOD content"
        )

        live = session.query(ChannelDB).filter_by(id=f"{fake_provider.id}_1").first()
        assert live is not None
        assert live.name == "ESPN HD", "the live row must upsert through the same chunked path"
        assert live.last_seen_at is not None and live.last_seen_at > old_seen_at


def test_live_only_never_prunes_even_when_a_live_row_vanishes(tmp_db, fake_provider):
    """A live channel the source no longer lists must NOT be deleted by a
    live-only pass — aging/pruning stays a FULL-refresh-only concern here;
    the row simply keeps its old last_seen_at (existing aging semantics)."""
    from datetime import datetime, timedelta

    old_seen_at = datetime.utcnow() - timedelta(days=10)
    with tmp_db.session_scope() as session:
        session.add(ChannelDB(
            id=f"{fake_provider.id}_gone", source_id="gone",
            provider_id=fake_provider.id, name="Vanished Channel",
            stream_url="http://example.com/live/gone", media_type="live",
            last_seen_at=old_seen_at,
        ))

    thread = ProviderLoadThread(fake_provider, tmp_db, kind="live_only")
    success, message = _run_load(
        thread, [_live_channel(fake_provider.id, "1", "ESPN")]
    )
    assert success is True, message

    with tmp_db.session_scope(commit=False) as session:
        gone = session.query(ChannelDB).filter_by(id=f"{fake_provider.id}_gone").first()
        assert gone is not None, "live-only must never prune, even a live row not re-listed"
        assert gone.last_seen_at == old_seen_at


def test_full_kind_still_prunes_vanished_channels(tmp_db, fake_provider):
    """Sibling control: kind="full" (default) keeps the existing prune
    behaviour — proves the skip above is live_only-specific, not a
    regression to pruning generally."""
    from datetime import datetime, timedelta

    old_seen_at = datetime.utcnow() - timedelta(days=10)
    with tmp_db.session_scope() as session:
        session.add(ChannelDB(
            id=f"{fake_provider.id}_gone", source_id="gone",
            provider_id=fake_provider.id, name="Vanished Channel",
            stream_url="http://example.com/live/gone", media_type="live",
            last_seen_at=old_seen_at,
        ))

    thread = ProviderLoadThread(fake_provider, tmp_db)  # kind="full"
    success, message = _run_load(
        thread, [_live_channel(fake_provider.id, "1", "ESPN")]
    )
    assert success is True, message

    with tmp_db.session_scope(commit=False) as session:
        gone = session.query(ChannelDB).filter_by(id=f"{fake_provider.id}_gone").first()
        assert gone is None, "a full refresh must still prune channels the source dropped"
