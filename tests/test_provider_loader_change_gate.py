"""DB-7: the catalog-upsert change gate, and the guard it depends on.

``_flush_batch`` (``provider_loader.py``) now skips the heavy multi-column
upsert for a row whose full catalog payload already matches what's stored —
see ``test_channel_bulk_upsert.py`` for the gate's own unit coverage
(SQL-statement proof it fires, mixed-batch behaviour, the rating/tmdb-id
edge cases it must NOT over-gate).

This file covers the one thing that makes the gate SAFE to ship at all: a
completed pass still prunes rows the source stopped listing
(``prune_vanished_channels``, unchanged by this slice — it still diffs on
``last_seen_at``, which every row keeps getting stamped with regardless of
whether it took the gated or full-upsert path). But if a refresh dies
PARTWAY through storing, the served-id set is incomplete and — were pruning
to run anyway — would read every row this pass never reached as "the source
stopped listing it" and delete the rest of the catalog. ``load_provider``'s
existing structure already prevents this (the prune call sits inside the
same ``try`` as ``_store_channels``, AFTER it, so any exception during store
takes the ``except: session.rollback(); raise`` path and never reaches the
prune call) — this test proves that guard holds with DB-7's gate in the mix,
using the interrupted-pass scenario CLAUDE.md calls out as the test that
matters most for this slice.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from metatv.core.database import ChannelDB
from metatv.core.models import Provider
from metatv.core.provider_loader import ProviderLoadThread

from tests.conftest import make_channel_double


@pytest.fixture
def fake_provider():
    """Minimal Provider instance for testing (no network calls)."""
    p = Provider.__new__(Provider)
    p.id = "test_prov"
    p.name = "Test Provider"
    p.type = "xtream"
    p.url = "http://example.com"
    p.username = "user"
    p.password = "pass"
    p.urls = []
    return p


def _stub_plugin(channels):
    """A provider plugin double whose fetch_channels returns *channels*.

    ``fetch_account_info = None`` mirrors the established pattern in
    ``test_provider_loader_zero_channels.py``: ``hasattr`` is still True (the
    attribute exists), the ``await None(...)`` call fails, and
    ``_refresh_account_info``'s own try/except swallows it — no network, no
    extra stubbing needed.
    """
    plugin = MagicMock()
    plugin.fetch_channels = AsyncMock(return_value=channels)
    plugin.fetch_account_info = None
    return plugin


def test_interrupted_store_prunes_nothing(fake_provider, tmp_db):
    """The critical DB-7 safety test: a refresh that dies mid-store must
    never prune, even though the served set it would have diffed against is
    a subset of the truth.

    Seeds a channel this provider will NOT re-list on the next fetch (so a
    COMPLETED pass would prune it as vanished — its last_seen_at is already
    older than what this pass would stamp), then forces the store to raise
    partway through. The seeded row must survive untouched.
    """
    old_seen_at = datetime.utcnow() - timedelta(days=10)
    with tmp_db.session_scope() as s:
        s.add(ChannelDB(
            id="stale_ch", source_id="stale_ch", provider_id=fake_provider.id,
            name="Stale Channel", category="News", media_type="live",
            quality="hd", last_seen_at=old_seen_at,
        ))

    thread = ProviderLoadThread(fake_provider, tmp_db)
    assert thread.kind == "full", "pruning only runs for a full refresh — precondition"

    new_channel = make_channel_double(
        id="new_ch", source_id="new_ch", provider_id=fake_provider.id,
        name="New Channel", category="News",
    )
    stub_plugin = _stub_plugin([new_channel])

    with patch.object(ProviderLoadThread, "_flush_batch",
                       side_effect=RuntimeError("simulated mid-store failure")):
        with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
            with pytest.raises(RuntimeError, match="simulated mid-store failure"):
                asyncio.run(thread.load_provider())

    session = tmp_db.get_session()
    try:
        stale = session.query(ChannelDB).filter_by(id="stale_ch").one_or_none()
        assert stale is not None, (
            "an interrupted pass must never prune — the in-memory served-id set "
            "from a partial store is incomplete and diffing against it would "
            "delete the rest of the catalog"
        )
        assert stale.last_seen_at == old_seen_at, (
            "a row the interrupted pass never reached must not even have its "
            "presence stamp touched"
        )
        # And the row this pass WAS trying to write never landed either —
        # the whole batch (one INSERT..ON CONFLICT statement) failed atomically.
        new_row = session.query(ChannelDB).filter_by(id="new_ch").one_or_none()
        assert new_row is None, (
            "the failed batch must not have partially landed"
        )
    finally:
        session.close()


def test_completed_pass_still_prunes_with_the_gate_in_place(fake_provider, tmp_db):
    """Sanity companion to the interrupted-pass test: a pass that completes
    normally must still prune a genuinely vanished row — proving the guard
    above isn't hiding a gate that broke pruning outright.
    """
    old_seen_at = datetime.utcnow() - timedelta(days=10)
    with tmp_db.session_scope() as s:
        s.add(ChannelDB(
            id="stale_ch", source_id="stale_ch", provider_id=fake_provider.id,
            name="Stale Channel", category="News", media_type="live",
            quality="hd", last_seen_at=old_seen_at,
        ))

    thread = ProviderLoadThread(fake_provider, tmp_db)
    new_channel = make_channel_double(
        id="new_ch", source_id="new_ch", provider_id=fake_provider.id,
        name="New Channel", category="News",
    )
    stub_plugin = _stub_plugin([new_channel])

    with patch("metatv.core.provider_loader.get_provider", return_value=stub_plugin):
        asyncio.run(thread.load_provider())

    session = tmp_db.get_session()
    try:
        stale = session.query(ChannelDB).filter_by(id="stale_ch").one_or_none()
        assert stale is None, "a genuinely vanished row must still be pruned on a completed pass"
        new_row = session.query(ChannelDB).filter_by(id="new_ch").one_or_none()
        assert new_row is not None, "the freshly-served row must be stored"
    finally:
        session.close()
