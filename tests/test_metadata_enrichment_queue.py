"""Behavioral tests for MetadataEnrichmentQueue (roadmap #249 — background,
queue-based metadata enrichment).

No real network: a hand-written ``_FakeProvider`` (a real ``MetadataProviderPlugin``
subclass, drop-in for the abstract interface) stands in for the provider layer.
DB is a real, file-backed ``Database`` on ``tmp_path`` — never ``:memory:``.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pytest

from metatv.core.database import ChannelDB, Database, MetadataDB, ProviderDB, WatchQueueDB
from metatv.core.metadata_enrichment_queue import (
    _MAX_ENRICH_ATTEMPTS,
    MetadataEnrichmentQueue,
)
from metatv.core.metadata_manager import MetadataManager, MetadataProviderRegistry
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.tag import _clear_tag_cache
from metatv.metadata_providers.base import MetadataProviderPlugin, MetadataResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def db(tmp_path: Path):
    """File-backed Database with all tables + lightweight migrations applied."""
    _clear_tag_cache()
    d = Database(f"sqlite:///{tmp_path / 'metadata_enrich.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture()
def config_obj(tmp_path):
    """Isolated Config with a 90-day old-content TTL (matches the module default)."""
    from metatv.core.config import Config

    c = Config(config_dir=tmp_path / "config")
    c.metadata_old_content_ttl_days = 90
    return c


@pytest.fixture(scope="module")
def qapp():
    """A QApplication so QObject-based managers can be constructed."""
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _provider(session, pid: str = "p1", *, is_active: bool = True) -> str:
    session.add(
        ProviderDB(
            id=pid, name=f"Provider {pid}", type="xtream",
            url="http://example.com", username="u", password="p",
            is_active=is_active,
        )
    )
    session.flush()
    return pid


def _channel(
    session,
    provider_id: str = "p1",
    *,
    name: str = "Test",
    media_type: str = "movie",
    is_favorite: bool = False,
    play_count: int = 0,
    last_played=None,
    is_hidden: bool = False,
    metadata_id: Optional[str] = None,
) -> str:
    cid = str(uuid.uuid4())
    session.add(
        ChannelDB(
            id=cid, source_id=str(uuid.uuid4()), provider_id=provider_id,
            name=name, media_type=media_type, is_favorite=is_favorite,
            play_count=play_count, last_played=last_played, is_hidden=is_hidden,
            metadata_id=metadata_id,
        )
    )
    session.flush()
    return cid


def _mm(provider: "MetadataProviderPlugin", db: Database) -> MetadataManager:
    reg = MetadataProviderRegistry()
    reg.register(provider)
    return MetadataManager(reg, db)


@pytest.fixture()
def make_queue(db, config_obj, qapp):
    """Factory for a real ``MetadataEnrichmentQueue`` with guaranteed teardown.

    Without an explicit, awaited ``shutdown()`` a queue's background worker can
    still be mid-emit when the test function returns and the (parent-less)
    QObject becomes unreferenced — a real cross-thread crash ("wrapped C/C++
    object ... has been deleted"), not just a leak. Every queue built through
    this factory is shut down and its worker joined at teardown, even on
    assertion failure, so no thread ever outlives its QObject.
    """
    created: list[MetadataEnrichmentQueue] = []

    def _make(provider: "MetadataProviderPlugin", **kwargs) -> MetadataEnrichmentQueue:
        q = MetadataEnrichmentQueue(
            db, config_obj, _mm(provider, db), migration_manager=None, **kwargs
        )
        created.append(q)
        return q

    yield _make

    for q in created:
        q.shutdown()
        future = q._worker_future
        if future is not None:
            try:
                future.result(timeout=5)
            except Exception:
                pass


def _wait_idle(queue: MetadataEnrichmentQueue, timeout: float = 6.0) -> None:
    """Block until the queue's worker has gone idle (real-time bounded poll)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        with queue._lock:
            running = queue._running
        if not running:
            return
        time.sleep(0.01)
    raise AssertionError("queue did not go idle within timeout")


class _FakeProvider(MetadataProviderPlugin):
    """In-memory ``MetadataProviderPlugin`` — no network, fully configurable."""

    def __init__(
        self,
        results: Optional[dict] = None,
        rate_limit: tuple[int, int] = (0, 0),
        raise_for: Optional[set] = None,
        on_call=None,
    ) -> None:
        self._results = results or {}
        self._rate_limit = rate_limit
        self._raise_for = raise_for or set()
        self._on_call = on_call
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def display_name(self) -> str:
        return "Fake Provider"

    @property
    def supported_media_types(self) -> list[str]:
        return ["movie", "series"]

    @property
    def supported_fields(self) -> list[str]:
        return ["title", "plot"]

    async def search(self, title: str, year: Optional[int] = None, media_type: str = "movie"):
        return []

    async def get_details(self, external_id: str, media_type: str = "movie"):
        self.calls.append(external_id)
        if self._on_call:
            self._on_call(external_id)
        if external_id in self._raise_for:
            raise RuntimeError("simulated provider failure")
        title = self._results.get(external_id)
        if title is None:
            return None
        return MetadataResult(title=title, confidence=1.0)

    async def test_connection(self):
        return True, None

    def get_rate_limit(self) -> tuple[int, int]:
        return self._rate_limit


# ---------------------------------------------------------------------------
# 1. Candidate selection — repository level (no queue needed)
# ---------------------------------------------------------------------------


def test_candidates_exclude_fresh_include_stale(db):
    now = datetime.now()
    with db.session_scope() as session:
        _provider(session, "p1")
        never_fetched = _channel(session, "p1", name="Never")
        session.add(MetadataDB(id="meta_fresh", title="Fresh", fetched_at=now))
        fresh = _channel(session, "p1", name="Fresh", metadata_id="meta_fresh")
        session.add(
            MetadataDB(id="meta_stale", title="Stale", fetched_at=now - timedelta(days=100))
        )
        stale = _channel(session, "p1", name="Stale", metadata_id="meta_stale")

    with db.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.select_metadata_enrichment_candidates(
            10, set(), now - timedelta(days=90)
        )
    ids = {r["id"] for r in rows}
    assert ids == {never_fetched, stale}
    assert fresh not in ids


def test_candidates_engaged_channels_ordered_first(db):
    with db.session_scope() as session:
        _provider(session, "p1")
        plain = _channel(session, "p1", name="Plain")
        fav = _channel(session, "p1", name="Fav", is_favorite=True)
        played = _channel(session, "p1", name="Played", play_count=3)
        queued = _channel(session, "p1", name="Queued")
        session.add(WatchQueueDB(
            channel_id=queued, channel_name="Queued", media_type="movie",
            source_id="s1", position=0,
        ))

    with db.session_scope(commit=False) as session:
        rows = RepositoryFactory(session).channels.select_metadata_enrichment_candidates(
            10, set(), datetime.now() - timedelta(days=90)
        )
    ids = [r["id"] for r in rows]
    assert len(ids) == 4
    assert ids[-1] == plain, "the unengaged channel must sort last"
    assert set(ids[:3]) == {fav, played, queued}, "favorited/played/queued sort first"


def test_candidates_exclude_hidden_providers(db):
    with db.session_scope() as session:
        _provider(session, "p1", is_active=True)
        _provider(session, "p2", is_active=False)  # hidden (inactive)
        visible = _channel(session, "p1", name="Visible")
        hidden = _channel(session, "p2", name="Hidden")

    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        excluded = set(repos.providers.get_hidden_provider_ids())
        rows = repos.channels.select_metadata_enrichment_candidates(
            10, excluded, datetime.now() - timedelta(days=90)
        )
    ids = {r["id"] for r in rows}
    assert visible in ids
    assert hidden not in ids


# ---------------------------------------------------------------------------
# 2. Full queue — pause/resume/cancel/failures/throttle/session-hygiene
# ---------------------------------------------------------------------------


def test_pause_stops_further_fetches_resume_continues(db, config_obj, qapp, monkeypatch, make_queue):
    import metatv.core.metadata_enrichment_queue as meq

    monkeypatch.setattr(meq, "_BATCH_SIZE", 2)

    with db.session_scope() as session:
        _provider(session, "p1")
        ids = [_channel(session, "p1", name=f"Movie{i}") for i in range(4)]

    calls: list[str] = []
    holder: dict[str, Any] = {}

    def on_call(cid: str) -> None:
        calls.append(cid)
        if len(calls) == 1:
            holder["queue"].pause()

    provider = _FakeProvider(results={cid: f"T-{cid}" for cid in ids}, on_call=on_call)
    queue = make_queue(provider)
    holder["queue"] = queue

    queue.start()
    _wait_idle(queue)
    paused_status = queue.get_status()
    assert paused_status.state == "paused"
    assert paused_status.done == 1
    assert len(calls) == 1, "pause must stop the batch before the next candidate is fetched"

    queue.resume()
    _wait_idle(queue)
    final_status = queue.get_status()
    assert final_status.state == "finished"
    assert final_status.done == 4
    assert len(calls) == 4
    assert len(set(calls)) == 4, "resume must not re-fetch an already-processed channel"


def test_cancel_stops_worker_and_leaves_none_running(db, config_obj, qapp, make_queue):
    with db.session_scope() as session:
        _provider(session, "p1")
        ids = [_channel(session, "p1", name=f"Movie{i}") for i in range(4)]

    calls: list[str] = []
    holder: dict[str, Any] = {}

    def on_call(cid: str) -> None:
        calls.append(cid)
        if len(calls) == 1:
            holder["queue"].cancel()

    provider = _FakeProvider(results={cid: f"T-{cid}" for cid in ids}, on_call=on_call)
    queue = make_queue(provider)
    holder["queue"] = queue

    queue.start()
    future = queue._worker_future
    assert future is not None
    future.result(timeout=5)  # must return promptly — proves no worker is left running

    status = queue.get_status()
    assert status.state == "cancelled"
    assert status.done == 1
    with queue._lock:
        assert queue._running is False


def test_provider_failure_counted_bounded_and_doesnt_kill_queue(db, config_obj, qapp, make_queue):
    with db.session_scope() as session:
        _provider(session, "p1")
        bad = _channel(session, "p1", name="Bad")
        good = _channel(session, "p1", name="Good")

    provider = _FakeProvider(results={good: "Good Title"}, raise_for={bad})
    queue = make_queue(provider)

    # A single start() drains the WHOLE current work set, not just one batch —
    # _worker_run loops batches until the candidate query goes empty. Since
    # 'bad' stays a candidate after each failed attempt (until it hits the
    # retry cap), one run alone drives it through every attempt up to
    # _MAX_ENRICH_ATTEMPTS. This also proves a raising provider doesn't
    # prevent its batch-sibling 'good' channel from being enriched.
    queue.start()
    _wait_idle(queue)

    status = queue.get_status()
    assert status.failed_count >= 1
    assert any(title == "Bad" for title, _reason in status.recent_failures)

    with db.session_scope(commit=False) as session:
        bad_row = session.query(
            ChannelDB.metadata_enrich_state, ChannelDB.metadata_enrich_attempts
        ).filter_by(id=bad).one()
        good_row = session.query(ChannelDB.metadata_id).filter_by(id=good).one()

    assert bad_row.metadata_enrich_state == "failed"
    assert bad_row.metadata_enrich_attempts == _MAX_ENRICH_ATTEMPTS
    assert good_row.metadata_id is not None, "sibling success must survive the other's exception"

    # One more pass: 'bad' is now permanently excluded — never re-attempted.
    calls_before = len(provider.calls)
    queue.start()
    _wait_idle(queue)
    assert bad not in provider.calls[calls_before:]


def test_rate_limit_spacing_honored_without_real_sleep(db, config_obj, qapp, monkeypatch, make_queue):
    import metatv.core.metadata_enrichment_queue as meq
    import metatv.core.metadata_manager as mm_mod

    with db.session_scope() as session:
        _provider(session, "p1")
        ids = [_channel(session, "p1", name=f"Movie{i}") for i in range(2)]

    provider = _FakeProvider(results={cid: f"T-{cid}" for cid in ids}, rate_limit=(1, 100))
    queue = make_queue(provider)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)  # record, never actually wait

    monkeypatch.setattr(meq.asyncio, "sleep", fake_sleep)

    # MetadataManager itself ALSO builds a per-provider RateLimiter straight off
    # the same get_rate_limit() (metadata_manager.py:_init_rate_limiters) — a
    # second, independent throttle from the one under test here. Its own
    # wait_if_needed() polls real wall-clock time (datetime.now()), which
    # patching asyncio.sleep alone can't fast-forward, so it's neutralized
    # separately — this test is about the QUEUE's spacing, not that one.
    async def _noop_wait(self) -> None:
        return None

    monkeypatch.setattr(mm_mod.RateLimiter, "wait_if_needed", _noop_wait)

    queue.start()
    _wait_idle(queue)

    assert queue.get_status().done == 2
    assert len(sleep_calls) == 1, "only the 2nd of 2 requests should wait on the rate limit"
    assert sleep_calls[0] > 90.0, "the wait must reflect window_seconds / max_requests (~100s)"


def test_no_db_session_open_during_network_await(db, config_obj, qapp, make_queue):
    with db.session_scope() as session:
        _provider(session, "p1")
        ids = [_channel(session, "p1", name=f"Movie{i}") for i in range(3)]

    # Instrument the real seam every DB touch goes through (Database.session_scope)
    # to observe, live, whether a scope is open at the moment a "network" call is
    # in flight — a behavioral assertion through the seam, not a code read.
    open_count = {"n": 0}
    original_scope = db.session_scope

    @contextmanager
    def tracking_scope(*args, **kwargs):
        open_count["n"] += 1
        try:
            with original_scope(*args, **kwargs) as session:
                yield session
        finally:
            open_count["n"] -= 1

    db.session_scope = tracking_scope

    observed: list[int] = []

    def on_call(cid: str) -> None:
        # Runs INSIDE the simulated network call (provider.get_details, awaited
        # by MetadataManager.get_metadata with no session open per its own
        # session-hygiene contract) — captures the seam's live open-count then.
        observed.append(open_count["n"])

    provider = _FakeProvider(results={cid: f"T-{cid}" for cid in ids}, on_call=on_call)
    queue = make_queue(provider)

    queue.start()
    _wait_idle(queue)

    assert queue.get_status().done == 3
    assert len(observed) == 3
    assert all(n == 0 for n in observed), (
        f"a DB session was open during a simulated network call: {observed}"
    )


def test_the_first_request_never_waits_on_an_empty_history(
    db, config_obj, qapp, monkeypatch, make_queue
):
    """Nothing has been requested yet, so there is nothing to space it from.

    ``last_request`` used to start at ``0.0`` while ``time.monotonic()`` counts
    from process start, so the first request computed ``interval - uptime`` and
    slept whenever the process was younger than the interval.

    **The clock is pinned deliberately.** Without it this test inherits the very
    dependency it exists to kill: on a machine where the suite has already run
    for longer than the interval, ``interval - uptime`` is negative and the bug
    cannot show. That is exactly why the spacing test above failed on FAST CI
    shards and passed on slow ones, and why a first attempt at this test passed
    against the unfixed code.
    """
    import metatv.core.metadata_enrichment_queue as meq
    import metatv.core.metadata_manager as mm_mod

    with db.session_scope() as session:
        _provider(session, "p1")
        ids = [_channel(session, "p1", name="OnlyOne")]

    provider = _FakeProvider(results={cid: f"T-{cid}" for cid in ids}, rate_limit=(1, 100))
    queue = make_queue(provider)

    # A young process: 5 seconds up, against a 100-second interval.
    monkeypatch.setattr(meq.time, "monotonic", lambda: 5.0)

    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(meq.asyncio, "sleep", fake_sleep)

    async def _noop_wait(self) -> None:
        return None

    monkeypatch.setattr(mm_mod.RateLimiter, "wait_if_needed", _noop_wait)

    queue.start()
    _wait_idle(queue)

    assert queue.get_status().done == 1
    assert sleep_calls == [], (
        "a single request must not be throttled against a request that never "
        f"happened; slept {sleep_calls}"
    )
