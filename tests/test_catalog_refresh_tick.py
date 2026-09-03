"""SPORT-7 — the catalog-refresh tick (metatv/gui/catalog_refresh_tick.py).

``ProviderDB.refresh_schedule`` (manual/launch/daily/weekly/monthly) shipped
in the provider editor with zero readers — the combo saved a value nothing
ever read. This is what finally reads it: ``_maybe_auto_refresh_catalogs``
fires the existing serial refresh queue for every ACTIVE provider whose
schedule says it is due, skipping any provider that is currently streaming.

Uses a real, file-backed ``Database`` (tmp_path) per CLAUDE.md — no
``:memory:`` — and a minimal host combining the real
``_CatalogRefreshTickMixin`` with fake collaborators (queue manager, player
manager) so ``_maybe_auto_refresh_catalogs`` runs exactly as MainWindow would
call it, synchronously (the fake ``_run_query`` executes ``query_fn``
immediately against a real session).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from metatv.core.catalog_refresh import catalog_refresh_due
from metatv.core.database import Database, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui.catalog_refresh_tick import _CatalogRefreshTickMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path) -> Database:
    db = Database(f"sqlite:///{tmp_path / 'catalog_refresh.db'}")
    db.create_tables()
    return db


def _insert_provider(
    session,
    provider_id: str,
    *,
    name: str,
    refresh_schedule: str,
    last_catalog_refresh_at,
    is_active: bool = True,
) -> None:
    session.add(ProviderDB(
        id=provider_id, name=name, type="xtream", url="http://example.com",
        is_active=is_active, urls=[],
        refresh_schedule=refresh_schedule,
        last_catalog_refresh_at=last_catalog_refresh_at,
    ))
    session.flush()


class _FakeQueueManager:
    """Records enqueue() calls; mirrors RefreshQueueManager's dedup contract."""

    def __init__(self):
        self.enqueued: list[tuple[str, str]] = []
        self._queued: set[str] = set()

    def enqueue(self, provider_id: str, provider_name: str) -> None:
        self.enqueued.append((provider_id, provider_name))
        self._queued.add(provider_id)

    def is_queued_or_running(self, provider_id: str) -> bool:
        return provider_id in self._queued


class _FakePlayerManager:
    """Mirrors the two PlayerManager methods the tick reads: active_keys() /
    provider_for_key()."""

    def __init__(self, streaming_provider_ids: set[str] | None = None):
        self._active = {pid: pid for pid in (streaming_provider_ids or set())}

    def active_keys(self) -> list[str]:
        return list(self._active.keys())

    def provider_for_key(self, key: str | None) -> str | None:
        return self._active.get(key)


class _Host(_CatalogRefreshTickMixin):
    """The real mixin, driven synchronously — no Qt, no MainWindow.__init__."""

    def __init__(self, db: Database, streaming_provider_ids: set[str] | None = None):
        self.db = db
        self.refresh_queue_manager = _FakeQueueManager()
        self.player_manager = _FakePlayerManager(streaming_provider_ids)

    def _run_query(self, query_fn, on_result, *, token_ref=None, on_error=None):
        with self.db.session_scope(commit=False) as session:
            on_result(query_fn(RepositoryFactory(session)))


# ---------------------------------------------------------------------------
# The pure due-ness function
# ---------------------------------------------------------------------------

def test_manual_never_fires_even_when_extremely_stale():
    """The owner's own configuration: Manual means the button only."""
    now = datetime.now()
    stale = now - timedelta(hours=27)
    assert catalog_refresh_due("manual", stale, now, at_launch=False) is False
    assert catalog_refresh_due("manual", stale, now, at_launch=True) is False
    assert catalog_refresh_due("manual", None, now, at_launch=False) is False


def test_daily_fires_only_past_24h():
    now = datetime.now()
    assert catalog_refresh_due("daily", now - timedelta(hours=23), now, at_launch=False) is False
    assert catalog_refresh_due("daily", now - timedelta(hours=25), now, at_launch=False) is True


def test_launch_fires_only_at_launch_regardless_of_staleness():
    now = datetime.now()
    fresh = now - timedelta(minutes=1)
    assert catalog_refresh_due("launch", fresh, now, at_launch=True) is True
    assert catalog_refresh_due("launch", fresh, now, at_launch=False) is False


def test_never_refreshed_is_always_due_for_an_opted_in_schedule():
    now = datetime.now()
    assert catalog_refresh_due("weekly", None, now, at_launch=False) is True


# ---------------------------------------------------------------------------
# The tick — real DB, real mixin, fake queue/player manager
# ---------------------------------------------------------------------------

def test_the_tick_enqueues_due_skips_manual_and_skips_streaming(tmp_path):
    """The three-provider scenario: one due, one manual (never), one due but
    currently streaming (skipped, retried next tick)."""
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "due", name="Due Sports Source",
            refresh_schedule="daily", last_catalog_refresh_at=now - timedelta(hours=25),
        )
        _insert_provider(
            session, "manual", name="Manual Movie Source",
            refresh_schedule="manual", last_catalog_refresh_at=now - timedelta(hours=27),
        )
        _insert_provider(
            session, "streaming", name="Currently Streaming Source",
            refresh_schedule="daily", last_catalog_refresh_at=now - timedelta(hours=25),
        )

    host = _Host(db, streaming_provider_ids={"streaming"})
    host._maybe_auto_refresh_catalogs(at_launch=False)

    assert host.refresh_queue_manager.enqueued == [("due", "Due Sports Source")], (
        host.refresh_queue_manager.enqueued
    )


def test_launch_schedule_only_fires_from_the_launch_call(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "launch-src", name="Launch Source",
            refresh_schedule="launch", last_catalog_refresh_at=now - timedelta(minutes=1),
        )

    host = _Host(db)
    host._maybe_auto_refresh_catalogs(at_launch=False)
    assert host.refresh_queue_manager.enqueued == [], (
        "'launch' must not fire on the hourly tick"
    )

    host._maybe_auto_refresh_catalogs(at_launch=True)
    assert host.refresh_queue_manager.enqueued == [("launch-src", "Launch Source")]


def test_a_provider_already_queued_is_not_re_enqueued(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "due", name="Due Source",
            refresh_schedule="daily", last_catalog_refresh_at=now - timedelta(hours=25),
        )

    host = _Host(db)
    host.refresh_queue_manager.enqueue("due", "Due Source")  # already in flight
    host._maybe_auto_refresh_catalogs(at_launch=False)

    assert host.refresh_queue_manager.enqueued == [("due", "Due Source")], (
        "a provider already queued/running must not be enqueued a second time"
    )


def test_an_inactive_provider_is_never_a_tick_candidate(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "off", name="Disabled Source",
            refresh_schedule="daily", last_catalog_refresh_at=now - timedelta(hours=48),
            is_active=False,
        )

    host = _Host(db)
    host._maybe_auto_refresh_catalogs(at_launch=False)
    assert host.refresh_queue_manager.enqueued == []


def test_success_stamp_feeds_the_next_ticks_effective_refresh(tmp_path):
    """mark_catalog_refreshed's stamp is what the tick reads back — proves the
    two ends (stamp write, tick read) actually agree on the column."""
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1",
            refresh_schedule="daily", last_catalog_refresh_at=now - timedelta(hours=25),
        )

    host = _Host(db)
    host._maybe_auto_refresh_catalogs(at_launch=False)
    assert host.refresh_queue_manager.enqueued == [("p1", "P1")]

    host._mark_catalog_refreshed("p1")
    host.refresh_queue_manager.enqueued.clear()
    host.refresh_queue_manager._queued.clear()

    host._maybe_auto_refresh_catalogs(at_launch=False)
    assert host.refresh_queue_manager.enqueued == [], (
        "the fresh stamp must make the provider no longer due"
    )
