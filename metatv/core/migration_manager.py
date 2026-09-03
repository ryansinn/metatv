"""MigrationManager — runs registered migration tasks sequentially in the background.

Architecture
------------
- Tasks are registered via ``register(task)``.
- ``run_pending()`` submits all tasks whose ``needs_run(config)`` is True to a
  single-worker ``ThreadPoolExecutor`` (SQLite-safe: no two bulk writers at once).
- Worker emits private signals → public signals arrive on the main thread.
- ``request_cancel()`` sets a ``threading.Event``; each task's ``is_cancelled``
  callable wraps the event so tasks stop between batches.
- ``shutdown()`` cancels and waits for the pool to drain (bounded 10 s timeout)
  so the app closes cleanly — no QThread-destroyed crash.

Signal flow (mirrors ``EpgManager``)::

    worker thread                       main thread
    ─────────────────────────────────── ──────────────────────────────
    _task_started.emit(id, label)   →  task_started(id, label)
    _task_progress.emit(id, d, t)   →  task_progress(id, done, total)
    _task_finished.emit(id)         →  task_finished(id)
    _all_finished.emit()            →  all_finished()
    _pending_evaluated.emit(bool)   →  pending_evaluated(bool)

``needs_run(config)`` is a real table scan for several tasks (785k+ rows);
evaluating every registered task's ``needs_run`` was itself a synchronous
main-thread call inside ``run_pending`` — a sampled 2.0s startup stall
(watchdog, 2026-09-02). Both ``run_pending`` and ``evaluate_pending_async``
now submit that probe pass to the same single-worker executor that runs the
tasks themselves, and report the answer back via ``pending_evaluated``
instead of a blocking ``has_pending_tasks()`` call.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

from metatv.core import migration_gate

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database
    from metatv.core.migrations.base import MigrationTask


class MigrationManager(QObject):
    """Runs registered migration tasks sequentially with UI progress signals.

    Signals (public — connect widgets to these)
    -------------------------------------------
    task_started(task_id: str, label: str)
        Emitted when a task begins execution.
    task_progress(task_id: str, done: int, total: int)
        Emitted after each batch/chunk inside a task.
    task_finished(task_id: str)
        Emitted when a task completes (or is cancelled mid-way and the
        manager moves on — but in practice cancellation stops the loop).
    all_finished()
        Emitted after all pending tasks complete (or the run is cancelled).
    pending_evaluated(bool)
        Emitted once the ``needs_run`` probe pass completes (off the main
        thread) with whether ANY registered task is pending. Emitted by both
        ``evaluate_pending_async`` and ``run_pending`` — a startup gate
        should connect, act, and disconnect after its first delivery (see
        ``MainWindow._gate_startup_fetches``).
    """

    # ── Public signals ──────────────────────────────────────────────────────
    task_started  = pyqtSignal(str, str)   # task_id, label
    task_progress = pyqtSignal(str, int, int)  # task_id, done, total
    task_finished = pyqtSignal(str)        # task_id
    all_finished  = pyqtSignal()
    pending_evaluated = pyqtSignal(bool)

    # ── Private signals (worker → main thread marshal) ──────────────────────
    _task_started  = pyqtSignal(str, str)
    _task_progress = pyqtSignal(str, int, int)
    _task_finished = pyqtSignal(str)
    _all_finished  = pyqtSignal()
    _pending_evaluated = pyqtSignal(bool)

    def __init__(
        self,
        config: "Config",
        db: "Database",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.db = db
        self._tasks: list["MigrationTask"] = []
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="migration"
        )
        self._cancel_event = threading.Event()
        self._running = False
        # Guards run_pending's OWN evaluate-then-run submission only — a
        # separate, unguarded evaluate_pending_async() may also be in flight
        # on the same executor (see its docstring); both are read-only probes
        # so they never race each other, only queue.
        self._evaluating = False

        # Wire private → public (always executes on Qt main thread)
        self._task_started.connect(self.task_started)
        self._task_progress.connect(self.task_progress)
        self._task_finished.connect(self.task_finished)
        self._all_finished.connect(self.all_finished)
        self._pending_evaluated.connect(self.pending_evaluated)

    # ── Public API ──────────────────────────────────────────────────────────

    def register(self, task: "MigrationTask") -> None:
        """Register a migration task.

        Tasks are run in registration order when ``run_pending`` is called.

        Args:
            task: Any object satisfying the ``MigrationTask`` protocol.
        """
        self._tasks.append(task)

    @property
    def is_running(self) -> bool:
        """True while a background migration pass is actively executing.

        Plain attribute read — no lock needed for this soft, best-effort check
        (a bulk writer elsewhere uses it to yield the SQLite write turn rather
        than race a migration's batched commits; see
        ``TmdbEnrichmentManager._defer_for_migration``). A missed transition
        by a beat or two is harmless — the retry helpers on both sides are the
        actual correctness backstop.

        A reader that does not hold (or want to hold) a manager reference —
        e.g. sidebar sections, which construct independently of it — reads the
        same fact via ``core.migration_gate.is_running()`` instead, set/cleared
        by this class alongside ``self._running`` (see ``_run_all``/``shutdown``).
        """
        return self._running

    def has_pending_tasks(self) -> bool:
        """Return True if any registered task's ``needs_run(config)`` is True.

        BLOCKING — scans every registered task's ``needs_run`` synchronously
        on the calling thread. Several tasks' probes are real table scans
        (785k+ rows), so calling this from the Qt main thread reproduces the
        exact stall ``run_pending``/``evaluate_pending_async`` exist to avoid.
        Kept for non-UI callers that genuinely need a synchronous answer;
        startup gating uses ``evaluate_pending_async`` + ``pending_evaluated``
        instead (see ``MainWindow._gate_startup_fetches``).
        """
        return bool(self._pending_tasks())

    def _pending_tasks(self) -> list["MigrationTask"]:
        """Registered tasks whose ``needs_run(config)`` currently returns True."""
        return [t for t in self._tasks if t.needs_run(self.config)]

    def evaluate_pending_async(self) -> None:
        """Probe ``needs_run`` off the main thread; report via ``pending_evaluated``.

        Read-only — submits the probe pass to the same single-worker executor
        ``run_pending`` uses (a read never races the writer since both run on
        that one worker, sequentially). Unguarded: safe to call once per
        startup even if ``run_pending``'s own evaluate-then-run pass is
        independently in flight — both are read-only until a run actually
        starts, so they only ever queue, never race.
        """
        self._executor.submit(self._evaluate_only)

    def _evaluate_only(self) -> None:
        """Worker: compute the pending list and report it, without running anything."""
        pending = self._pending_tasks()
        self._pending_evaluated.emit(bool(pending))

    def run_pending(self) -> None:
        """Submit the pending-task probe, then whatever is pending, to the background worker.

        A task is *pending* when its ``needs_run(config)`` returns True. The
        probe itself now runs off the main thread (see module docstring) —
        this call only submits work and returns; ``pending_evaluated`` and
        ``all_finished``/``task_*`` report the outcome asynchronously. If no
        tasks need running, ``all_finished`` is NOT emitted (matches the old
        synchronous no-op path). If a run is already in progress, or an
        evaluate-then-run pass from an earlier call is still in flight, this
        call is ignored (the caller should not call again while running; the
        timer fires once at startup).
        """
        if self._running:
            logger.debug("MigrationManager.run_pending: already running, skipping")
            return
        if self._evaluating:
            logger.debug("MigrationManager.run_pending: evaluation already in flight, skipping")
            return

        self._evaluating = True
        self._executor.submit(self._evaluate_and_run)

    def _evaluate_and_run(self) -> None:
        """Worker: compute the pending list, report it, then run it if non-empty."""
        pending = self._pending_tasks()
        self._pending_evaluated.emit(bool(pending))
        self._evaluating = False

        if not pending:
            logger.debug("MigrationManager.run_pending: no pending tasks")
            return

        self._cancel_event.clear()
        self._running = True
        logger.info(
            "MigrationManager: queuing {} task(s): {}",
            len(pending),
            [t.id for t in pending],
        )
        # Already running on the worker thread — call directly rather than
        # re-submitting, so this evaluate-then-run pass is one executor job.
        self._run_all(pending)

    def request_cancel(self) -> None:
        """Request cancellation of the running task(s).

        Sets the cancel event; the active task's ``is_cancelled`` callable will
        return True on the next check.  Does not block — cancellation is
        cooperative.
        """
        logger.info("MigrationManager: cancel requested")
        self._cancel_event.set()

    def shutdown(self) -> None:
        """Cancel any running work and shut down the executor.

        Blocks until the worker exits (up to 10 s) so the pool drains before
        the process tears down.  Called by the MainWindow cleanup registry on
        ``closeEvent``.
        """
        logger.info("MigrationManager: shutting down")
        self._cancel_event.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        # Clear even if no pass was running — idempotent, and guarantees a
        # reader (BackgroundRefreshMixin.refresh) never sees a stuck gate past
        # window teardown.
        migration_gate._set_running(False)
        logger.info("MigrationManager: shutdown complete")

    # ── Internal worker (runs on the pool thread) ───────────────────────────

    def _run_all(self, pending: list["MigrationTask"]) -> None:
        """Worker: iterate through *pending* tasks sequentially."""
        # Gate on for the whole pass — set at the same point the first task is
        # about to start, cleared in `finally` alongside "all tasks done". A
        # bulk-write manager (TmdbEnrichmentManager) already polls this same
        # shape via its own `.is_running`; sidebar sections' background reads
        # (BackgroundRefreshMixin.refresh) poll THIS gate instead of contending.
        migration_gate._set_running(True)
        try:
            for task in pending:
                if self._cancel_event.is_set():
                    logger.info(
                        "MigrationManager: cancelled before starting task {}", task.id
                    )
                    break

                logger.info("MigrationManager: starting task {} ({})", task.id, task.label)
                self._task_started.emit(task.id, task.label)

                def _progress_cb(done: int, total: int, _id=task.id) -> None:
                    self._task_progress.emit(_id, done, total)

                def _is_cancelled() -> bool:
                    return self._cancel_event.is_set()

                try:
                    task.run(_progress_cb, _is_cancelled)
                except Exception:
                    logger.exception(
                        "MigrationManager: task {} raised an exception", task.id
                    )
                    # Emit finished so the widget updates, but SKIP on_completed —
                    # a crashed task must NOT bump its version, so it retries next
                    # launch. (This block previously fell through to on_completed,
                    # marking crashed runs complete — the 2026-07-31 reparse-v8
                    # "database is locked" run was burned exactly this way.)
                    self._task_finished.emit(task.id)
                    continue

                # Only mark complete if the task finished (not cancelled). The
                # task owns its own completion bookkeeping (version bump + save),
                # so the manager stays task-agnostic.
                if not self._cancel_event.is_set():
                    try:
                        task.on_completed(self.config)
                    except Exception:
                        logger.exception(
                            "MigrationManager: task {} on_completed failed", task.id
                        )
                    self._task_finished.emit(task.id)
                    logger.info("MigrationManager: task {} finished", task.id)
                else:
                    # Emit finished so the widget can clean up, but do NOT bump version
                    self._task_finished.emit(task.id)
                    logger.info(
                        "MigrationManager: task {} interrupted by cancellation", task.id
                    )
                    break

        finally:
            self._running = False
            migration_gate._set_running(False)
            self._all_finished.emit()
            logger.info("MigrationManager: all tasks done")
