"""Migration task: propagate ``detected_tmdb_id`` from confident title siblings.

Phase-2 reshape, part 1 (the FREE, no-network layer).  Many idless VOD rows
(``detected_tmdb_id IS NULL``) have a sibling variant — a different language or
quality copy of the *same* production — whose list row DID ship a tmdb id.  This
one-time pass lets each idless row adopt that sibling's id when it shares the
same normalized ``detected_title`` + ``media_type`` and is year-compatible, so
cross-language / quality variants collapse onto one card immediately, before any
provider-detail fetch runs.

Delegates to :meth:`ChannelRepository.propagate_tmdb_from_title_siblings` — the
SAME helper ``update_detected_prefixes`` calls at ingestion, so the one-time
backfill and the self-heal-on-ingest path share one definition.

Ordering
--------
Registered AFTER ``TmdbIdBackfillTask`` (which populates ``detected_tmdb_id``
from ``raw_data``) and ``ContentKeyBackfillTask`` (which sets ``content_key``):
propagation reads the id-bearing rows those two produce and recomputes
``content_key`` for the rows it adopts.  See the registration order in
``gui/main_window.py``.

Idempotency
-----------
``needs_run`` returns True when ``config.tmdb_sibling_propagation_version`` is
behind ``CURRENT_VERSION``.  On completion the version is bumped and saved.  The
pass is fill-empty-only (it never overwrites an existing id) so a re-run after an
interruption is cheap and safe.

Generated-data only
-------------------
Only ``detected_tmdb_id`` / ``content_key`` / ``tmdb_enrich_state`` (all
generated) are written — user tags/ratings/favorites are never touched
(mirror-not-cage).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the title-sibling propagation for all users on next launch.
# History:
#   1 — initial pass: idless VOD rows adopt a confident same-normalized-title +
#       same-media_type + year-compatible sibling's detected_tmdb_id.
#   2 — (#284) the pass now buckets siblings with the SAME normaliser that computes
#       content_key (content_identity.normalize_title_for_key) instead of the
#       raw-name cleaner content_dedup.normalize_title, which double-stripped
#       already-cleaned detected_title values and merged unrelated productions
#       ("Blade Runner 2049" → "blade runner"). Those fake multi-id buckets tripped
#       the remake guard, so rows with unambiguous evidence were skipped. Re-run
#       required: v1 recorded those skips permanently. Measured +498 adoptions,
#       0 lost, on the owner's library.
CURRENT_VERSION: int = 2


class TmdbSiblingPropagationTask:
    """Propagate ``detected_tmdb_id`` onto idless rows from confident title siblings.

    ``needs_run`` checks ``config.tmdb_sibling_propagation_version`` against
    ``CURRENT_VERSION``.  On full completion the task bumps the version and saves
    config; on cancellation the version is left unbumped so the next launch
    re-runs (a cheap no-op for rows already adopted).
    """

    id: str = "tmdb_sibling_propagation"
    label: str = "Linking language/quality variants by shared title"

    def __init__(self, db: "Database") -> None:
        """
        Args:
            db: Database instance.
        """
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when the propagation has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.tmdb_sibling_propagation_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "tmdb_sibling_propagation_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the whole-library title-sibling propagation.

        Runs on a **worker thread** (called by MigrationManager).  Delegates to
        ``ChannelRepository.propagate_tmdb_from_title_siblings()`` (no ``provider_id``
        → whole library), which commits in batches internally.

        Args:
            progress_cb: ``(done, total)`` — reported coarsely (the delegate is an
                in-memory/SQL pass with no network, so it completes quickly relative
                to the network migrations).
            is_cancelled: Returns True when the manager has been asked to stop.
                Checked before the (single) pass starts.
            config: Unused; accepted for forward-compat with MigrationManager
                callers that pass config as a keyword arg.
        """
        if is_cancelled():
            return

        logger.info("TmdbSiblingPropagationTask: starting (version={})", CURRENT_VERSION)
        progress_cb(0, 1)

        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            adopted = repos.channels.propagate_tmdb_from_title_siblings()

        progress_cb(1, 1)
        logger.info("TmdbSiblingPropagationTask: completed ({} rows adopted an id)", adopted)

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.tmdb_sibling_propagation_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "TmdbSiblingPropagationTask: bumped tmdb_sibling_propagation_version={}",
            CURRENT_VERSION,
        )
