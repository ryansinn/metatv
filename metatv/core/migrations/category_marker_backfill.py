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

from metatv.core.migrations.detected_fields_reparse import DetectedFieldsReparseTask

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


class CategoryMarkerBackfillTask(DetectedFieldsReparseTask):
    """Populate ``detected_collection``/``detected_collection_language``/
    ``detected_collection_subdub`` for every channel row.

    ``needs_run`` checks ``config.category_marker_backfill_version`` against
    ``CURRENT_VERSION``. On full completion the version is bumped and config
    is saved; on cancellation (or a crash — see ``MigrationManager._run_all``)
    the version is left unbumped so the next launch retries from scratch.
    ``__init__``/``needs_run``/``on_completed``/``run`` all come from
    ``DetectedFieldsReparseTask``/``VersionGatedTask``.
    """

    id: str = "category_marker_backfill"
    label: str = "Cleaning up category markers"
    VERSION_FIELD: str = "category_marker_backfill_version"
    CURRENT_VERSION: int = CURRENT_VERSION
