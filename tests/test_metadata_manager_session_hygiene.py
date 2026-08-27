"""Regression guard: MetadataManager.get_metadata() must not hold a DB session
open while awaiting a provider's network call.

Migration-resilience wave 2 (owner log 2026-08-01): a details-pane metadata
fetch held a session open (legacy ``Database.get_session()``, never closed
until every provider's network call returned) across the ENTIRE provider
fetch loop, only writing at the very end. That long-held session was the
actual root cause the lock-retry work in ``channel.py`` is the belt for —
this is the suspenders: the fetch-then-write must be fetch with NO session
open -> open session_scope -> write -> close (CLAUDE.md #database-sessions).

The test below is structural: it dependency-injects a fake metadata provider
whose ``get_details()`` coroutine — invoked exactly at the point a real
network call would happen — asserts that zero DB sessions (tracked at the
lowest-level ``SessionLocal`` factory, so it catches BOTH ``session_scope()``
and the legacy ``get_session()`` pattern) are open. A real file-backed
(tmp_path) Database is used per CLAUDE.md's testing rule; only the "network"
is faked.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'metadata_hygiene.db'}")
    d.create_tables()
    yield d
    d.close()


def _make_channel(session, channel_id: str, name: str, media_type: str = "movie") -> None:
    from metatv.core.database import ChannelDB
    session.add(ChannelDB(
        id=channel_id,
        source_id=f"src-{channel_id}",
        provider_id="p1",
        name=name,
        media_type=media_type,
    ))


class _SessionCounter:
    """Wraps ``Database.SessionLocal`` (the raw sessionmaker) to count how many
    sessions are currently open.

    Deliberately wraps the LOWEST-level session factory rather than
    ``session_scope()`` alone: the original bug (``metadata_manager.py``
    calling the legacy ``Database.get_session()`` and holding it open across
    every provider network call, never touching ``session_scope`` at all)
    would NOT have been caught by a probe that only instruments
    ``session_scope`` — both ``session_scope()`` and ``get_session()``
    ultimately call ``self.SessionLocal()``, so wrapping that single seam
    catches a regression to either legacy pattern.
    """

    def __init__(self, db):
        self._db = db
        self._real_factory = db.SessionLocal
        self.open_count = 0

    def __call__(self, *args, **kwargs):
        session = self._real_factory(*args, **kwargs)
        self.open_count += 1
        real_close = session.close

        def _tracked_close():
            self.open_count -= 1
            real_close()

        session.close = _tracked_close
        return session


def _make_provider(supported_types, get_details_fn, *, name="probe"):
    from metatv.metadata_providers.base import MetadataProviderPlugin

    class _Provider(MetadataProviderPlugin):
        @property
        def name(self) -> str:
            return name

        @property
        def display_name(self) -> str:
            return "Probe Provider"

        @property
        def supported_media_types(self):
            return supported_types

        @property
        def supported_fields(self):
            return ["plot", "poster"]

        async def search(self, title, year=None, media_type="movie"):
            return []

        async def get_details(self, external_id, media_type="movie"):
            return await get_details_fn(external_id, media_type)

        async def test_connection(self):
            return (True, None)

        def is_enabled(self) -> bool:
            return True

        def get_priority(self) -> int:
            return 1

    return _Provider()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_get_metadata_holds_no_session_during_network_call(db):
    """The provider's get_details() coroutine — the network phase — must see
    ZERO open session_scope()s. This is the literal fetch-then-write contract:
    read (closed) -> network (no session) -> write (fresh session)."""
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c1", "Test Movie", media_type="movie")

    counter = _SessionCounter(db)
    db.SessionLocal = counter

    seen_during_network: list[int] = []

    async def _get_details(external_id, media_type):
        seen_during_network.append(counter.open_count)
        return MetadataResult(title="Test Movie", plot="A great plot", confidence=1.0)

    registry = MetadataProviderRegistry()
    registry.register(_make_provider(["movie", "series"], _get_details))

    mgr = MetadataManager(registry, db)
    result = asyncio.run(mgr.get_metadata("c1"))

    assert seen_during_network == [0], (
        f"expected 0 open sessions while the network call ran, saw {seen_during_network}"
    )
    assert result is not None
    assert result.title == "Test Movie"
    assert result.plot == "A great plot"

    # And the result was actually persisted by a session opened AFTER the
    # network phase (proves the write phase is real, not skipped).
    with db.session_scope(commit=False) as session:
        from metatv.core.database import ChannelDB, MetadataDB
        ch = session.query(ChannelDB).filter_by(id="c1").first()
        assert ch.metadata_id is not None
        meta = session.query(MetadataDB).filter_by(id=ch.metadata_id).first()
        assert meta.plot == "A great plot"


def test_get_metadata_multiple_providers_no_session_across_any_call(db):
    """Two providers in the fallback chain — neither's network call sees an
    open session (guards against a partial fix that only closes the session
    around the FIRST provider)."""
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c2", "Another Movie", media_type="movie")

    counter = _SessionCounter(db)
    db.SessionLocal = counter

    seen: list[int] = []

    async def _first(external_id, media_type):
        seen.append(counter.open_count)
        return MetadataResult(title="Another Movie", confidence=0.5)  # incomplete: no plot/poster

    async def _second(external_id, media_type):
        seen.append(counter.open_count)
        return MetadataResult(plot="Filled in by provider 2", confidence=0.9)

    registry = MetadataProviderRegistry()
    registry.register(_make_provider(["movie"], _first, name="p_first"))
    registry.register(_make_provider(["movie"], _second, name="p_second"))

    mgr = MetadataManager(registry, db)
    result = asyncio.run(mgr.get_metadata("c2"))

    assert seen == [0, 0], f"expected every provider call to see 0 open sessions, saw {seen}"
    assert result is not None
    assert result.plot == "Filled in by provider 2"


def test_get_metadata_cache_hit_never_calls_provider(db):
    """A fresh cache hit must return from the read phase alone — the network
    phase (and the fake provider that would fail the test if called) never
    runs."""
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
    from metatv.metadata_providers.base import MetadataResult

    with db.session_scope() as session:
        _make_channel(session, "c3", "Cached Movie", media_type="movie")

    async def _should_not_be_called(external_id, media_type):
        raise AssertionError("provider network call must not run on a cache hit")

    registry = MetadataProviderRegistry()
    registry.register(_make_provider(["movie"], _should_not_be_called))
    mgr = MetadataManager(registry, db)

    # Prime the cache directly (bypassing the network path).
    with db.session_scope() as session:
        from metatv.core.database import ChannelDB
        channel = session.query(ChannelDB).filter_by(id="c3").first()
        mgr._save_metadata_cache(
            session, channel,
            MetadataResult(title="Cached Movie", plot="Already cached", poster_url="http://x/p.jpg"),
        )

    result = asyncio.run(mgr.get_metadata("c3"))
    assert result is not None
    assert result.plot == "Already cached"


def test_get_metadata_channel_not_found_returns_none_no_network(db):
    from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry

    async def _should_not_be_called(external_id, media_type):
        raise AssertionError("provider network call must not run for a missing channel")

    registry = MetadataProviderRegistry()
    registry.register(_make_provider(["movie"], _should_not_be_called))
    mgr = MetadataManager(registry, db)

    result = asyncio.run(mgr.get_metadata("does-not-exist"))
    assert result is None
