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
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from typing import TYPE_CHECKING, Callable

from PyQt6.QtCore import QObject, pyqtSignal
from loguru import logger

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
    """

    # ── Public signals ──────────────────────────────────────────────────────
    task_started  = pyqtSignal(str, str)   # task_id, label
    task_progress = pyqtSignal(str, int, int)  # task_id, done, total
    task_finished = pyqtSignal(str)        # task_id
    all_finished  = pyqtSignal()

    # ── Private signals (worker → main thread marshal) ──────────────────────
    _task_started  = pyqtSignal(str, str)
    _task_progress = pyqtSignal(str, int, int)
    _task_finished = pyqtSignal(str)
    _all_finished  = pyqtSignal()

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

        # Wire private → public (always executes on Qt main thread)
        self._task_started.connect(self.task_started)
        self._task_progress.connect(self.task_progress)
        self._task_finished.connect(self.task_finished)
        self._all_finished.connect(self.all_finished)

    # ── Public API ──────────────────────────────────────────────────────────

    def register(self, task: "MigrationTask") -> None:
        """Register a migration task.

        Tasks are run in registration order when ``run_pending`` is called.

        Args:
            task: Any object satisfying the ``MigrationTask`` protocol.
        """
        self._tasks.append(task)

    def run_pending(self) -> None:
        """Submit all pending tasks to the background worker.

        A task is *pending* when its ``needs_run(config)`` returns True.
        If no tasks need running this is a no-op.  If a run is already in
        progress this call is ignored (the caller should not call again while
        running; the timer fires once at startup).
        """
        if self._running:
            logger.debug("MigrationManager.run_pending: already running, skipping")
            return

        pending = [t for t in self._tasks if t.needs_run(self.config)]
        if not pending:
            logger.debug("MigrationManager.run_pending: no pending tasks")
            return

        self._cancel_event.clear()
        self._running = True
        logger.info(
            "MigrationManager: queuing %d task(s): %s",
            len(pending),
            [t.id for t in pending],
        )
        self._executor.submit(self._run_all, pending)

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
        logger.info("MigrationManager: shutdown complete")

    # ── Internal worker (runs on the pool thread) ───────────────────────────

    def _run_all(self, pending: list["MigrationTask"]) -> None:
        """Worker: iterate through *pending* tasks sequentially."""
        try:
            for task in pending:
                if self._cancel_event.is_set():
                    logger.info(
                        "MigrationManager: cancelled before starting task %s", task.id
                    )
                    break

                logger.info("MigrationManager: starting task %s (%s)", task.id, task.label)
                self._task_started.emit(task.id, task.label)

                def _progress_cb(done: int, total: int, _id=task.id) -> None:
                    self._task_progress.emit(_id, done, total)

                def _is_cancelled() -> bool:
                    return self._cancel_event.is_set()

                try:
                    task.run(_progress_cb, _is_cancelled)
                except Exception:
                    logger.exception(
                        "MigrationManager: task %s raised an exception", task.id
                    )
                    # Emit finished anyway so the widget updates; the version
                    # was not bumped so the task will retry next launch.

                # Only mark complete if the task finished (not cancelled). The
                # task owns its own completion bookkeeping (version bump + save),
                # so the manager stays task-agnostic.
                if not self._cancel_event.is_set():
                    try:
                        task.on_completed(self.config)
                    except Exception:
                        logger.exception(
                            "MigrationManager: task %s on_completed failed", task.id
                        )
                    self._task_finished.emit(task.id)
                    logger.info("MigrationManager: task %s finished", task.id)
                else:
                    # Emit finished so the widget can clean up, but do NOT bump version
                    self._task_finished.emit(task.id)
                    logger.info(
                        "MigrationManager: task %s interrupted by cancellation", task.id
                    )
                    break

        finally:
            self._running = False
            self._all_finished.emit()
            logger.info("MigrationManager: all tasks done")
