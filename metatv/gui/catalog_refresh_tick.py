"""SPORT-7 — the catalog-refresh tick and the Sports view's "Refresh sources" action.

``_CatalogRefreshTickMixin`` is mixed into :class:`~metatv.gui.main_window.MainWindow`
(main_window.py's class bases), same shape as every other ``main_window_*.py``
mixin: its methods read/write ``self.*`` attributes MainWindow's
``__init__``/``setup_ui`` already establish (``self.db``, ``self._run_query``,
``self.refresh_queue_manager``, ``self.player_manager``).

Split out of ``main_window_providers.py`` rather than added there because that
file is baseline-pinned at its debt-ratchet ceiling
(``tests/code_health_baseline.json``) — CLAUDE.md: "a pinned file at its
ceiling means extract to a cohesive new module, not rebaseline." Only a
single delegating call (``self._mark_catalog_refreshed(provider_id)``) lives
in ``_ProviderMixin._on_queue_refresh_finished``; everything else is here.

The due-ness decision itself is the pure ``catalog_refresh_due`` function in
``core/catalog_refresh.py`` — this module is orchestration only (offloading
the DB read, resolving currently-streaming providers, calling
``refresh_queue_manager.enqueue``), per DR-0007 (engine <- control <- view).
"""

from __future__ import annotations

from datetime import datetime

from PyQt6.QtCore import QTimer
from loguru import logger

from metatv.core.catalog_refresh import BANNER_STALE_THRESHOLD, catalog_refresh_due
from metatv.core.repositories import RepositoryFactory

#: Hourly tick interval, in milliseconds — see _maybe_auto_refresh_catalogs.
CATALOG_REFRESH_TICK_MS = 60 * 60 * 1000


class _CatalogRefreshTickMixin:
    """Fires the existing serial refresh queue from a source's opted-in
    ``refresh_schedule``, and serves the Sports view's staleness-banner action.
    """

    def _init_catalog_refresh_tick(self) -> None:
        """Construct the hourly QTimer and register its cleanup.

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

    def _wire_sports_catalog_banner(self) -> None:
        """Connect ``SportsView``'s refresh-stale signal and queue-busy flag.

        Called once from ``MainWindow.setup_ui``, right after ``sports_view``
        is constructed.
        """
        self.sports_view.refreshSourcesRequested.connect(
            self._on_sports_refresh_stale_requested
        )
        self.refresh_queue_manager.queue_changed.connect(
            lambda queue: self.sports_view.set_refresh_pending(bool(queue))
        )

    def _mark_catalog_refreshed(self, provider_id: str | None) -> None:
        """Stamp ``last_catalog_refresh_at`` on a SUCCESSFUL catalog refresh.

        Called only from ``_ProviderMixin._on_queue_refresh_finished``'s
        success branch — never on failure, so a source that just failed a
        refresh isn't treated as freshly current by the tick or the banner.
        No-ops on a falsy *provider_id* (defensive; the queue manager always
        supplies one).
        """
        if not provider_id:
            return
        with self.db.session_scope() as session:
            RepositoryFactory(session).providers.mark_catalog_refreshed(provider_id)

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
                self.refresh_queue_manager.enqueue(provider_id, name)

        self._run_query(query, on_result, on_error=lambda exc: None)

    def _on_sports_refresh_stale_requested(self) -> None:
        """``SportsView.refreshSourcesRequested`` -> enqueue every active,
        stale source through the same queue Sources' "Refresh All" uses
        (``refresh_queue_manager.enqueue``, see
        ``main_window_providers.refresh_all_providers``).

        The view never reaches into ``refresh_queue_manager`` itself (engine
        <- control <- view, DR-0007); it asks the host, which resolves
        "stale" the same COALESCE rule the banner itself uses.
        """
        with self.db.session_scope(commit=False) as session:
            stale = RepositoryFactory(session).providers.get_stale_active_providers(
                BANNER_STALE_THRESHOLD
            )
        if not hasattr(self, "refresh_queue_manager"):
            return
        for provider_id, name in stale:
            self.refresh_queue_manager.enqueue(provider_id, name)
