"""Migration task: backfill ``content_key`` for all channel rows.

Content-identity Slice 1.  The ``content_key`` column was added to the
``channels`` table; this task computes it from the already-stored
``detected_title``, ``media_type``, and ``detected_year`` fields for all rows
that were ingested before this feature shipped.

Idempotency
-----------
``needs_run`` returns True when ``config.content_key_backfill_version`` is
behind ``CURRENT_VERSION``.  On completion the version is bumped and saved.
An interrupted run leaves the version unbumped so the task restarts on the
next launch from scratch.

When the version is bumped (formula change), ``backfill_content_keys()`` is
called with ``recompute_all=True`` so that EVERY row is recomputed — not just
rows with a NULL key.  The NULL-only path (``recompute_all=False``) is still
used for version 1 (initial population of rows that had no key at all).

Memory safety
-------------
``ChannelRepository.backfill_content_keys()`` processes rows in 2000-row
batches with a commit + expunge_all between batches.  Only the four narrow
columns needed for the key are loaded; the ``raw_data`` JSON blob is never
fetched.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the backfill for all users on next launch.
# History:
#   1 — initial backfill: populate content_key from detected_title / media_type /
#       detected_year for all rows that existed before Slice 1 shipped.
#   2 — formula change (QA 10bc0a7): series/live drop year from the key so
#       cross-source variants with inconsistent year labels collapse correctly;
#       movie years are normalized to start-year (first 4-digit group).
#       Requires recompute_all=True so existing non-NULL rows get the new key.
#   3 — formula change (QA flag 1ebe93bb): key normalisation now strips a trailing
#       MULTI-anchored audio-annotation run ("The Bridge MULTI" → "the bridge|series")
#       so "MULTI" source variants collapse onto their plain siblings.
#       Requires recompute_all=True so existing non-NULL rows get the new key.
#       (Recomputes only the generated content_key column — user tags/ratings/
#       favorites are untouched.)
CURRENT_VERSION: int = 3

# Versions whose formula changed and therefore need every row recomputed, not
# just NULL rows.  Add the new CURRENT_VERSION here whenever the key formula
# changes.
_RECOMPUTE_ALL_VERSIONS: frozenset[int] = frozenset({2, 3})


class ContentKeyBackfillTask:
    """Populate ``content_key`` for every channel row that still has NULL.

    ``needs_run`` checks ``config.content_key_backfill_version`` against
    ``CURRENT_VERSION``.  On full completion the task bumps the version and
    saves config; on cancellation the version is left unbumped so the next
    launch picks up from where backfilling stopped (no-op for already-filled
    rows).
    """

    id: str = "content_key_backfill"
    label: str = "Building content identity keys for channel dedup"

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
            True when ``config.content_key_backfill_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "content_key_backfill_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the content_key backfill.

        Runs on a **worker thread** (called by MigrationManager).  Delegates
        to ``ChannelRepository.backfill_content_keys()`` which processes rows
        in 2000-row batches.

        When the current version requires a full recompute (formula change —
        ``CURRENT_VERSION`` is in ``_RECOMPUTE_ALL_VERSIONS``), passes
        ``recompute_all=True`` so that rows whose key is already set are
        also updated to the new formula.  The NULL-only path is used for
        versions that only add keys for rows that never had one.

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        recompute_all = CURRENT_VERSION in _RECOMPUTE_ALL_VERSIONS
        logger.info(
            "ContentKeyBackfillTask: starting (version={}, recompute_all={})",
            CURRENT_VERSION, recompute_all,
        )

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.backfill_content_keys(
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
                recompute_all=recompute_all,
            )

        logger.info("ContentKeyBackfillTask: completed")

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.content_key_backfill_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "ContentKeyBackfillTask: bumped content_key_backfill_version={}",
            CURRENT_VERSION,
        )
