"""SPORT-7/LIVE-1 — the catalog-refresh ticks (metatv/gui/catalog_refresh_tick.py).

``ProviderDB.refresh_schedule`` (manual/launch/daily/weekly/monthly) shipped
in the provider editor with zero readers — the combo saved a value nothing
ever read. This is what finally reads it: ``_maybe_auto_refresh_catalogs``
fires the existing serial refresh queue for every ACTIVE provider whose
schedule says it is due, skipping any provider that is currently streaming.

LIVE-1 adds a second, GLOBAL lane on top: the Sports banner's "Refresh
sources" action, a global auto-rate (Settings -> Content), and opening
Sports/Events all drive a LIVE-ONLY refresh (``kind="live_only"``) — never
the full multi-minute one — through ``_maybe_live_refresh_tick`` /
``_maybe_live_refresh_on_view_open`` / ``_on_sports_refresh_stale_requested``.

Uses a real, file-backed ``Database`` (tmp_path) per CLAUDE.md — no
``:memory:`` — and a minimal host combining the real
``_CatalogRefreshTickMixin`` with fake collaborators (queue manager, player
manager, config) so every tick/hook runs exactly as MainWindow would call it,
synchronously (the fake ``_run_query`` executes ``query_fn`` immediately
against a real session).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from metatv.core.catalog_refresh import (
    BANNER_STALE_THRESHOLD,
    catalog_refresh_due,
    live_refresh_due,
    live_refresh_on_view_open_due,
)
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
    last_live_refresh_at=None,
) -> None:
    session.add(ProviderDB(
        id=provider_id, name=name, type="xtream", url="http://example.com",
        is_active=is_active, urls=[],
        refresh_schedule=refresh_schedule,
        last_catalog_refresh_at=last_catalog_refresh_at,
        last_live_refresh_at=last_live_refresh_at,
    ))
    session.flush()


class _FakeQueueManager:
    """Records enqueue() calls; mirrors RefreshQueueManager's dedup contract.

    ``enqueued`` stays a plain ``(id, name)`` list so every pre-LIVE-1 test
    that asserts against it is untouched; ``enqueued_kinds`` is the LIVE-1
    addition for tests that need to see "full" vs "live_only".
    """

    def __init__(self):
        self.enqueued: list[tuple[str, str]] = []
        self.enqueued_kinds: list[tuple[str, str, str]] = []
        self._queued: set[str] = set()

    def enqueue(self, provider_id: str, provider_name: str, kind: str = "full") -> None:
        self.enqueued.append((provider_id, provider_name))
        self.enqueued_kinds.append((provider_id, provider_name, kind))
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

    def __init__(
        self,
        db: Database,
        streaming_provider_ids: set[str] | None = None,
        live_refresh_mode: str = "manual",
    ):
        self.db = db
        self.refresh_queue_manager = _FakeQueueManager()
        self.player_manager = _FakePlayerManager(streaming_provider_ids)
        # LIVE-1's tick/hook read config.live_refresh_mode; every other
        # method here predates the setting and never touches self.config.
        self.config = SimpleNamespace(live_refresh_mode=live_refresh_mode)

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


# ---------------------------------------------------------------------------
# LIVE-1 — the pure due-ness functions
# ---------------------------------------------------------------------------

def test_live_refresh_due_manual_and_on_view_open_never_fire_from_the_tick():
    """Those two modes are driven by the banner button and the view-open hook
    respectively — the 5-minute interval tick must never fire for them."""
    now = datetime.now()
    stale = now - timedelta(hours=5)
    assert live_refresh_due("manual", stale, now) is False
    assert live_refresh_due("on_view_open", stale, now) is False
    assert live_refresh_due("manual", None, now) is False


def test_live_refresh_due_interval_modes_fire_past_their_interval():
    now = datetime.now()
    assert live_refresh_due("30m", now - timedelta(minutes=29), now) is False
    assert live_refresh_due("30m", now - timedelta(minutes=31), now) is True
    assert live_refresh_due("15m", None, now) is True, (
        "never live-refreshed at all is always due"
    )


def test_live_refresh_on_view_open_due_is_a_five_minute_cooldown():
    now = datetime.now()
    assert live_refresh_on_view_open_due(now - timedelta(minutes=4), now) is False
    assert live_refresh_on_view_open_due(now - timedelta(minutes=6), now) is True
    assert live_refresh_on_view_open_due(None, now) is True


# ---------------------------------------------------------------------------
# LIVE-1 — _mark_catalog_refreshed stamps the right column(s) per kind
# ---------------------------------------------------------------------------

def test_mark_catalog_refreshed_live_only_stamps_only_the_live_column(tmp_path):
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1",
            refresh_schedule="manual", last_catalog_refresh_at=None,
        )

    host = _Host(db)
    host._mark_catalog_refreshed("p1", kind="live_only")

    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="p1").first()
        assert p.last_live_refresh_at is not None
        assert p.last_catalog_refresh_at is None, (
            "live-only must never stamp the FULL catalog-refresh column"
        )


def test_mark_catalog_refreshed_full_stamps_both_columns(tmp_path):
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1",
            refresh_schedule="manual", last_catalog_refresh_at=None,
        )

    host = _Host(db)
    host._mark_catalog_refreshed("p1", kind="full")

    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="p1").first()
        assert p.last_live_refresh_at is not None, (
            "a full refresh includes the live half by definition"
        )
        assert p.last_catalog_refresh_at is not None


def test_mark_catalog_refreshed_without_a_kind_defaults_to_full(tmp_path):
    """The pre-LIVE-1 call shape (main_window_providers.py's existing site
    before it started passing kind) must keep stamping the full column."""
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1",
            refresh_schedule="manual", last_catalog_refresh_at=None,
        )

    host = _Host(db)
    host._mark_catalog_refreshed("p1")

    with db.session_scope(commit=False) as session:
        p = session.query(ProviderDB).filter_by(id="p1").first()
        assert p.last_catalog_refresh_at is not None
        assert p.last_live_refresh_at is not None


def test_mark_catalog_refreshed_noops_on_a_falsy_provider_id(tmp_path):
    db = _make_db(tmp_path)
    host = _Host(db)
    host._mark_catalog_refreshed(None, kind="live_only")  # must not raise


# ---------------------------------------------------------------------------
# LIVE-1 — the Sports banner's "Refresh sources" action enqueues live-only
# ---------------------------------------------------------------------------

def test_banner_refresh_action_enqueues_live_only_for_stale_sources_only(tmp_path):
    """A source whose LIVE refresh is recent must not be re-queued even when
    its FULL refresh is old — the banner's own staleness rule is live-first
    (COALESCE(last_live_refresh_at, last_catalog_refresh_at, ...))."""
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "stale", name="Stale Source", refresh_schedule="manual",
            last_catalog_refresh_at=now - timedelta(hours=27),
        )
        _insert_provider(
            session, "fresh", name="Fresh Live Source", refresh_schedule="manual",
            last_catalog_refresh_at=now - timedelta(hours=27),
            last_live_refresh_at=now - timedelta(minutes=5),
        )

    host = _Host(db)
    host._on_sports_refresh_stale_requested()

    assert host.refresh_queue_manager.enqueued_kinds == [
        ("stale", "Stale Source", "live_only")
    ], host.refresh_queue_manager.enqueued_kinds


def test_banner_refresh_action_ignores_a_fresh_active_corpus(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(hours=1),
        )
    assert timedelta(hours=1) < BANNER_STALE_THRESHOLD

    host = _Host(db)
    host._on_sports_refresh_stale_requested()
    assert host.refresh_queue_manager.enqueued == []


# ---------------------------------------------------------------------------
# LIVE-1 — the 5-minute interval lane
# ---------------------------------------------------------------------------

def test_live_refresh_tick_enqueues_live_only_when_past_the_configured_interval(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(minutes=31),
        )

    host = _Host(db, live_refresh_mode="30m")
    host._maybe_live_refresh_tick()

    assert host.refresh_queue_manager.enqueued_kinds == [("p1", "P1", "live_only")]


def test_live_refresh_tick_does_not_fire_within_the_interval(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(minutes=10),
        )

    host = _Host(db, live_refresh_mode="30m")
    host._maybe_live_refresh_tick()

    assert host.refresh_queue_manager.enqueued == []


def test_live_refresh_tick_fires_nothing_in_manual_or_on_view_open_mode(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(hours=5),  # very stale
        )

    for mode in ("manual", "on_view_open"):
        host = _Host(db, live_refresh_mode=mode)
        host._maybe_live_refresh_tick()
        assert host.refresh_queue_manager.enqueued == [], mode


def test_live_refresh_tick_skips_a_currently_streaming_source(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(hours=1),
        )

    host = _Host(db, streaming_provider_ids={"p1"}, live_refresh_mode="30m")
    host._maybe_live_refresh_tick()

    assert host.refresh_queue_manager.enqueued == [], (
        "a streaming source must be skipped, not enqueued — retried next tick"
    )


def test_live_refresh_tick_ignores_inactive_providers(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "off", name="Disabled", refresh_schedule="manual",
            last_catalog_refresh_at=None, is_active=False,
            last_live_refresh_at=now - timedelta(hours=5),
        )

    host = _Host(db, live_refresh_mode="30m")
    host._maybe_live_refresh_tick()

    assert host.refresh_queue_manager.enqueued == []


def test_live_refresh_tick_already_queued_is_not_re_enqueued(tmp_path):
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
            last_live_refresh_at=now - timedelta(minutes=31),
        )

    host = _Host(db, live_refresh_mode="30m")
    host.refresh_queue_manager.enqueue("p1", "P1", kind="live_only")  # already in flight
    host._maybe_live_refresh_tick()

    assert host.refresh_queue_manager.enqueued_kinds == [("p1", "P1", "live_only")], (
        "already queued/running must not be enqueued a second time"
    )


# ---------------------------------------------------------------------------
# LIVE-1 — opening Sports or Events, shared cooldown
# ---------------------------------------------------------------------------

def test_on_view_open_sports_then_events_share_one_cooldown(tmp_path):
    """The owner's own scenario: opening Sports fires (never live-refreshed);
    opening Events 1 minute later does NOT (shared 5-minute cooldown);
    opening Events 6 minutes later fires again. Both views call the SAME
    host method — there is nothing per-view to keep in sync."""
    db = _make_db(tmp_path)
    now = datetime.now()
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
        )

    host = _Host(db, live_refresh_mode="on_view_open")

    # "Sports opens."
    host._maybe_live_refresh_on_view_open()
    assert host.refresh_queue_manager.enqueued_kinds == [("p1", "P1", "live_only")]

    # The refresh's own success stamp (what _mark_catalog_refreshed would do),
    # plus resetting the queue bookkeeping so the NEXT call is judged on the
    # cooldown rather than the ordinary already-queued dedupe.
    host.refresh_queue_manager.enqueued.clear()
    host.refresh_queue_manager.enqueued_kinds.clear()
    host.refresh_queue_manager._queued.clear()

    # "Events opens" 1 minute later.
    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id="p1").first()
        p.last_live_refresh_at = now - timedelta(minutes=1)
    host._maybe_live_refresh_on_view_open()
    assert host.refresh_queue_manager.enqueued == [], (
        "Events opening inside the shared cooldown window must not re-fire"
    )

    # "Events opens" 6 minutes later.
    with db.session_scope() as session:
        p = session.query(ProviderDB).filter_by(id="p1").first()
        p.last_live_refresh_at = now - timedelta(minutes=6)
    host._maybe_live_refresh_on_view_open()
    assert host.refresh_queue_manager.enqueued_kinds == [("p1", "P1", "live_only")]


def test_on_view_open_does_nothing_outside_on_view_open_mode(tmp_path):
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
        )

    for mode in ("manual", "15m", "30m", "1h", "3h"):
        host = _Host(db, live_refresh_mode=mode)
        host._maybe_live_refresh_on_view_open()
        assert host.refresh_queue_manager.enqueued == [], mode


def test_on_view_open_skips_a_currently_streaming_source(tmp_path):
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "p1", name="P1", refresh_schedule="manual",
            last_catalog_refresh_at=None,
        )

    host = _Host(db, streaming_provider_ids={"p1"}, live_refresh_mode="on_view_open")
    host._maybe_live_refresh_on_view_open()

    assert host.refresh_queue_manager.enqueued == []


def test_on_view_open_ignores_inactive_providers(tmp_path):
    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(
            session, "off", name="Disabled", refresh_schedule="manual",
            last_catalog_refresh_at=None, is_active=False,
        )

    host = _Host(db, live_refresh_mode="on_view_open")
    host._maybe_live_refresh_on_view_open()

    assert host.refresh_queue_manager.enqueued == []
