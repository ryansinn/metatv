"""Serial provider-refresh queue with consolidated overview notification.

:class:`RefreshQueueManager` replaces the old one-thread-per-refresh approach
with a strict FIFO queue that processes **one** provider at a time.  This
eliminates the two problems that arose when many providers were refreshed at
once:

1. **DB-write contention** — ProviderLoadThread writes in bulk; running N of
   them concurrently hammered SQLite with concurrent inserts and triggered
   ``database is locked`` errors.

2. **Notification overflow** — each concurrent refresh spawned its own progress
   toast.  Five sources → five toasts stacked on top of each other.

The new contract:

* One **overview notification** (singleton): a compact per-source status list
  (queued / running / done + %).  Appears when the first provider is enqueued;
  updated as sources are processed; dismissed when the queue empties.
* One **active notification** (the existing step-checklist toast): shows the
  detailed channel-fetch sub-steps for the source being processed RIGHT NOW.
  Completed and replaced as each source finishes.

Thread safety: all mutating methods (``enqueue``, ``_start_next``,
``_on_thread_finished``) are called on the main thread — either directly by
UI slots or via Qt signal delivery.  ``ProviderLoadThread`` is a ``QThread``
whose ``finished`` / ``progress`` signals are connected to slots on *this*
object (a ``QObject``), so Qt automatically delivers them on the main thread.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

# Module-level imports so tests can patch them at `metatv.gui.refresh_queue_manager.*`
from metatv.core.repositories import RepositoryFactory
from metatv.core.provider_loader import ProviderLoadThread
from metatv.core.database import ProviderDB

if TYPE_CHECKING:
    from metatv.core.database import Database
    from metatv.core.config import Config
    from metatv.core.notifications import NotificationManager


class ProviderRefreshStatus(Enum):
    """Per-source status in the overview notification."""
    QUEUED  = "queued"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"


@dataclass
class _QueueEntry:
    """One item in the FIFO queue."""
    provider_id: str
    provider_name: str
    status: ProviderRefreshStatus = ProviderRefreshStatus.QUEUED
    pct: int = 0
    thread: "ProviderLoadThread | None" = field(default=None, repr=False)


class RefreshQueueManager(QObject):
    """Serial FIFO refresh queue with one overview + one active toast.

    Signals
    -------
    queue_changed
        Emitted whenever the queue state changes (enqueue, progress, finish).
        Carries a snapshot list of ``(provider_name, status, pct)`` tuples for
        the overview notification.  Always emitted on the main thread.
    refresh_finished
        Emitted when a single provider's refresh is fully done.
        Carries ``(provider_id, success, message, thread)`` so that the
        MainWindow can run the canonical post-refresh actions (EPG, relink,
        monitor checks, ``_refresh_provider_dependent_views``).
    """

    # Snapshot of (name, status, pct) for the overview widget
    queue_changed = pyqtSignal(list)

    # (provider_id, success, message, thread) — main-window post-refresh hook
    refresh_finished = pyqtSignal(str, bool, str, object)

    def __init__(
        self,
        db: "Database",
        config: "Config",
        notification_manager: "NotificationManager",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._db = db
        self._config = config
        self._nm = notification_manager

        # Ordered queue (oldest-first FIFO)
        self._queue: list[_QueueEntry] = []
        # provider_ids currently in the queue OR running — for dedup
        self._queued_ids: set[str] = set()

        # The singleton overview notification id (None when idle)
        self._overview_notif_id: str | None = None

        logger.debug("RefreshQueueManager initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enqueue(self, provider_id: str, provider_name: str) -> None:
        """Add *provider_id* to the queue (no-op if already queued or running).

        Args:
            provider_id:   Unique provider identifier.
            provider_name: Human-readable label for the overview notification.
        """
        if provider_id in self._queued_ids:
            logger.debug(
                f"RefreshQueueManager: {provider_name!r} already queued/running — skipped"
            )
            return

        entry = _QueueEntry(
            provider_id=provider_id,
            provider_name=provider_name,
        )
        self._queue.append(entry)
        self._queued_ids.add(provider_id)
        logger.info(f"RefreshQueueManager: enqueued {provider_name!r} (queue depth {len(self._queue)})")

        self._emit_queue_changed()
        self._ensure_overview_notification()

        # Kick off the first item immediately if nothing is running
        self._maybe_start_next()

    def shutdown(self) -> None:
        """Graceful shutdown — let the running thread finish but drop the queue.

        Called by MainWindow's cleanup registry on close.  We clear pending
        items so no new threads are started after the window closes, but we
        don't forcefully kill the running thread (that would risk DB corruption).
        """
        logger.info("RefreshQueueManager: shutdown requested")
        # Keep the head (may be RUNNING) but drop everything after it
        if self._queue:
            running = [e for e in self._queue if e.status == ProviderRefreshStatus.RUNNING]
            self._queue = running
        self._queued_ids.clear()
        if self._queue:
            for e in self._queue:
                self._queued_ids.add(e.provider_id)

    def is_queued_or_running(self, provider_id: str) -> bool:
        """Return True if *provider_id* is already in the queue or running."""
        return provider_id in self._queued_ids

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_start_next(self) -> None:
        """Start the head of the queue if nothing is running."""
        # A RUNNING entry is always head of the queue; if it's there, wait.
        if any(e.status == ProviderRefreshStatus.RUNNING for e in self._queue):
            return
        if not self._queue:
            return
        # The next item to start is the first QUEUED entry
        for entry in self._queue:
            if entry.status == ProviderRefreshStatus.QUEUED:
                self._start_entry(entry)
                return

    def _start_entry(self, entry: _QueueEntry) -> None:
        """Build and start a ProviderLoadThread for *entry*."""
        # Use module-level imports (RepositoryFactory, ProviderLoadThread, ProviderDB)
        # so tests can patch them at metatv.gui.refresh_queue_manager.*
        from metatv.gui.main_window_providers import (
            _make_steps, _advance_steps, _has_epg_steps,
            _advance_epg_steps,
        )

        entry.status = ProviderRefreshStatus.RUNNING
        entry.pct = 0
        self._emit_queue_changed()

        # Look up the provider record
        session = self._db.get_session()
        try:
            repos = RepositoryFactory(session)
            db_provider = repos.providers.get_by_id(entry.provider_id)
            if not db_provider:
                logger.error(f"RefreshQueueManager: provider {entry.provider_id!r} not found")
                self._mark_done(entry, success=False, message="Provider not found")
                return
            provider_model = repos.providers.to_model(db_provider)
        finally:
            session.close()

        # Decide whether to show EPG steps
        epg_enabled = self._provider_has_epg(entry.provider_id)
        initial_steps = _make_steps(epg=epg_enabled)

        # Show the active (step-checklist) notification for this source
        active_notif_id = self._nm.show_progress(
            title=f"Refreshing {entry.provider_name}",
            total=100,
            steps=initial_steps,
        )
        # Mutable container so the lambda closures share the same list object
        current_steps: list[list] = [initial_steps]

        def _on_progress(cur: int, tot: int, msg: str) -> None:
            # Advance the step-checklist on the active toast
            new_steps = _advance_steps(current_steps[0], msg, cur)
            current_steps[0] = new_steps
            self._nm.set_steps(active_notif_id, new_steps)
            # Advance the progress bar on the active toast so it moves as
            # sub-tasks complete.  tot is always 100 (phase-banded %).
            if tot and tot > 0:
                self._nm.update_progress(active_notif_id, cur, tot)
            # Update pct on the entry for the overview
            entry.pct = cur
            self._emit_queue_changed()

        def _on_finished(success: bool, message: str) -> None:
            self._on_thread_finished(
                entry, active_notif_id, success, message,
                current_steps, epg_enabled,
            )

        thread = ProviderLoadThread(
            provider_model, self._db,
            separators=self._config.prefix_separators,
            language_groups=self._config.filter_language_groups,
            quality_groups=self._config.filter_quality_groups,
            platform_groups=self._config.filter_platform_groups,
            regional_groups=self._config.filter_regional_groups,
        )
        thread.provider_id = entry.provider_id  # Store for the finished handler
        thread.progress.connect(_on_progress)
        thread.finished.connect(_on_finished)

        entry.thread = thread
        thread.start()
        logger.info(f"RefreshQueueManager: started thread for {entry.provider_name!r}")

    def _on_thread_finished(
        self,
        entry: _QueueEntry,
        active_notif_id: str,
        success: bool,
        message: str,
        current_steps: list[list],
        epg_enabled: bool,
    ) -> None:
        """Called on the main thread when a ProviderLoadThread finishes."""
        from metatv.gui.main_window_providers import (
            _advance_steps, _has_epg_steps,
        )
        from metatv.core.notifications import NotificationType

        logger.info(
            f"RefreshQueueManager: thread finished for {entry.provider_name!r} "
            f"success={success}"
        )

        if success:
            # Mark all channel steps done
            steps = _advance_steps(current_steps[0], "Loaded", 100)
            current_steps[0] = steps
            self._nm.set_steps(active_notif_id, steps)

            if _has_epg_steps(steps):
                # Wire EPG-manager signals to advance the EPG step pair on the
                # active toast.  The manager will be wired via
                # refresh_finished → MainWindow._on_queue_refresh_finished.
                # We pass the notif_id + current_steps via the signal payload
                # so MainWindow can call _wire_epg_step_signals itself.
                pass  # EPG step wiring happens in MainWindow via the signal below
            else:
                self._nm.complete_progress(active_notif_id, message)
        else:
            entry.pct = 0
            self._nm.update(
                active_notif_id,
                type=NotificationType.ERROR,
                title="Refresh Failed",
                message=message,
                dismissible=True,
                auto_dismiss_seconds=5,
            )

        self._mark_done(entry, success=success, message=message)

        # Emit so MainWindow can run the canonical post-refresh actions
        # (EPG relink, monitor checks, _refresh_provider_dependent_views, etc.)
        # The thread is passed through so MainWindow can read prefix_stats.
        self.refresh_finished.emit(
            entry.provider_id,
            success,
            message,
            entry.thread,
        )

        # If EPG steps exist, we need to pass through the active_notif_id and
        # current_steps so MainWindow can wire the EPG signals.  We emit a
        # second specialised signal for this.
        if success and _has_epg_steps(current_steps[0]):
            self._emit_epg_step_wire(
                active_notif_id, entry.provider_id, current_steps
            )
        elif not _has_epg_steps(current_steps[0]) or not success:
            pass  # already completed above

        # Start next item in queue
        self._maybe_start_next()

    def _mark_done(
        self, entry: _QueueEntry, success: bool, message: str
    ) -> None:
        """Mark entry as done/failed, remove from queued_ids, update overview."""
        entry.status = (
            ProviderRefreshStatus.DONE if success else ProviderRefreshStatus.FAILED
        )
        entry.pct = 100 if success else 0
        self._queued_ids.discard(entry.provider_id)

        self._emit_queue_changed()

        # Remove the entry from the queue — it's finished
        if entry in self._queue:
            self._queue.remove(entry)

        self._emit_queue_changed()

        # If queue is now empty, dismiss overview
        if not self._queue:
            self._dismiss_overview()

    # ------------------------------------------------------------------
    # Overview notification helpers
    # ------------------------------------------------------------------

    def _ensure_overview_notification(self) -> None:
        """Create the singleton overview toast if it doesn't exist yet."""
        if self._overview_notif_id is not None:
            return
        # Note: the notification widget prepends its own type icon (⟳ for PROGRESS),
        # so we must NOT include icons.refresh_icon in the title — that would double it.
        # show_bar=False: total=None means an indeterminate bar that sits at 0% the
        # entire time.  The steps list already conveys per-source progress, so the bar
        # adds no information and should not be rendered.
        self._overview_notif_id = self._nm.show_progress(
            title="Source refresh queue",
            total=None,
            steps=self._build_overview_steps(),
            show_bar=False,
        )

    def _dismiss_overview(self) -> None:
        """Dismiss the overview notification and clear the singleton ref."""
        if self._overview_notif_id is not None:
            self._nm.dismiss(self._overview_notif_id)
            self._overview_notif_id = None

    def _build_overview_steps(self) -> list:
        """Build a steps list for the overview toast, one row per queued source.

        Maps each source's :class:`ProviderRefreshStatus` to a
        :class:`~metatv.core.notifications.StepStatus` so the notification widget
        renders a labeled row with a status glyph:

        * QUEUED  → PENDING  (◻ Source name)
        * RUNNING → ACTIVE   (⟳ Source name  45%)
        * DONE    → DONE     (✓ Source name)
        * FAILED  → DONE     (✓ Source name  failed)  — DONE glyph, "failed" suffix

        Returns:
            List of ``(label, StepStatus)`` tuples suitable for
            :meth:`NotificationManager.set_steps`.
        """
        from metatv.core.notifications import StepStatus

        _status_map = {
            ProviderRefreshStatus.QUEUED:  StepStatus.PENDING,
            ProviderRefreshStatus.RUNNING: StepStatus.ACTIVE,
            ProviderRefreshStatus.DONE:    StepStatus.DONE,
            ProviderRefreshStatus.FAILED:  StepStatus.DONE,
        }
        steps: list = []
        for entry in self._queue:
            step_status = _status_map[entry.status]
            if entry.status == ProviderRefreshStatus.RUNNING and entry.pct > 0:
                label = f"{entry.provider_name}  {entry.pct}%"
            elif entry.status == ProviderRefreshStatus.FAILED:
                label = f"{entry.provider_name}  failed"
            else:
                label = entry.provider_name
            steps.append((label, step_status))
        return steps

    def _emit_queue_changed(self) -> None:
        """Emit queue_changed signal and refresh the overview steps."""
        snapshot = [
            (e.provider_name, e.status, e.pct) for e in self._queue
        ]
        self.queue_changed.emit(snapshot)

        # Keep overview steps in sync
        if self._overview_notif_id is not None:
            self._nm.set_steps(self._overview_notif_id, self._build_overview_steps())

    # ------------------------------------------------------------------
    # EPG step wire signal — emitted so MainWindow can wire EPG signals
    # without the manager needing a reference to epg_manager.
    # ------------------------------------------------------------------

    # (active_notif_id, provider_id, current_steps_container)
    _request_epg_wire = pyqtSignal(str, str, object)

    def _emit_epg_step_wire(
        self,
        active_notif_id: str,
        provider_id: str,
        current_steps: list[list],
    ) -> None:
        """Emit _request_epg_wire so MainWindow can call _wire_epg_step_signals."""
        self._request_epg_wire.emit(active_notif_id, provider_id, current_steps)

    # ------------------------------------------------------------------
    # Helpers that probe the DB / config
    # ------------------------------------------------------------------

    def _provider_has_epg(self, provider_id: str) -> bool:
        """Return True if the provider has EPG enabled and a usable URL.

        Mirrors the same logic as ``_ProviderMixin._provider_has_epg`` but
        uses the manager's own references to ``_db`` and ``_epg_manager``.
        """
        epg_manager = getattr(self.parent(), "epg_manager", None)
        if epg_manager is None:
            return False
        # Use module-level ProviderDB import (patchable in tests)
        session = self._db.get_session()
        try:
            provider = session.query(ProviderDB).filter_by(id=provider_id).first()
            if provider is None:
                return False
            if not getattr(provider, "epg_enabled", True):
                return False
            return bool(epg_manager.effective_epg_url(provider))
        finally:
            session.close()
