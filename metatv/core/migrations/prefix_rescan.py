"""Migration task: re-scan all channel names for detected_prefix/quality/region/title/year.

This task re-runs ``update_detected_prefixes`` across the entire channel library
whenever the prefix detection logic has been updated (tracked by a version number
in the user's config).  It runs once per version bump, in the background, with
full progress reporting and clean cancellation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump this constant whenever the prefix detection logic changes (compound
# decomposition, quality token list, normalisation, etc.) to trigger a
# one-time background re-scan for all users on an older version.
#
# History:
#   1 — initial detector (main_window.py CURRENT_DETECTOR_VERSION=1)
#   2 — consolidated: covers all parsing improvements previously tracked by
#       _PREFIX_PARSE_VERSION=1..6 in main_window_nav.py, migrated to
#       MigrationManager framework.
#   3 — code-interpretation alignment (#138): "PUNJABI" now aliases to "PB"
#       (was "PA", which is Panama/Spanish).  Existing generated rows stored
#       Punjabi channels with detected_prefix "PA"; re-run update_detected_prefixes
#       so they become "PB".  Runs BEFORE TagBackfill (registration order) so the
#       re-tag reads the corrected detected_prefix.
CURRENT_PREFIX_SCAN_VERSION = 3

# The compound-prefix parse version that the old nav-mixin tracked separately.
# We persist this into config.prefix_parse_version on completion so existing
# checks (should any remain) don't trigger a redundant re-scan.
_LEGACY_PREFIX_PARSE_VERSION = 6


class PrefixRescanTask:
    """Re-scan channel name fields when the detector logic has been updated.

    ``needs_run`` checks ``config.prefix_detector_version`` against
    ``CURRENT_PREFIX_SCAN_VERSION``.  On full completion the task bumps the
    version and saves config; on cancellation it leaves the version unbumped
    so the next launch will re-run it from scratch.
    """

    id: str = "prefix_rescan"
    label: str = "Rescanning channel name fields"

    def __init__(self, db: "Database") -> None:
        self._db = db

    def needs_run(self, config: "Config") -> bool:
        """Return True when either version field is behind the current detector.

        Two legacy fields are checked:
        - ``prefix_detector_version``: the original main_window.py rescan guard.
        - ``prefix_parse_version``: the compound-prefix rescan guard from
          main_window_nav._PREFIX_PARSE_VERSION (now removed).
        Either being behind is sufficient to trigger a full re-scan.
        """
        stored_detector = getattr(config, "prefix_detector_version", 0)
        stored_parse    = getattr(config, "prefix_parse_version", 0)
        return (
            stored_detector < CURRENT_PREFIX_SCAN_VERSION
            or stored_parse < _LEGACY_PREFIX_PARSE_VERSION
        )

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Execute the prefix re-scan.

        Opens its own ``session_scope`` (commits per batch), calls
        ``progress_cb`` after each batch, and returns early if
        ``is_cancelled()`` becomes True.  On partial completion the session
        is already committed up to the interrupted batch — progress is durable,
        but since the config version is NOT bumped the task re-runs next launch
        to finish the remainder.

        Args:
            progress_cb: ``(done, total)`` — called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
        """
        logger.info(
            "PrefixRescanTask: starting (stored_version={}, current={})",
            0, CURRENT_PREFIX_SCAN_VERSION,
        )
        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.channels.update_detected_prefixes(
                progress_cb=progress_cb,
                is_cancelled=is_cancelled,
            )

        logger.info("PrefixRescanTask: completed successfully")

    def on_completed(self, config: "Config") -> None:
        """Bump both detector version fields + save so the rescan won't re-run.

        Satisfies both the current detector guard and the legacy
        ``prefix_parse_version`` guard, so neither this task nor any stale
        reference re-triggers a redundant scan.
        """
        config.prefix_detector_version = CURRENT_PREFIX_SCAN_VERSION
        config.prefix_parse_version = _LEGACY_PREFIX_PARSE_VERSION
        config.save()
        logger.debug(
            "PrefixRescanTask: bumped prefix_detector_version={}, prefix_parse_version={}",
            CURRENT_PREFIX_SCAN_VERSION, _LEGACY_PREFIX_PARSE_VERSION,
        )
