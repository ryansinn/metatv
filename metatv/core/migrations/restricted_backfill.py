"""Migration task: backfill ``detected_restricted`` for all channel rows.

Owner-reported gap: the restricted-content hide/only filter (``filter_adult_mode``)
keyed only off the provider's ``is_adult`` API flag. Channels whose NAME/prefix
marks them restricted (XXX / ADULT / X-prefix naming convention — the "Adult"
content-descriptor group) were not caught when the provider failed to flag them,
so they leaked into general surfaces (Discover shelves, recommendations, browse).

``ChannelDB.detected_restricted`` was added so the shared adult-mode gate
(``ChannelRepository._apply_channel_filters`` / ``discovery_engine._apply_adult_filter``)
can read a small, ingestion-computed stored field — via
``channel_name_utils.is_restricted_name()`` — alongside ``is_adult``, instead of
missing name-flagged-but-provider-unflagged channels entirely. New channels get
this field populated automatically at ingestion
(``ChannelRepository.update_detected_prefixes()``, called after every provider
refresh); this task performs the one-time backfill for rows that existed before
the fix shipped.

Idempotency
-----------
``needs_run`` returns True when ``config.restricted_backfill_version`` is behind
``CURRENT_VERSION``.  On completion the version is bumped and saved.  An
interrupted run — including a crash inside ``run()`` — leaves the version
unbumped (see ``MigrationManager._run_all``, which skips ``on_completed`` for
any task whose ``run()`` raises) so the task restarts on the next launch from
scratch; already-committed batches are durable (#364 crash-retry semantics).
"""

from __future__ import annotations

from metatv.core.migrations.detected_fields_reparse import DetectedFieldsReparseTask

# Bump to re-run the full detected_restricted backfill for all users on next launch.
# History:
#   1 — initial backfill: populate detected_restricted (name/prefix restricted-content
#       detection via channel_name_utils.is_restricted_name()) for every existing row,
#       via the same update_detected_prefixes() pass that computes the other
#       detected_* fields.
# 1 -> 2: PORNBOX joined BASE_PREFIX_GROUPS["Adult"]. detected_restricted is
# computed at INGESTION and stored, so a table fix does not reach rows already
# written — 30 of them here. Bumping the version is what re-sweeps them.
CURRENT_VERSION: int = 2


class RestrictedBackfillTask(DetectedFieldsReparseTask):
    """Populate ``detected_restricted`` for every channel row.

    ``needs_run`` checks ``config.restricted_backfill_version`` against
    ``CURRENT_VERSION``.  On full completion the version is bumped and config
    is saved; on cancellation (or a crash — see ``MigrationManager._run_all``)
    the version is left unbumped so the next launch retries from scratch.
    ``__init__``/``needs_run``/``on_completed``/``run`` all come from
    ``DetectedFieldsReparseTask``/``VersionGatedTask``.
    """

    id: str = "restricted_backfill"
    label: str = "Indexing restricted-content flags"
    VERSION_FIELD: str = "restricted_backfill_version"
    CURRENT_VERSION: int = CURRENT_VERSION
