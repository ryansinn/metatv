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

from typing import TYPE_CHECKING, Callable, Protocol, runtime_checkable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database


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


class VersionGatedTask:
    """Optional base for the common "gate on one Config version field" shape.

    ``MigrationTask`` above stays a ``Protocol`` BY DESIGN (see its docstring)
    — plenty of tasks don't fit this shape (``MetadataRescanTask`` takes extra
    constructor args, ``QueryIndexTask`` doesn't version-gate at all) and must
    stay free to hand-roll ``needs_run``/``on_completed`` themselves. This is
    for the ones that DO fit it: 19 migration tasks had an identical
    ``__init__`` (``self._db = db``) and 12 had an identical ``needs_run``
    (``getattr(config, "<x>_version", 0) < CURRENT_VERSION``) before this
    existed (docs/REFACTOR_PLAN.md R2).

    Subclasses set two class attributes (alongside the ``id``/``label`` every
    ``MigrationTask`` needs, and their own ``run``):

    - ``VERSION_FIELD``: the ``Config`` attribute name holding the stored
      version, e.g. ``"restricted_backfill_version"``.
    - ``CURRENT_VERSION``: the version ``run()`` brings that field to.

    ``needs_run``/``on_completed`` read/write via plain ``getattr``/``setattr``
    on ``self`` — safe to call on an instance built with ``Cls.__new__(Cls)``
    (skipping ``__init__``, as some tests do), since both only touch the class
    attributes above, never ``self._db``.
    """

    VERSION_FIELD: str
    CURRENT_VERSION: int

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when ``VERSION_FIELD`` on *config* is behind ``CURRENT_VERSION``."""
        stored = getattr(config, self.VERSION_FIELD, 0)
        return stored < self.CURRENT_VERSION

    def on_completed(self, config: "Config") -> None:
        """Bump ``VERSION_FIELD`` to ``CURRENT_VERSION`` on *config* and save it."""
        setattr(config, self.VERSION_FIELD, self.CURRENT_VERSION)
        config.save()
        logger.debug(
            "{}: bumped {}={}",
            type(self).__name__, self.VERSION_FIELD, self.CURRENT_VERSION,
        )
