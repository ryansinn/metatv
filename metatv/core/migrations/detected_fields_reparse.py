"""Shared ``run()`` for every migration task that re-derives the ``detected_*``
channel fields via a full ``update_detected_prefixes()`` pass.

Five migration tasks — ``category_marker_backfill.py``,
``collection_token_cleanup_backfill.py``, ``detected_genre_backfill.py``,
``detected_title_reparse.py`` and ``restricted_backfill.py`` — had a
byte-identical ``run()`` body: open a ``session_scope``, build a
``RepositoryFactory``, call
``repos.channels.update_detected_prefixes(provider_id=None, progress_cb=...,
is_cancelled=...)``. Each is version-gated on its OWN ``Config`` field because
each shipped as its own fix for its own bug, at its own time, and each still
needs its own ``id``/``label`` (the Migration Center progress widget and the
What's New/QA history name them individually) — so they stay FIVE registered
tasks (``MigrationManager.register()`` is called once per key in
``main_window.py``, unchanged), not one. Only the ``run()`` body — and the
``__init__``/``needs_run``/``on_completed`` boilerplate handled by
``VersionGatedTask`` — was ever actually shared (docs/REFACTOR_PLAN.md R2).

No coalescing: when several of these five are pending together, MigrationManager
still runs five full ``update_detected_prefixes()`` passes rather than one.
Collapsing them into a single pass was considered (an earlier audit flagged the
redundancy) but rejected here — ``MigrationManager._run_all`` computes its
``pending`` list once, up front, and calls each task's own ``run()``/
``on_completed()`` independently; making one task's ``run()`` silently satisfy
its siblings would need cross-instance shared state (these tasks are freshly
constructed, one per registration, with no shared config/session reference)
for a purely cosmetic startup-time saving, and ``MigrationManager``'s contract
(each task owns its own completion bookkeeping) was not to be touched by this
slice. Multiple full passes on an upgrade are the existing, understood
behaviour; kept as-is.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.core.migrations.base import VersionGatedTask

if TYPE_CHECKING:
    from metatv.core.config import Config


class DetectedFieldsReparseBase(VersionGatedTask):
    """Base for a version-gated task whose whole job is one
    ``update_detected_prefixes()`` pass. Subclasses set ``id``, ``label``,
    ``VERSION_FIELD`` and ``CURRENT_VERSION`` only.
    """

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the full ``detected_*`` backfill.

        Runs on a **worker thread** (called by ``MigrationManager``).
        Delegates to ``ChannelRepository.update_detected_prefixes(provider_id=None)``
        — the single ingestion chokepoint that computes every ``detected_*``
        field in one pass — which processes all rows in 2000-row batches with
        commit + expunge (and lock-retry, via the repository's shared
        ``_retry_on_lock`` helper) between batches. Any exception propagates
        to the caller (``MigrationManager``), which is what keeps the version
        unbumped on a crash — this task deliberately does NOT catch and
        swallow errors itself (#364).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        name = type(self).__name__
        logger.info("{}: starting full backfill (version={})", name, self.CURRENT_VERSION)

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                provider_id=None,
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )

        logger.info("{}: completed", name)
