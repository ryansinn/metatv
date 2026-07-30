"""Migration task: backfill ``detected_tmdb_id`` from each row's ``raw_data``.

Content-identity Slice 3, step (a).  Rows ingested before the provider tmdb id
was captured have a NULL ``detected_tmdb_id``.  This task reads the ``raw_data``
blob for existing VOD rows and stores the validated ``raw_data["tmdb"]`` value
into the stored ``detected_tmdb_id`` column.

Ordering (critical)
--------------------
This task MUST run **before** ``ContentKeyBackfillTask`` (version 4): the
content_key recompute reads ``detected_tmdb_id`` to emit the tmdb-first key, so
the id column has to be populated first.  The two are registered in that order
in ``gui/main_window.py``.

Idempotency
-----------
``needs_run`` returns True when ``config.tmdb_id_backfill_version`` is behind
``CURRENT_VERSION``.  On completion the version is bumped and saved.  An
interrupted run leaves the version unbumped so the task restarts next launch;
because it only scans rows whose ``detected_tmdb_id`` is still NULL, the restart
is cheap and never re-writes an id it already set.

Generated-data only
-------------------
Only the generated ``detected_tmdb_id`` field is written (derived purely from
the provider blob).  User tags/ratings/favorites are never touched
(mirror-not-cage).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the tmdb-id backfill for all users on next launch.
# History:
#   1 — initial backfill: capture raw_data["tmdb"] into detected_tmdb_id for all
#       pre-Slice-3 VOD rows so the content_key recompute can key on it.
CURRENT_VERSION: int = 1


class TmdbIdBackfillTask:
    """Populate ``detected_tmdb_id`` for every VOD row that still has NULL.

    ``needs_run`` checks ``config.tmdb_id_backfill_version`` against
    ``CURRENT_VERSION``.  On full completion the task bumps the version and
    saves config; on cancellation the version is left unbumped so the next
    launch resumes (a no-op for rows already assigned an id).
    """

    id: str = "tmdb_id_backfill"
    label: str = "Reading provider TMDb ids for content dedup"

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
            True when ``config.tmdb_id_backfill_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "tmdb_id_backfill_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the tmdb-id backfill.

        Runs on a **worker thread** (called by MigrationManager).  Delegates to
        ``ChannelRepository.backfill_tmdb_ids()`` which processes rows in
        2000-row batches, reading ``raw_data`` for one batch at a time.

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        logger.info("TmdbIdBackfillTask: starting (version={})", CURRENT_VERSION)

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.backfill_tmdb_ids(
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )

        logger.info("TmdbIdBackfillTask: completed")

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.tmdb_id_backfill_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "TmdbIdBackfillTask: bumped tmdb_id_backfill_version={}",
            CURRENT_VERSION,
        )
