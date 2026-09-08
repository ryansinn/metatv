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

GENRE-1 (version 2): the Xtream VOD/movie payload carries no
``raw_data["genre"]`` key at all (only the series payload does), so every
movie backfilled by version 1 got ``detected_genre(s) = NULL``. Version 2
re-runs the same full pass; ``update_detected_prefixes()`` now falls back to
``filter_utils.genres_from_category()`` on the provider ``category`` when
``genres_from_raw()`` finds nothing, so this backfill populates rows where
``detected_genres IS NULL AND category IS NOT NULL AND category != ''`` —
through the identical ingestion codepath a fresh row gets, not a second
targeted query.
"""

from __future__ import annotations

from metatv.core.migrations.detected_fields_reparse import DetectedFieldsReparseBase

# Bump to re-run the full detected_genre(s) backfill for all users on next launch.
# History:
#   1 — initial backfill: populate detected_genre (first-segment canonical label)
#       and detected_genres (all-segments canonical list) from raw_data["genre"]
#       for every existing row, via the same update_detected_prefixes() pass that
#       computes the other detected_* fields.
#   2 — GENRE-1: movies have no raw_data["genre"] key at all (only series does),
#       so update_detected_prefixes() now also falls back to
#       genres_from_category() on the provider category; re-run to backfill the
#       movie rows version 1 left NULL.
CURRENT_VERSION: int = 2


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
