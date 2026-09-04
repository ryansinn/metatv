"""SPORT-7/LIVE-1 — the catalog-refresh ticks and the live-refresh lane.

``_CatalogRefreshTickMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases), same shape as every other ``main_window_*.py``
mixin: its methods read/write ``self.*`` attributes MainWindow's
``__init__``/``setup_ui`` already establish (``self.db``, ``self._run_query``,
``self.refresh_queue_manager``, ``self.player_manager``, ``self.config``).

Split out of ``main_window_providers.py`` rather than added there because that
file is baseline-pinned at its debt-ratchet ceiling
(``tests/code_health_baseline.json``) — CLAUDE.md: "a pinned file at its
ceiling means extract to a cohesive new module, not rebaseline." Only a
single delegating call (``self._mark_catalog_refreshed(provider_id, kind)``)
lives in ``_ProviderMixin._on_queue_refresh_finished``; everything else is
here.

Two ticks live here:

* SPORT-7's hourly full-catalog tick (``_maybe_auto_refresh_catalogs``) — a
  per-source opt-in ``refresh_schedule``, unchanged by LIVE-1.
* LIVE-1's 5-minute live-only lane (``_maybe_live_refresh_tick``) — a single
  GLOBAL ``config.live_refresh_mode`` setting, always enqueuing
  ``kind="live_only"`` rather than the full multi-minute refresh.

The Sports and Events views that used to trigger ``_on_sports_refresh_stale_requested``
and ``_maybe_live_refresh_on_view_open`` on open/refresh-click were retired
(owner direction: live sports channels stay in search/browse, wearing the
live flag, rather than a dedicated surface). Both hooks are kept — they are
general live-refresh infrastructure, not view-specific — but neither has a
live caller today; ``config.live_refresh_mode == "on_view_open"`` is
consequently dormant until something else wires a trigger to them.

Every due-ness decision is a pure function in ``core/catalog_refresh.py`` —
this module is orchestration only (offloading the DB read, resolving
currently-streaming providers, calling ``refresh_queue_manager.enqueue``),
per DR-0007 (engine <- control <- view).
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QTimer
from loguru import logger

from metatv.core.catalog_refresh import (
    BANNER_STALE_THRESHOLD,
    LIVE_REFRESH_INTERVALS,
    catalog_refresh_due,
    live_refresh_due,
    live_refresh_on_view_open_due,
)
from metatv.core.repositories import RepositoryFactory

#: Hourly tick interval, in milliseconds — see _maybe_auto_refresh_catalogs.
CATALOG_REFRESH_TICK_MS = 60 * 60 * 1000

#: LIVE-1's live-refresh lane tick interval, in milliseconds. Much finer than
#: the hourly full-catalog tick above: the shortest interval mode is 15
#: minutes, so an hourly granularity would miss it entirely.
LIVE_REFRESH_TICK_MS = 5 * 60 * 1000


class _CatalogRefreshTickMixin:
    """Fires the existing serial refresh queue from a source's opted-in
    ``refresh_schedule`` (SPORT-7) and from the global live-refresh rate
    (LIVE-1).
    """

    def _init_catalog_refresh_tick(self) -> None:
        """Construct both auto-refresh QTimers and register their cleanup.

        Called once from ``MainWindow.__init__``, after ``refresh_queue_manager``
        exists. The one-time launch check is a separate ``QTimer.singleShot``
        in ``_start_deferred_fetches`` (needs channels loaded first).
        """
        self._catalog_refresh_timer = QTimer(self)
        self._catalog_refresh_timer.timeout.connect(
            lambda: self._maybe_auto_refresh_catalogs(at_launch=False)
        )
        self._catalog_refresh_timer.start(CATALOG_REFRESH_TICK_MS)
        self._register_cleanable(
            "catalog_refresh_timer", self._catalog_refresh_timer.stop
        )

        # LIVE-1's live-refresh lane — finer granularity than the hourly tick
        # above because its shortest interval mode is 15 minutes.
        self._live_refresh_timer = QTimer(self)
        self._live_refresh_timer.timeout.connect(self._maybe_live_refresh_tick)
        self._live_refresh_timer.start(LIVE_REFRESH_TICK_MS)
        self._register_cleanable(
            "live_refresh_timer", self._live_refresh_timer.stop
        )

    def _mark_catalog_refreshed(self, provider_id: str | None, kind: str = "full") -> None:
        """Stamp the refresh timestamp(s) on a SUCCESSFUL refresh (SPORT-7/LIVE-1).

        ``kind="live_only"`` stamps only ``last_live_refresh_at``;
        ``kind="full"`` (default) stamps BOTH ``last_live_refresh_at`` and
        ``last_catalog_refresh_at`` — a full refresh includes the live half
        by definition. Called only from
        ``_ProviderMixin._on_queue_refresh_finished``'s success branch — never
        on failure, so a source that just failed a refresh isn't treated as
        freshly current by either tick or the banner. No-ops on a falsy
        *provider_id* (defensive; the queue manager always supplies one).
        """
        if not provider_id:
            return
        with self.db.session_scope() as session:
            repo = RepositoryFactory(session).providers
            repo.mark_live_refreshed(provider_id)
            if kind == "full":
                repo.mark_catalog_refreshed(provider_id)

    def _currently_streaming_provider_ids(self) -> set[str]:
        """provider_ids with a live mpv instance right now.

        The refresh path is not enrolled in ``ConnectionAccountant``, so
        taking a one-connection provider's slot mid-stream would kill
        playback — a provider in this set is skipped by the tick and simply
        retried on the next pass.
        """
        player_manager = self.__dict__.get("player_manager")
        if player_manager is None:
            return set()
        ids: set[str] = set()
        for key in player_manager.active_keys():
            provider_id = player_manager.provider_for_key(key)
            if provider_id:
                ids.add(provider_id)
        return ids

    def _maybe_auto_refresh_catalogs(self, *, at_launch: bool) -> None:
        """The SPORT-7 tick: enqueue every ACTIVE provider whose
        ``refresh_schedule`` says a catalog refresh is due right now.

        Called from an hourly ``QTimer`` (``at_launch=False``, wired in
        ``main_window.py``) and once at launch (``at_launch=True``, from
        ``_start_deferred_fetches``) — see
        :func:`metatv.core.catalog_refresh.catalog_refresh_due` for the
        due-ness rule, including why "On App Launch" fires only from the
        launch call. Always a BULK COMPLETE source refresh through
        ``refresh_queue_manager.enqueue`` — never per-category polling
        (owner, 2026-09-03) — and never a provider that is CURRENTLY
        STREAMING (see :meth:`_currently_streaming_provider_ids`).
        """
        def query(repos):
            return repos.providers.get_active_providers_with_refresh_schedule()

        def on_result(rows) -> None:
            if not rows or not hasattr(self, "refresh_queue_manager"):
                return
            now = datetime.now()
            streaming = self._currently_streaming_provider_ids()
            for provider_id, name, schedule, effective in rows:
                if not catalog_refresh_due(schedule, effective, now, at_launch=at_launch):
                    continue
                if provider_id in streaming:
                    logger.info(
                        "catalog auto-refresh: skipping {!r} — currently streaming", name,
                    )
                    continue
                if self.refresh_queue_manager.is_queued_or_running(provider_id):
                    continue
                logger.info(
                    "catalog auto-refresh: enqueuing {!r} (schedule={!r}, last refresh {})",
                    name, schedule, effective,
                )
                self.refresh_queue_manager.enqueue(provider_id, name, kind="full")

        self._run_query(query, on_result, on_error=lambda exc: None)

    def _on_sports_refresh_stale_requested(self) -> None:
        """Enqueue a LIVE-ONLY refresh (LIVE-1) for every active, stale source
        — not the full multi-minute catalog refresh. Measured on the owner's
        two sources: ``get_live_streams`` alone returns the complete live
        catalog in ~1.6-3.9s, so a "refresh stale sources" button only pays
        for that single call.

        Formerly wired to ``SportsView.refreshSourcesRequested`` (a banner
        button on the now-retired Sports view). Kept as general live-refresh
        infrastructure — it never reached into ``refresh_queue_manager``
        itself (engine <- control <- view, DR-0007), it resolves "stale" via
        the same live-first COALESCE rule the (also retired) banner's age
        display used (``ProviderRepository._effective_live_refresh``) — but it
        currently has no caller.
        """
        with self.db.session_scope(commit=False) as session:
            stale = RepositoryFactory(session).providers.get_stale_active_providers(
                BANNER_STALE_THRESHOLD
            )
        if not hasattr(self, "refresh_queue_manager"):
            return
        for provider_id, name in stale:
            self.refresh_queue_manager.enqueue(provider_id, name, kind="live_only")

    def _maybe_live_refresh_tick(self) -> None:
        """LIVE-1's 5-minute lane: enqueue a live-only refresh for every
        ACTIVE provider when ``config.live_refresh_mode`` is an interval
        ("15m"/"30m"/"1h"/"3h") and that provider's ``last_live_refresh_at``
        is older than it. "manual" and "on_view_open" never fire from here.
        """
        mode = getattr(self.config, "live_refresh_mode", "manual")
        if mode not in LIVE_REFRESH_INTERVALS:
            return
        now = datetime.now()

        def query(repos):
            return repos.providers.get_active_providers_live_refresh()

        def on_result(rows) -> None:
            self._enqueue_due_live_sources(
                rows, lambda last: live_refresh_due(mode, last, now)
            )

        self._run_query(query, on_result, on_error=lambda exc: None)

    def _maybe_live_refresh_on_view_open(self) -> None:
        """LIVE-1: enqueue a live-only refresh for every ACTIVE, due provider
        when ``config.live_refresh_mode == "on_view_open"``.

        Formerly wired to ``SportsView.on_activate`` / ``EventsView.on_activate``
        (they covered overlapping content, so either opening could trigger it
        — owner) via a shared 5-minute cooldown against ``last_live_refresh_at``
        so rapid tab-switching between the two views would not hammer the API.
        Both views were retired; this method is kept as general live-refresh
        infrastructure (not view-specific) but currently has no caller, so
        ``"on_view_open"`` mode is dormant until something else wires a
        trigger to it.
        """
        if getattr(self.config, "live_refresh_mode", "manual") != "on_view_open":
            return
        now = datetime.now()

        def query(repos):
            return repos.providers.get_active_providers_live_refresh()

        def on_result(rows) -> None:
            self._enqueue_due_live_sources(
                rows, lambda last: live_refresh_on_view_open_due(last, now)
            )

        self._run_query(query, on_result, on_error=lambda exc: None)

    def _enqueue_due_live_sources(self, rows, is_due) -> None:
        """Shared enqueue loop for the live-refresh lane and the on-view-open
        hook: skip currently-streaming and already-queued/running sources,
        enqueue ``kind="live_only"`` for the rest.

        Args:
            rows: ``(provider_id, name, last_live_refresh_at)`` tuples from
                ``get_active_providers_live_refresh``.
            is_due: Callable taking ``last_live_refresh_at`` and returning
                whether that provider is due right now — the two callers
                supply ``live_refresh_due``/``live_refresh_on_view_open_due``
                pre-bound to their own mode/cooldown.
        """
        if not rows or not hasattr(self, "refresh_queue_manager"):
            return
        streaming = self._currently_streaming_provider_ids()
        for provider_id, name, last_live in rows:
            if not is_due(last_live):
                continue
            if provider_id in streaming:
                logger.info(
                    "live-refresh: skipping {!r} — currently streaming", name,
                )
                continue
            if self.refresh_queue_manager.is_queued_or_running(provider_id):
                continue
            logger.info("live-refresh: enqueuing {!r} (live-only)", name)
            self.refresh_queue_manager.enqueue(provider_id, name, kind="live_only")
