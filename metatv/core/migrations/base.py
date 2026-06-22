"""Migration task interface for the MetaTV Migration Center.

A migration task is a self-contained piece of work that:
- Knows whether it needs to run (``needs_run``)
- Knows how to run itself (``run``) with progress reporting and cancellation
- Is idempotent — interrupting it mid-way leaves it in an un-completed state
  so it will re-run on next launch

Usage::

    from metatv.core.migrations.base import MigrationTask

    class MyMigration(MigrationTask):
        id    = "my_migration"
        label = "My migration description"

        def needs_run(self, config) -> bool:
            return config.my_version < MY_VERSION

        def run(self, progress_cb, is_cancelled) -> None:
            ...
"""

from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable


@runtime_checkable
class MigrationTask(Protocol):
    """Protocol that every migration task must satisfy.

    Attributes
    ----------
    id : str
        Unique task identifier (used in signals and logging).
    label : str
        Human-readable description shown in the progress widget.
    """

    id: str
    label: str

    def needs_run(self, config) -> bool:
        """Return True if this migration has not yet completed for *config*.

        Args:
            config: The application ``Config`` instance.

        Returns:
            True when the task should run; False to skip.
        """
        ...

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Execute the migration.

        Must be called from a **worker thread** (never the Qt main thread).

        Args:
            progress_cb: Call with ``(done, total)`` after each unit of work.
                ``done`` must be non-decreasing and end at ``total`` on full
                completion.  May be called zero times for instant tasks.
            is_cancelled: Return True to stop early.  Check at the top of each
                chunk/batch.  On early exit, leave the task in a state where
                ``needs_run`` still returns True so it re-runs next launch.
        """
        ...

    def on_completed(self, config) -> None:
        """Persist that this task has fully completed for *config*.

        Called by the manager on the **main thread** only after ``run`` returns
        without cancellation — typically bumps a version field and saves config
        so ``needs_run`` returns False next launch.  Each task owns its own
        completion bookkeeping (the manager stays task-agnostic).
        """
        ...
