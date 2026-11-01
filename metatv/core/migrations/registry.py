"""Every startup migration task, in the order they run (ledger F29).

This list used to be 29 hand-written ``migration_manager.register(...)`` calls
in ``gui/main_window.py``, where a task file could exist, be correct, be
tested, and never run, with nothing failing. It lives beside the tasks now, and
``tests/test_migration_registry.py`` fails when a ``*Task`` class in this
package is missing from it.

It is an explicit list, not discovery, because ORDER MATTERS for some pairs and
nothing on a task declares it. The ordering notes stay on the entries they
constrain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

# Static imports, never importlib by name: PyInstaller bundles only what it can
# see imported, and the packaged app died at launch with
# "No module named 'metatv.core.migrations.query_indexes'" (2026-10-19).
from metatv.core.migrations import (
    age_rating_region_cleanup,
    bad_region_cleanup,
    category_facet_refacet,
    category_marker_backfill,
    collection_token_cleanup_backfill,
    company_person_cleanup,
    content_key_backfill,
    credit_tags_backfill,
    credits_text_drop,
    detected_genre_backfill,
    detected_title_reparse,
    epg_channel_id_backfill,
    episode_metadata_backfill,
    feeder_codes_compact,
    metadata_rescan,
    metadata_year_backfill,
    offline_metadata_backfill,
    orphan_sweep,
    person_aliases,
    person_identity,
    playback_events_fold,
    poster_backfill,
    prefix_rescan,
    query_indexes,
    raw_field_backfill,
    restricted_backfill,
    sports_reclassify,
    tag_backfill,
    tag_case_merge,
    tmdb_id_backfill,
    tmdb_sibling_propagation,
    unknown_region_cleanup,
)

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

#: Module name → module, so the lookup below needs no importlib.
_MODULES = {m.__name__.rsplit(".", 1)[-1]: m for m in (
    age_rating_region_cleanup,
    bad_region_cleanup,
    category_facet_refacet,
    category_marker_backfill,
    collection_token_cleanup_backfill,
    company_person_cleanup,
    content_key_backfill,
    credit_tags_backfill,
    credits_text_drop,
    detected_genre_backfill,
    detected_title_reparse,
    epg_channel_id_backfill,
    episode_metadata_backfill,
    feeder_codes_compact,
    metadata_rescan,
    metadata_year_backfill,
    offline_metadata_backfill,
    orphan_sweep,
    person_aliases,
    person_identity,
    playback_events_fold,
    poster_backfill,
    prefix_rescan,
    query_indexes,
    raw_field_backfill,
    restricted_backfill,
    sports_reclassify,
    tag_backfill,
    tag_case_merge,
    tmdb_id_backfill,
    tmdb_sibling_propagation,
    unknown_region_cleanup,
)}

#: ``(module, class, extra)`` in run order. ``extra`` names what the task's
#: constructor takes besides the database: ``"metadata_manager"`` (positional)
#: or ``"config"`` (keyword).
TASKS: tuple[tuple[str, str, str], ...] = (
    # FIRST: every task below scans channels, and this one is what makes those
    # scans fast (and correctly planned — see its docstring).
    ("query_indexes", "QueryIndexTask", ""),
    ("offline_metadata_backfill", "OfflineMetadataBackfillTask", ""),
    ("poster_backfill", "PosterBackfillTask", ""),
    ("prefix_rescan", "PrefixRescanTask", ""),
    ("metadata_rescan", "MetadataRescanTask", "metadata_manager"),
    # ORDER MATTERS — derive stored fields BEFORE deriving tags from them.
    # DetectedTitleReparse populates ChannelDB.detected_audio (and the other
    # detected_* fields + content_key); TagBackfill's audio_annotation feeder
    # READS it. Version-gated, so the wrong order would never self-correct.
    # BEFORE the reparse: clears region codes nothing names (F4); the reparse's
    # fill-empty pass then re-derives them with the fixed parser.
    ("unknown_region_cleanup", "UnknownRegionCleanupTask", ""),
    ("detected_title_reparse", "DetectedTitleReparseTask", ""),
    ("detected_genre_backfill", "DetectedGenreBackfillTask", ""),
    # Regions inherited from an unrelated same-title sibling (#272).
    ("bad_region_cleanup", "BadRegionCleanupTask", ""),
    # Its sibling for age-rating prefixes ("18+"); ahead of TagBackfill so the
    # region is honest when facets are derived from it.
    ("age_rating_region_cleanup", "AgeRatingRegionCleanupTask", ""),
    ("restricted_backfill", "RestrictedBackfillTask", ""),
    ("tag_case_merge", "TagCaseMergeTask", ""),
    ("epg_channel_id_backfill", "EpgChannelIdBackfillTask", ""),
    ("metadata_year_backfill", "MetadataYearBackfillTask", ""),
    ("credit_tags_backfill", "CreditTagsBackfillTask", ""),
    ("feeder_codes_compact", "FeederCodesCompactTask", ""),
    ("person_identity", "PersonIdentityTask", ""),
    ("person_aliases", "PersonAliasTask", ""),
    # AFTER the credit writers and the alias merge: studios out of the person facet (F59).
    ("company_person_cleanup", "CompanyPersonCleanupTask", ""),
    ("credits_text_drop", "CreditsTextDropTask", ""),
    # A new provider field is a row in raw_field_backfill's FIELDS table, not
    # a new task here.
    ("raw_field_backfill", "RawFieldBackfillTask", ""),
    ("orphan_sweep", "OrphanSweepTask", ""),
    ("playback_events_fold", "PlaybackEventsFoldTask", ""),
    # The classifier only sees rows with special_view IS NULL; this re-labels
    # existing ones after a special_content.py fix.
    ("sports_reclassify", "SportsReclassifyTask", ""),
    ("category_marker_backfill", "CategoryMarkerBackfillTask", ""),
    ("collection_token_cleanup_backfill", "CollectionTokenCleanupBackfillTask", ""),
    # ORDER MATTERS — detected_tmdb_id from raw_data BEFORE the content_key
    # recompute reads it, so variants sharing a tmdb id collapse onto one key.
    ("tmdb_id_backfill", "TmdbIdBackfillTask", ""),
    ("content_key_backfill", "ContentKeyBackfillTask", ""),
    # AFTER the id + content_key backfills, so id-bearing siblings exist.
    ("tmdb_sibling_propagation", "TmdbSiblingPropagationTask", ""),
    ("tag_backfill", "TagBackfillTask", "config"),
    ("episode_metadata_backfill", "EpisodeMetadataBackfillTask", ""),
    ("category_facet_refacet", "CategoryFacetRefacetTask", "config"),
)


def build_tasks(db: "Database", *, metadata_manager: Any = None,
                config: "Config | None" = None) -> list:
    """Instantiate every task in :data:`TASKS`, in order.

    Args:
        db: The database every task runs against.
        metadata_manager: For the tasks that re-fetch metadata.
        config: For the tasks that read configuration.

    Returns:
        The task instances, ready for ``MigrationManager.register``.
    """
    tasks = []
    for module, cls_name, extra in TASKS:
        cls = getattr(_MODULES[module], cls_name)
        if extra == "metadata_manager":
            tasks.append(cls(db, metadata_manager))
        elif extra == "config":
            tasks.append(cls(db, config=config))
        else:
            tasks.append(cls(db))
    return tasks
