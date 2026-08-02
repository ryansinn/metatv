"""Migration task: backfill ``plot``/``air_date``/``rating``/``still_url`` on ``EpisodeDB``.

Wave 4 — #247. ``EpisodeDB.raw_data`` has always stored the provider's full
per-episode blob verbatim (``metatv/core/provider_loader.py``), but ingestion
only ever lifted ``title``/``duration``/``container_extension``/``cover_url``
into real columns — the episode plot, air date, rating, and still image were
sitting unused in already-stored data. New episodes get these four columns
populated at ingestion (via the shared
:func:`~metatv.core.episode_metadata_extract.extract_episode_metadata_fields`
chokepoint); this task performs the one-time backfill for episode rows that
existed before the fix shipped, reading ONLY the already-stored ``raw_data`` —
no network access.

Idempotency
-----------
``needs_run`` returns True when ``config.episode_metadata_backfill_version`` is
behind ``CURRENT_VERSION``. On completion the version is bumped and saved. An
interrupted run — including a crash inside ``run()`` — leaves the version
unbumped (``MigrationManager._run_all`` skips ``on_completed`` for any task
whose ``run()`` raises, #364) so the task restarts on the next launch;
already-committed batches are durable.

Session discipline
-------------------
One ``session_scope()`` per batch (not one held open across the whole scan) —
mirrors :mod:`metatv.core.migrations.tag_backfill`. Holding a single session
open across a large table scan has previously produced ``database is locked``
errors against the app's other SQLite writers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from metatv.core.episode_metadata_extract import extract_episode_metadata_fields

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the full episode-metadata backfill for all users on next launch.
# History:
#   1 — initial backfill: populate plot/air_date/rating/still_url from each
#       episode's already-stored raw_data blob.
CURRENT_VERSION: int = 1

# Number of episode rows processed per DB session (commit boundary). One
# session_scope per batch keeps each transaction short and gives cooperative
# cancellation a chance to fire between batches (see module docstring).
_BATCH_SIZE: int = 500


class EpisodeMetadataBackfillTask:
    """Populate ``plot``/``air_date``/``rating``/``still_url`` for every episode row.

    ``needs_run`` checks ``config.episode_metadata_backfill_version`` against
    ``CURRENT_VERSION``. On full completion the task bumps the version and
    saves config; on cancellation (or a crash — see ``MigrationManager._run_all``)
    the version is left unbumped so the next launch retries from scratch.
    """

    id: str = "episode_metadata_backfill"
    label: str = "Backfilling episode plot, air date & rating"

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
            True when ``config.episode_metadata_backfill_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "episode_metadata_backfill_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the episode-metadata backfill.

        Runs on a **worker thread** (called by ``MigrationManager``). Collects
        all episode ids in one short read-only session, then processes them in
        ``_BATCH_SIZE`` chunks, each inside its own ``session_scope()`` — no
        single session is held open across the whole scan (see module
        docstring). Any exception propagates to the caller (``MigrationManager``),
        which is what keeps the version unbumped on a crash — this task
        deliberately does NOT catch and swallow errors itself (#364).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        logger.info(
            "EpisodeMetadataBackfillTask: starting (version={})", CURRENT_VERSION
        )

        episode_ids = self._collect_episode_ids()
        total = len(episode_ids)

        if total == 0:
            logger.info("EpisodeMetadataBackfillTask: no episodes found — nothing to do")
            progress_cb(0, 0)
            return

        logger.info("EpisodeMetadataBackfillTask: processing {} episodes", total)

        done = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            if is_cancelled():
                logger.info(
                    "EpisodeMetadataBackfillTask: cancelled after {}/{}", done, total
                )
                return

            chunk = episode_ids[batch_start : batch_start + _BATCH_SIZE]
            self._process_batch(chunk)
            done = batch_start + len(chunk)
            progress_cb(done, total)

        logger.info("EpisodeMetadataBackfillTask: completed — scanned {} episodes", total)

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.episode_metadata_backfill_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "EpisodeMetadataBackfillTask: bumped episode_metadata_backfill_version={}",
            CURRENT_VERSION,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_episode_ids(self) -> list[str]:
        """Return all episode IDs in a single short, read-only session.

        Column-only projection — no ``raw_data`` loaded here.
        """
        from metatv.core.database import EpisodeDB

        with self._db.session_scope(commit=False) as session:
            rows = session.query(EpisodeDB.id).all()
        return [r[0] for r in rows]

    def _process_batch(self, episode_ids: list[str]) -> None:
        """Backfill one batch of episodes inside a single ``session_scope()``.

        For each row, extracts plot/air_date/rating/still_url from its stored
        ``raw_data`` via the shared :func:`extract_episode_metadata_fields`
        chokepoint. A row whose ``raw_data`` carries none of the four fields is
        left untouched (its columns stay whatever they already were — NULL for
        a never-backfilled row); only fields the extractor actually found are
        written.

        Args:
            episode_ids: Slice of episode IDs to process.
        """
        from metatv.core.database import EpisodeDB

        with self._db.session_scope() as session:
            episodes = (
                session.query(EpisodeDB)
                .filter(EpisodeDB.id.in_(episode_ids))
                .all()
            )
            for ep in episodes:
                fields = extract_episode_metadata_fields(ep.raw_data)
                if all(v is None for v in fields.values()):
                    continue  # nothing in raw_data — leave the row alone
                if fields["plot"] is not None:
                    ep.plot = fields["plot"]
                if fields["air_date"] is not None:
                    ep.air_date = fields["air_date"]
                if fields["rating"] is not None:
                    ep.rating = fields["rating"]
                if fields["still_url"] is not None:
                    ep.still_url = fields["still_url"]
