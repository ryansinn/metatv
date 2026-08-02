"""MetadataEnrichmentQueue — background, queue-based metadata enrichment for the library.

ROADMAP.md: "Background metadata enrichment: queue-based async fetching for entire
library with progress tracking." Until this, ``MetadataManager.get_metadata()`` was
strictly on-demand — called only when the user selected a channel. Nothing proactively
filled the library, so most of a large catalog stayed posterless/plot-less until
individually clicked.

Design (mirrors ``tmdb_enrichment_manager.py`` — read that file first)
------------------------------------------------------------------------
* **Single worker.** One ``ThreadPoolExecutor(max_workers=1)`` — never parallel;
  SQLite is a single writer and ``MetadataManager`` already rate-limits per
  provider, so concurrent fetches would only contend, not go faster.
* **Drives the existing ``MetadataManager`` — does not reimplement it.** Each
  candidate is fetched via ``await self.metadata_manager.get_metadata(channel_id,
  force_refresh=True)``. That single call already does the session-hygiene split
  this codebase requires (read in a session that closes BEFORE any network call,
  write in a new session AFTER every provider call returns — see
  ``metadata_manager.py:143-151``); this queue's own DB touches (fetching a batch,
  recording success/failure) follow the identical discipline: read in
  ``_fetch_batch`` (session closed before ``_run_batch_async`` runs), write in
  ``_handle_success``/``_handle_failure`` (a new session opened only AFTER the
  ``await get_metadata(...)`` above has returned). **No session is ever open
  across a network await.**
* **Work set = SQL, not Python.** ``ChannelRepository.select_metadata_enrichment_candidates``
  resolves "needs enrichment" (no cached metadata, or cached metadata older than
  ``config.metadata_old_content_ttl_days``) and the engaged-first ordering
  (favorited / queued / played channels before the rest) entirely in the query —
  see that method's docstring for the exact predicate.
* **Resumable by construction, no separate position table.** A channel drops out
  of the candidate query the moment its metadata is freshly written (or it hits
  the bounded-retry cap and is marked ``'failed'``) — so pausing, cancelling, or
  even quitting the app and relaunching never re-crawls already-done work; the
  DB state itself *is* the position.
* **Defers to Migration Center.** ``_defer_for_migration`` is the same
  ``MigrationManager.is_running`` poll as ``TmdbEnrichmentManager`` uses, for the
  identical reason: two single-worker bulk writers must never race SQLite's
  writer lock (owner log 2026-08-01, docs/CRITICAL_RULES.md).
* **Bounded retries, visible failures.** A channel whose fetch fails is counted
  (``EnrichmentStatus.failed_count``), logged with a reason, and emitted via
  ``enrichment_failed`` — never silently dropped. After
  ``_MAX_ENRICH_ATTEMPTS`` consecutive failures the channel is marked
  ``metadata_enrich_state='failed'`` and permanently excluded from future runs
  (see ``ChannelRepository.record_metadata_enrich_failure``).
* **Auto-start is opt-in.** ``config.metadata_background_refresh`` (default
  ``False``) gates whether ``MainWindow`` calls ``start()`` automatically on
  launch — it does not gate manual start from the Tools view; a user can always
  run a pass on demand regardless of the launch toggle.
"""

from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.metadata_manager import MetadataManager
    from metatv.core.migration_manager import MigrationManager


# One drain batch: candidates resolved (read) then fetched (network) per iteration.
_BATCH_SIZE = 25

# Bounded retries — a channel that fails this many consecutive times is marked
# 'failed' and permanently excluded from future candidate queries (never retried
# forever against a dead/absent provider entry).
_MAX_ENRICH_ATTEMPTS = 3

# Recent-failures ring kept for the status snapshot (UI "count + reason" surface).
_MAX_FAILURE_LOG = 20

# Migration-defer tuning — identical contract to TmdbEnrichmentManager's (see that
# file's module docstring): this manager yields its single-worker turn to a
# running Migration Center pass rather than race its batched commits.
_MIGRATION_DEFER_POLL_S = 1.0
_MIGRATION_DEFER_MAX_WAIT_S = 600.0  # 10 min ceiling — courtesy, not a hard guarantee


@dataclass(frozen=True)
class EnrichmentStatus:
    """Point-in-time snapshot of the queue — safe to read from the main thread.

    Returned by :meth:`MetadataEnrichmentQueue.get_status`, a plain lock-guarded
    attribute read (no DB query). A view calls it on ``on_activate()`` to render
    the CURRENT state immediately (a pass may already be mid-flight from a prior
    session or an auto-start), then tracks live updates via the
    ``progress_changed`` / ``state_changed`` / ``enrichment_failed`` signals.
    """

    state: str  # "idle" | "running" | "paused" | "cancelled" | "finished"
    done: int
    total: int
    current_title: str
    failed_count: int
    recent_failures: tuple[tuple[str, str], ...]  # (title, reason), most recent last


class MetadataEnrichmentQueue(QObject):
    """Background, queue-based metadata enrichment for the whole library.

    Signals
    -------
    progress_changed(done: int, total: int, current_title: str)
        Emitted after every processed candidate (success or failure).
    state_changed(state: str)
        Emitted whenever the run transitions — "running" / "paused" /
        "cancelled" / "finished". Never "idle" (that is only the pre-``start()``
        default, read via :meth:`get_status`, not emitted).
    enrichment_failed(title: str, reason: str)
        Emitted for every failed candidate, in addition to being folded into
        the ``recent_failures`` ring on the status snapshot — failures are
        surfaced, never swallowed.
    """

    progress_changed = pyqtSignal(int, int, str)
    state_changed = pyqtSignal(str)
    enrichment_failed = pyqtSignal(str, str)

    def __init__(
        self,
        db: "Database",
        config: "Config",
        metadata_manager: "MetadataManager",
        parent=None,
        migration_manager: "MigrationManager | None" = None,
    ) -> None:
        """
        Args:
            db: Database handle (worker uses ``session_scope``).
            config: Application config — reads ``metadata_old_content_ttl_days``
                for the staleness cutoff each drain.
            metadata_manager: The app's existing ``MetadataManager`` instance
                (already wired with the registered metadata providers) — this
                queue drives it, it does not construct its own.
            parent: Qt parent (keeps the QObject on the main thread so its
                signals auto-queue back onto it).
            migration_manager: Optional ``MigrationManager`` this manager polls
                (``.is_running``) before each batch read, so a drain yields to a
                running Migration Center pass instead of racing its batched
                commits. ``None`` (default) disables the check.
        """
        super().__init__(parent)
        self.db = db
        self.config = config
        self.metadata_manager = metadata_manager
        self._migration_manager = migration_manager
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="metadata_enrich"
        )
        self._lock = threading.Lock()

        self._running = False
        self._paused = False
        self._cancelled = False
        self._shutdown = False
        self._state = "idle"

        self._done = 0
        self._failed = 0
        self._total: Optional[int] = None
        self._current_title = ""
        self._failure_log: list[tuple[str, str]] = []

        self._worker_future: Optional[Future] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Begin a fresh enrichment pass. A no-op while a pass is already running."""
        self._kick(reset=True)

    def resume(self) -> None:
        """Resume a paused pass from the saved position — no reset.

        "Saved position" is structural, not a separate cursor: an already-done
        channel no longer matches the candidate query (see module docstring), so
        the next drain batch naturally continues where the last one left off.
        """
        self._kick(reset=False)

    def _kick(self, *, reset: bool) -> None:
        if self._shutdown:
            return
        with self._lock:
            if self._running:
                return
            self._cancelled = False
            self._paused = False
            if reset:
                self._done = 0
                self._failed = 0
                self._total = None
                self._current_title = ""
                self._failure_log = []
            self._running = True
        self._set_state("running")
        self._worker_future = self._executor.submit(self._worker_run)

    def pause(self) -> None:
        """Request a pause; takes effect once the in-flight fetch returns.

        Checked at the top of every candidate iteration in :meth:`_run_batch_async`
        — a pause never aborts an in-flight network call, only stops the next one.
        """
        with self._lock:
            self._paused = True

    def cancel(self) -> None:
        """Request cancellation; the worker exits after the in-flight fetch returns.

        Leaves no worker running once :meth:`_worker_run` observes the flag —
        already-written rows stay written (naturally resumable via the candidate
        query, same as a pause).
        """
        with self._lock:
            self._cancelled = True
            self._paused = False

    def shutdown(self) -> None:
        """Stop the executor without blocking the main thread (closeEvent cleanup).

        A drain in flight is abandoned; because a channel's success/failure marker
        is written only after each fetch completes, an abandoned batch leaves the
        rest unattempted for a future ``start()``/next launch — resumable, same
        contract as ``TmdbEnrichmentManager.shutdown``.
        """
        with self._lock:
            self._shutdown = True
            self._cancelled = True
        self._executor.shutdown(wait=False)

    def get_status(self) -> EnrichmentStatus:
        """Thread-safe snapshot of the queue's current state (no DB read)."""
        with self._lock:
            return EnrichmentStatus(
                state=self._state,
                done=self._done,
                total=self._total or 0,
                current_title=self._current_title,
                failed_count=self._failed,
                recent_failures=tuple(self._failure_log),
            )

    # ------------------------------------------------------------------
    # State helper
    # ------------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        with self._lock:
            self._state = state
        self.state_changed.emit(state)

    # ------------------------------------------------------------------
    # Worker — runs in the single-worker executor (NO widget access)
    # ------------------------------------------------------------------

    def _worker_run(self) -> None:
        """Drain batches until paused, cancelled, shut down, or the work set is empty."""
        reason = "finished"
        try:
            while True:
                with self._lock:
                    if self._shutdown or self._cancelled:
                        reason = "cancelled"
                        break
                    if self._paused:
                        reason = "paused"
                        break

                self._defer_for_migration()

                with self._lock:
                    if self._shutdown or self._cancelled:
                        reason = "cancelled"
                        break

                batch = self._fetch_batch()
                if not batch:
                    reason = "finished"
                    break

                try:
                    asyncio.run(self._run_batch_async(batch))
                except Exception:
                    logger.exception("metadata_enrich: batch run failed")
        finally:
            with self._lock:
                self._running = False
            self._set_state(reason)

    def _defer_for_migration(self) -> None:
        """Best-effort: pause before a batch read while a MigrationManager pass runs.

        Called at the TOP of each drain iteration (before the read query even
        runs) — same shape as ``TmdbEnrichmentManager._defer_for_migration``: a
        plain polled ``is_running`` check, not a scheduler, bounded so a
        stuck/misreporting ``MigrationManager`` can't wedge enrichment forever.
        """
        if self._migration_manager is None:
            return
        waited = 0.0
        while (
            not self._shutdown
            and self._migration_manager.is_running
            and waited < _MIGRATION_DEFER_MAX_WAIT_S
        ):
            time.sleep(_MIGRATION_DEFER_POLL_S)
            waited += _MIGRATION_DEFER_POLL_S
        if waited > 0:
            logger.debug(
                "metadata_enrich: deferred {:.0f}s for a running migration pass", waited
            )

    def _fetch_batch(self) -> list[dict]:
        """Read-only: one drain batch, plus (first call of a run only) the work-set total.

        Own short ``session_scope(commit=False)`` that closes before this method
        returns — the caller never does network I/O while it is open.
        """
        from metatv.core.repositories import RepositoryFactory

        ttl_days = max(1, int(getattr(self.config, "metadata_old_content_ttl_days", 90)))
        stale_before = datetime.now() - timedelta(days=ttl_days)

        with self.db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            excluded = set(repos.providers.get_hidden_provider_ids())

            with self._lock:
                need_total = self._total is None
            if need_total:
                total = repos.channels.count_metadata_enrichment_candidates(
                    excluded, stale_before
                )
                with self._lock:
                    self._total = total

            return repos.channels.select_metadata_enrichment_candidates(
                _BATCH_SIZE, excluded, stale_before
            )

    async def _run_batch_async(self, batch: list[dict]) -> None:
        """Fetch each candidate sequentially — single worker, never parallel.

        Session hygiene: no session is open anywhere in this coroutine. The read
        that produced *batch* already closed in :meth:`_fetch_batch`; the write
        for each row happens in :meth:`_handle_success`/:meth:`_handle_failure`,
        called only AFTER that row's ``await get_metadata(...)`` has returned.
        """
        interval = self._compute_min_interval()
        last_request = 0.0

        for row in batch:
            with self._lock:
                if self._shutdown or self._cancelled or self._paused:
                    return

            if interval > 0:
                wait = interval - (time.monotonic() - last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
            last_request = time.monotonic()

            channel_id = row["id"]
            title = row.get("name") or channel_id
            with self._lock:
                self._current_title = title

            try:
                result = await self.metadata_manager.get_metadata(
                    channel_id, force_refresh=True
                )
            except Exception as exc:
                # Defensive backstop — get_metadata already swallows per-provider
                # errors internally and returns None, but a channel must never be
                # able to kill the queue regardless of where an error surfaces.
                result = None
                reason = f"{type(exc).__name__}: {exc}"
            else:
                reason = None if result else "No metadata found from any enabled provider"

            if result:
                self._handle_success(channel_id, title)
            else:
                self._handle_failure(channel_id, title, reason or "unknown error")

    def _compute_min_interval(self) -> float:
        """Slowest enabled VOD provider's ``get_rate_limit()`` as a per-request floor.

        ``get_metadata`` tries enabled providers in priority order per channel,
        and this queue doesn't know ahead which one will actually serve a given
        row — so the most conservative enabled provider (largest
        ``window_seconds / max_requests``) sets the pace for every request.
        ``(0, 0)`` (no limit, the ``MetadataProviderPlugin`` default) contributes
        no floor. Spacing is enforced with ``asyncio.sleep`` of the shortfall —
        never a busy loop.
        """
        interval = 0.0
        for provider in self.metadata_manager.registry.get_enabled():
            if not any(mt in provider.supported_media_types for mt in ("movie", "series")):
                continue
            max_requests, window_seconds = provider.get_rate_limit()
            if max_requests > 0 and window_seconds > 0:
                interval = max(interval, window_seconds / max_requests)
        return interval

    # ------------------------------------------------------------------
    # Per-item persistence — new session AFTER the network await returns
    # ------------------------------------------------------------------

    def _handle_success(self, channel_id: str, title: str) -> None:
        from metatv.core.repositories import RepositoryFactory

        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.record_metadata_enrich_success(channel_id)
        with self._lock:
            self._done += 1
            done, total = self._done, self._total or 0
        self.progress_changed.emit(done, total, title)

    def _handle_failure(self, channel_id: str, title: str, reason: str) -> None:
        from metatv.core.repositories import RepositoryFactory

        with self.db.session_scope() as session:
            RepositoryFactory(session).channels.record_metadata_enrich_failure(
                channel_id, _MAX_ENRICH_ATTEMPTS
            )
        with self._lock:
            self._done += 1
            self._failed += 1
            self._failure_log.append((title, reason))
            if len(self._failure_log) > _MAX_FAILURE_LOG:
                self._failure_log.pop(0)
            done, total = self._done, self._total or 0
        logger.info("metadata_enrich: {} failed — {}", title, reason)
        self.progress_changed.emit(done, total, title)
        self.enrichment_failed.emit(title, reason)
