"""Migration task: re-derive ``detected_collection`` to drop redundant tokens.

Owner-reported gap (side-by-side preview, 2026-08-03): the comfy list row's
line-2 collection chip repeats information the row already shows via its own
line-1 chips/icon — a quality tier duplicating the quality chip (e.g. "4K"
when ``detected_quality`` is already "4K"), a media-type word duplicating the
media-type icon (e.g. "SERIES" on a row already showing the series icon), or
a multi-track/sub-dub marker duplicating the subtitle-marker chip. Real
examples: ``"MULTISUB SERIES 4K"`` (every token redundant — should render no
chip at all) and ``"|MULTI| APPLE+ KIDS"`` (should render as
``"APPLE+ KIDS"``). ``ChannelRepository.update_detected_prefixes()`` now runs
every ``detected_collection`` candidate through
``channel_name_utils.strip_collection_noise_tokens()`` at ingestion, alongside
the other ``detected_*`` fields; new channels get it automatically. This task
performs the one-time backfill for rows that existed before the fix shipped.

Idempotency
-----------
``needs_run`` returns True when ``config.collection_token_cleanup_backfill_version``
is behind ``CURRENT_VERSION``. On completion the version is bumped and saved.
An interrupted run — including a crash inside ``run()`` — leaves the version
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

# Bump to re-run the full detected_collection noise-token cleanup for all
# users on next launch.
# History:
#   1 — initial backfill: strip quality/media-type/multi-sub tokens already
#       conveyed elsewhere on the row (quality chip, media-type icon,
#       subtitle-marker chip) out of detected_collection for every existing
#       row, via the same update_detected_prefixes() pass that computes the
#       other detected_* fields.
CURRENT_VERSION: int = 1


class CollectionTokenCleanupBackfillTask:
    """Re-derive ``detected_collection`` for every channel row.

    ``needs_run`` checks ``config.collection_token_cleanup_backfill_version``
    against ``CURRENT_VERSION``. On full completion the version is bumped and
    config is saved; on cancellation (or a crash — see
    ``MigrationManager._run_all``) the version is left unbumped so the next
    launch retries from scratch.
    """

    id: str = "collection_token_cleanup_backfill"
    label: str = "Cleaning up redundant collection tokens"

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
            True when ``config.collection_token_cleanup_backfill_version`` is
            behind ``CURRENT_VERSION``.
        """
        stored = getattr(config, "collection_token_cleanup_backfill_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the full collection-token-cleanup backfill.

        Runs on a **worker thread** (called by ``MigrationManager``).
        Delegates to ``ChannelRepository.update_detected_prefixes(provider_id=None)``
        — the single ingestion chokepoint that now runs every candidate
        through ``strip_collection_noise_tokens()`` alongside the other
        ``detected_*`` fields — which processes all rows in 2000-row batches,
        each batch its own committed transaction (never one long-held write
        lock across the whole scan), retrying transient ``database is
        locked`` errors per batch via the repository's shared
        ``_retry_on_lock`` helper. Any exception that survives those retries
        propagates to the caller (``MigrationManager``), which is what keeps
        the version unbumped on a crash — this task deliberately does NOT
        catch and swallow errors itself (#364).

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        logger.info(
            "CollectionTokenCleanupBackfillTask: starting full "
            "detected_collection noise-token cleanup (version={})",
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

        logger.info("CollectionTokenCleanupBackfillTask: completed")

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.collection_token_cleanup_backfill_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "CollectionTokenCleanupBackfillTask: bumped "
            "collection_token_cleanup_backfill_version={}",
            CURRENT_VERSION,
        )
