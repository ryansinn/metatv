"""Migration task: backfill ``detected_genre``/``detected_genres`` for all channel rows.

Discover genre-shelf perf fix (#genre-perf).  ``ChannelDB.detected_genre`` /
``detected_genres`` were added so ``get_by_genre``/``get_all_genres`` can read a
small, pre-canonicalised stored field instead of alias-matching against the raw
``raw_data["genre"]`` JSON blob on every shelf expand (was 15-20s over 240k+
rows).  New channels get these fields populated automatically at ingestion
(``ChannelRepository.update_detected_prefixes()``, called after every provider
refresh); this task performs the one-time backfill for rows that existed
before the fix shipped.

Idempotency
-----------
``needs_run`` returns True when ``config.genre_backfill_version`` is behind
``CURRENT_VERSION``.  On completion the version is bumped and saved.  An
interrupted run — including a crash inside ``run()`` — leaves the version
unbumped (see ``MigrationManager._run_all``, which skips ``on_completed`` for
any task whose ``run()`` raises) so the task restarts on the next launch from
scratch; already-committed batches are durable (#364 crash-retry semantics).
"""

from __future__ import annotations

from metatv.core.migrations.detected_fields_reparse import DetectedFieldsReparseBase

# Bump to re-run the full detected_genre(s) backfill for all users on next launch.
# History:
#   1 — initial backfill: populate detected_genre (first-segment canonical label)
#       and detected_genres (all-segments canonical list) from raw_data["genre"]
#       for every existing row, via the same update_detected_prefixes() pass that
#       computes the other detected_* fields.
CURRENT_VERSION: int = 1


class DetectedGenreBackfillTask(DetectedFieldsReparseBase):
    """Populate ``detected_genre``/``detected_genres`` for every channel row.

    ``needs_run`` checks ``config.genre_backfill_version`` against
    ``CURRENT_VERSION``.  On full completion the version is bumped and config
    is saved; on cancellation (or a crash — see ``MigrationManager._run_all``)
    the version is left unbumped so the next launch retries from scratch.
    ``__init__``/``needs_run``/``on_completed``/``run`` all come from
    ``DetectedFieldsReparseBase``/``VersionGatedTask``.
    """

    id: str = "detected_genre_backfill"
    label: str = "Indexing genre shelves"
    VERSION_FIELD: str = "genre_backfill_version"
    CURRENT_VERSION: int = CURRENT_VERSION
