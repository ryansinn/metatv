"""Migration task: backfill ``detected_collection``/``detected_collection_language``/
``detected_collection_subdub`` for all channel rows.

Owner-reported gap: provider category strings often carry a leading pipe-delimited
marker that duplicates channel-name language/subtitle information (e.g.
``"|EN| ANIME"``, ``"|AR-SUB| AMAZON PRIME"``, ``"|DE| FILME 1990-2023"``),
crowding the title in the Comfy channel-list rows. ``ChannelRepository.
update_detected_prefixes()`` now strips and routes this marker at ingestion
(``channel_name_utils.parse_category_marker()``) alongside the other
``detected_*`` fields; new channels get it automatically. This task performs
the one-time backfill for rows that existed before the fix shipped.

Idempotency
-----------
``needs_run`` returns True when ``config.category_marker_backfill_version`` is
behind ``CURRENT_VERSION``. On completion the version is bumped and saved. An
interrupted run — including a crash inside ``run()`` — leaves the version
unbumped (see ``MigrationManager._run_all``, which skips ``on_completed`` for
any task whose ``run()`` raises) so the task restarts on the next launch from
scratch; already-committed batches are durable (#364 crash-retry semantics).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the full detected_collection(_language|_subdub) backfill for all
# users on next launch.
# History:
#   1 — initial backfill: strip/route the leading "|TOKEN|" category marker into
#       detected_collection (clean text), detected_collection_language (a plain
#       marker that disagrees with the channel's own prefix), and
#       detected_collection_subdub (a "CODE-SUB"/"CODE-DUB" marker's chip-ready
#       display text) for every existing row, via the same
#       update_detected_prefixes() pass that computes the other detected_*
#       fields.
CURRENT_VERSION: int = 1


class CategoryMarkerBackfillTask:
    """Populate ``detected_collection``/``detected_collection_language``/
    ``detected_collection_subdub`` for every channel row.

    ``needs_run`` checks ``config.category_marker_backfill_version`` against
    ``CURRENT_VERSION``. On full completion the version is bumped and config
    is saved; on cancellation (or a crash — see ``MigrationManager._run_all``)
    the version is left unbumped so the next launch retries from scratch.
    """

    id: str = "category_marker_backfill"
    label: str = "Cleaning up category markers"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when the backfill has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.category_marker_backfill_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "category_marker_backfill_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the full category-marker backfill.

        Runs on a **worker thread** (called by ``MigrationManager``).
        Delegates to ``ChannelRepository.update_detected_prefixes(provider_id=None)``
        — the single ingestion chokepoint that computes detected_collection(_language|
        _subdub) alongside the other detected_* fields — which processes all rows in
        2000-row batches with commit + expunge between batches. Any exception
        propagates to the caller (``MigrationManager``), which is what keeps the
        version unbumped on a crash — this task deliberately does NOT catch and
        swallow errors itself (#364).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        logger.info(
            "CategoryMarkerBackfillTask: starting full category-marker backfill (version={})",
            CURRENT_VERSION,
        )

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                provider_id=None,
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )

        logger.info("CategoryMarkerBackfillTask: completed")

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.category_marker_backfill_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "CategoryMarkerBackfillTask: bumped category_marker_backfill_version={}",
            CURRENT_VERSION,
        )
