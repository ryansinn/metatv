"""Migration task: backfill ``content_tags`` for every channel via the decomposer.

Tags Slice T3 (DR-0005).  Runs the four feeders for each channel through
:func:`~metatv.core.tag_decomposer.decompose` /
:func:`~metatv.core.tag_decomposer.decompose_name_parse`, accumulates the
resulting ``(type, value, feeder)`` tuples, and persists them via
:meth:`~metatv.core.repositories.tag.TagRepository.set_content_tags`.

Non-destructive contract
------------------------
For each channel, the task deletes **only** its ``source="generated"``
content-tags before re-deriving.  User-curated tags (``source="user"``) are
never touched.

Idempotency
-----------
A completed run bumps ``config.tag_backfill_version`` to
``CURRENT_TAG_BACKFILL_VERSION`` so the task does not re-run unless the
constant is bumped again.  An interrupted run leaves the version unbumped:
channels processed before the cancel retain their (committed) tags; the task
restarts from scratch on the next launch and re-writes them (idempotent,
because the per-channel delete-before-re-derive is non-destructive toward user
tags).

Memory safety
-------------
The channels table can exceed 1 M rows.  The query uses
``yield_per(_YIELD_SIZE)`` over a column-only projection so only a few
thousand lightweight tuples are in memory at any time — no full ORM objects,
no JSON blobs beyond those needed for the genre feeder.

Confidence
----------
Each ``(type, value)`` pair accumulates the feeder name(s) that independently
produced it.  The v1 confidence formula in
:func:`~metatv.core.repositories.tag._compute_confidence` maps feeder count →
confidence: one feeder → ~0.33, two → ~0.67, three or more → 1.0.  More
independent feeders corroborating the same tag raises confidence without any
manual weighting.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Module-level flag: True while a TagBackfillTask is actively running.
# _update_tags_in_thread in provider_loader checks this before tagging to avoid
# a 3rd concurrent SQLite writer (backfill + store + per-refresh = locked DB).
# Protected by a threading.Lock so it is safe to read/write from any thread.
_backfill_lock = threading.Lock()
_backfill_active: bool = False


def is_backfill_active() -> bool:
    """Return True if a ``TagBackfillTask`` is currently running.

    Thread-safe; may be called from any thread.
    """
    with _backfill_lock:
        return _backfill_active


def _set_backfill_active(active: bool) -> None:
    """Set the module-level backfill-active flag.  Called only by TagBackfillTask."""
    global _backfill_active
    with _backfill_lock:
        _backfill_active = active


# Bump this constant to re-run the backfill for all users on next launch.
#
# History:
#   1 — initial backfill: populate content_tags from provider_category,
#       header (source_category), name_parse, and genre feeders.
#   2 — cross-language genre normalization: extended _GENRE_NORM in filter_utils
#       with Arabic, Polish, Swedish, Danish/Norwegian, Dutch, Slovak, Croatian,
#       Portuguese, Greek, Russian, Hebrew, Turkish, Romanian, and Persian
#       mappings so foreign-language genre names fold into their canonical
#       English equivalents before tags are stored.
#   3 — category→genre cross-walk for movies + series (#77): added
#       recognized_genre() strict-allowlist predicate to filter_utils and a
#       genre pass in _decompose_compound so provider category tokens that
#       match a known canonical genre (e.g. "ACTION/THRILLER", "DRAME",
#       "KOMEDIE") emit genre tags at CONF_STRONG_PRIOR.  Movies previously
#       produced zero genre tags (no raw_data["genre"] field); ~15% of movies
#       now gain genre tags from their provider category.  TMDb will supersede
#       at higher confidence when integrated.
#   4 — audio_annotation feeder (#82/#24): sub/dub/multi parentheticals now
#       produce language: (union), subtitle:, dub:, and format: tags from the
#       stored ChannelDB.detected_audio dict.  Full re-tag required so existing
#       rows gain these facets.
#   5 — Sport → Sports fold (#103): _GENRE_NORM in filter_utils now maps both
#       "sport" and "sports" to the plural canonical "Sports" (matching
#       CONTENT_DESCRIPTOR_GROUPS and BASE_PLATFORM_GROUPS).  Existing
#       source="generated" tags with value "Sport" (singular) must be
#       regenerated as "Sports" to eliminate the split facet.
#   6 — code-interpretation alignment (#138): AR removed from Spanish/South-
#       America/Latin-America groups (AR = Arabic, not Argentina); BS removed
#       from English (BS = Serbian/Croatian); "PA" removed from the Indian
#       language group (PA = Panama/Spanish) while Punjabi moved to "PB".
#       Existing generated tags misclassified Panama channels as language:Indian
#       and Punjabi channels under "PA"; a full re-tag re-derives the correct
#       language/region facets.  Runs AFTER prefix_rescan (v3) so detected_prefix
#       already reflects the PUNJABI→PB alias.  Deletes only source="generated"
#       tags per channel — user-curated tags are untouched.
#   7 — TV-genre fold (#143): _GENRE_NORM in filter_utils now folds the whole
#       fragmented "TV" family (TV program, TV programme, TV Series, Television
#       series, Program Tv, the provider typos TV proramme/PROGRAME, and the
#       bare program/programme) into ONE canonical "TV Show" — TMDB has no
#       single "TV" genre so providers split it into ~15 near-duplicate labels.
#       Existing source="generated" tags holding the old un-normalized values
#       must be regenerated so the filter panel shows one "TV Show" entry with
#       the summed count instead of the fragmented facets.  Deletes only
#       source="generated" tags per channel — user-curated tags are untouched.
#   8 — AI-provenance markers: a trailing "(AI Generated)" (AI-generated content)
#       or "(AI)" (AI voiceover/dub) suffix now emits a content_type: tag
#       (content_type:ai_generated / content_type:ai_voiceover) via a new
#       name-based feeder (decompose_ai_provenance).  Full re-tag required so
#       existing rows gain the excludable facet.  Runs AFTER
#       detected_title_reparse (which strips the "(AI)" marker from the display
#       title and keeps the "(AI Generated)" marker for content-key distinctness).
#       Deletes only source="generated" tags per channel — user tags untouched.
#   9 — genre consolidation (#153): _GENRE_NORM in filter_utils gained 118 new
#       folds (129 chart rows) collapsing ~500 raw genre spellings into ~40
#       canonical genres, PLUS 10 new canonicals (Adult, Politics, Biography,
#       Game Show, Anime, Music Show, TV Movie, and the Drama-led compounds
#       Drama & Comedy / Drama & Crime / Drama & Romance), PLUS 6 corrections:
#       "Soap" → "Soap Opera" (rename), "biografi" → Biography (was History),
#       "tävling" → Game Show (was Reality), "children & family" → Family (was
#       Kids), and removal of the "variety" / "underhållning" / Persian
#       "اجتماعی" concept-guess mappings (now kept raw).  A full re-tag rewrites
#       existing source="generated" genre tags so, e.g., a stored "Soap" tag
#       becomes "Soap Opera" and a "Dram" tag becomes "Drama".  Deletes only
#       source="generated" tags per channel — user-curated tags are untouched.
#       Auditable mapping: docs/GENRE_MAPPING.md.
CURRENT_TAG_BACKFILL_VERSION = 9

# Number of channel rows to stream per SQLAlchemy yield_per chunk.
# Small enough to stay memory-safe on 1 M+ row tables; large enough for
# reasonable throughput.
_YIELD_SIZE: int = 2_000

# Number of channels processed per DB session (commit boundary).
# One session_scope per batch keeps the transaction short and gives
# cooperative cancellation a chance to fire between batches.
_BATCH_SIZE: int = 500


class TagBackfillTask:
    """Populate ``content_tags`` for every channel via the tag decomposer.

    ``needs_run`` checks ``config.tag_backfill_version`` against
    ``CURRENT_TAG_BACKFILL_VERSION``.  On full completion the task bumps the
    version and saves config; on cancellation the version is left unbumped so
    the next launch re-runs from scratch.
    """

    id: str = "tag_backfill"
    label: str = "Building content tags from channel metadata"

    def __init__(self, db: "Database", config: "Config | None" = None) -> None:
        """
        Args:
            db: Database instance.
            config: Live Config instance (provides filter groups for the
                decomposer).  If None, a default Config is loaded lazily at
                run time — this branch exists so the task can be driven
                directly in tests without a full application boot.
        """
        self._db = db
        self._config = config

    def needs_run(self, config: "Config") -> bool:
        """Return True when the backfill has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.tag_backfill_version`` is behind
            ``CURRENT_TAG_BACKFILL_VERSION``.
        """
        stored = getattr(config, "tag_backfill_version", 0)
        return stored < CURRENT_TAG_BACKFILL_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
    ) -> None:
        """Execute the tag backfill.

        Runs on a **worker thread** (called by MigrationManager).  Streams
        all channels in column-only batches, runs the decomposer over each
        feeder, and writes the resulting tags to ``content_tags`` via
        ``TagRepository``.

        Args:
            progress_cb: ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
        """
        config = self._config
        if config is None:
            from metatv.core.config import Config as _Config
            config = _Config.load()

        logger.info(
            "TagBackfillTask: starting (version={})", CURRENT_TAG_BACKFILL_VERSION
        )

        _set_backfill_active(True)
        try:
            channel_ids = self._collect_channel_ids()
            total = len(channel_ids)

            if total == 0:
                logger.info("TagBackfillTask: no channels found — nothing to do")
                progress_cb(0, 0)
                return

            logger.info("TagBackfillTask: processing {} channels", total)

            done = 0
            for batch_start in range(0, total, _BATCH_SIZE):
                if is_cancelled():
                    logger.info(
                        "TagBackfillTask: cancelled after {}/{}", done, total
                    )
                    return

                chunk = channel_ids[batch_start : batch_start + _BATCH_SIZE]
                self._process_batch(chunk, config)
                done = batch_start + len(chunk)
                logger.debug(
                    "TagBackfillTask: committed batch {}–{}", batch_start, done
                )
                progress_cb(done, total)

            logger.info(
                "TagBackfillTask: completed — tagged {} channels", total
            )
        finally:
            _set_backfill_active(False)

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.tag_backfill_version = CURRENT_TAG_BACKFILL_VERSION
        config.save()
        logger.debug(
            "TagBackfillTask: bumped tag_backfill_version={}",
            CURRENT_TAG_BACKFILL_VERSION,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _collect_channel_ids(self) -> list[str]:
        """Return all channel IDs from the DB in a single read-only query.

        Column-only projection — no full ORM objects.
        """
        from metatv.core.database import ChannelDB

        with self._db.session_scope(commit=False) as session:
            rows = (
                session.query(ChannelDB.id)
                .yield_per(_YIELD_SIZE)
                .all()
            )
        # rows is a list of 1-tuples; extract the id strings.
        return [r[0] for r in rows]

    def _process_batch(self, channel_ids: list[str], config: "Config") -> None:
        """Scrub-and-re-tag one batch of channels inside a single session_scope.

        The session is committed at the end of the scope; cancellation between
        batches leaves previously committed batches durable.

        **Write-throughput optimization:** Instead of issuing a DELETE + an
        INSERT/UPSERT per channel (N×2 round-trips for a 500-channel batch), this
        method:

        1. Decomposes ALL channels in the loop (pure CPU — no DB round-trips).
        2. Performs ONE bulk DELETE of generated tags for all channel_ids.
        3. Performs ONE bulk upsert of tag rows + content_tag links for the whole
           batch via :meth:`~metatv.core.repositories.tag.TagRepository.set_content_tags_bulk`.

        This collapses ~1 000 DB round-trips per 500-channel batch to 3,
        reducing wall time by ~10× on typical hardware.

        Args:
            channel_ids: Slice of channel IDs to process.
            config: Live Config instance.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)

            # Load only the columns we need for the four feeders — no JSON for
            # channels that have none.  media_type is required for content-descriptor
            # facet routing (category: live vs genre: movie/series).
            # detected_audio is required for the audio_annotation feeder (feeder 5).
            # name is required for the AI-provenance feeder (decompose_ai_provenance
            # reads the trailing "(AI Generated)" / "(AI)" marker off the raw name).
            rows = (
                session.query(
                    ChannelDB.id,
                    ChannelDB.name,
                    ChannelDB.category,
                    ChannelDB.source_category,
                    ChannelDB.detected_prefix,
                    ChannelDB.detected_quality,
                    ChannelDB.detected_region,
                    ChannelDB.detected_year,
                    ChannelDB.raw_data,
                    ChannelDB.media_type,
                    ChannelDB.detected_audio,
                )
                .filter(ChannelDB.id.in_(channel_ids))
                .yield_per(_YIELD_SIZE)
                .all()
            )

            # Phase 1: decompose all channels in Python (CPU-only, no DB I/O).
            # Build {channel_id: [(type, value, feeder), ...]} for the whole batch.
            tag_map: dict[str, list[tuple[str, str, str]]] = {}
            for row in rows:
                (
                    channel_id,
                    name,
                    category,
                    source_category,
                    detected_prefix,
                    detected_quality,
                    detected_region,
                    detected_year,
                    raw_data,
                    media_type,
                    detected_audio,
                ) = row

                all_tags = _collect_tags(
                    config=config,
                    name=name,
                    category=category,
                    source_category=source_category,
                    detected_prefix=detected_prefix,
                    detected_quality=detected_quality,
                    detected_region=detected_region,
                    detected_year=detected_year,
                    raw_data=raw_data,
                    media_type=media_type,
                    detected_audio=detected_audio,
                )
                # Include every channel (even empty) so channels with no tags
                # still get their generated rows cleared.
                tag_map[channel_id] = all_tags

            # Phase 2: ONE bulk DELETE for all channels in the batch.
            # Only source="generated" rows are removed; user tags survive.
            repos.tags.delete_generated_for_channels(list(tag_map.keys()))

            # Phase 3: ONE bulk upsert for all channels that have at least one tag.
            # Channels with an empty tag list are silently skipped inside the method.
            repos.tags.set_content_tags_bulk(tag_map, source="generated")


# ---------------------------------------------------------------------------
# Feeder wiring (module-level helper — pure, no DB)
# ---------------------------------------------------------------------------

def _collect_tags(
    *,
    config,
    category: str | None,
    source_category: str | None,
    detected_prefix: str | None,
    detected_quality: str | None,
    detected_region: str | None,
    detected_year: str | None,
    raw_data: dict | None,
    media_type: str | None = None,
    detected_audio: dict | None = None,
    name: str | None = None,
) -> list[tuple[str, str, str]]:
    """Run all feeders and return a merged ``(type, value, feeder)`` list.

    Each distinct ``(type, value)`` pair carries ALL feeder names that produced
    it, deduplicated.  The TagRepository's ``set_content_tags`` uses feeder
    count as the v1 confidence signal, so more independent feeders → higher
    confidence automatically.

    After all feeders run, content-descriptor group tags (see
    :data:`~metatv.core.channel_name_utils.CONTENT_DESCRIPTOR_GROUPS` — e.g.
    ``"Sports"``, ``"Adult"``, ``"Kids"``) are re-faceted by *media_type* via
    :func:`~metatv.core.tag_decomposer.remap_content_descriptor_facets`:
    ``category:`` for live channels, ``genre:`` for movies / series / unknown.

    Args:
        config: Live Config instance.
        category:         ``ChannelDB.category`` (provider_category feeder).
        source_category:  ``ChannelDB.source_category`` (header feeder).
        detected_prefix:  ``ChannelDB.detected_prefix`` (name_parse feeder).
        detected_quality: ``ChannelDB.detected_quality`` (name_parse feeder).
        detected_region:  ``ChannelDB.detected_region`` (name_parse feeder).
        detected_year:    ``ChannelDB.detected_year`` (name_parse feeder).
        raw_data:         ``ChannelDB.raw_data`` dict (genre feeder).
        media_type:       ``ChannelDB.media_type`` — used to route content-
                          descriptor groups to the correct facet.  ``None`` /
                          ``"unknown"`` maps to ``genre:``.
        detected_audio:   ``ChannelDB.detected_audio`` dict (audio_annotation feeder).
                          When present, adds ``language:``, ``subtitle:``, ``dub:``,
                          and ``format:`` tags (tasks #82/#24).
        name:             ``ChannelDB.name`` (ai_provenance feeder).  When a trailing
                          ``(AI Generated)`` / ``(AI)`` marker is present, adds a
                          ``content_type:`` tag (``ai_generated`` / ``ai_voiceover``).

    Returns:
        List of ``(type, value, feeder)`` tuples ready for
        :meth:`~metatv.core.repositories.tag.TagRepository.set_content_tags`.
    """
    from metatv.core.tag_decomposer import (
        decompose,
        decompose_ai_provenance,
        decompose_audio,
        decompose_name_parse,
        remap_content_descriptor_facets,
    )

    # key: (type, value)  →  value: set of feeder names
    feeder_map: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Feeder 1: provider_category
    if category:
        for tag_type, tag_value, _conf in decompose(
            "provider_category", category, config=config
        ):
            feeder_map[(tag_type, tag_value)].add("provider_category")

    # Feeder 2: header (source_category = the ##...## label)
    if source_category:
        for tag_type, tag_value, _conf in decompose(
            "header", source_category, config=config
        ):
            feeder_map[(tag_type, tag_value)].add("header")

    # Feeder 3: name_parse (already-typed detected_* fields)
    name_tags = decompose_name_parse(
        detected_prefix=detected_prefix,
        detected_quality=detected_quality,
        detected_region=detected_region,
        detected_year=detected_year,
        config=config,
    )
    for tag_type, tag_value, _conf in name_tags:
        feeder_map[(tag_type, tag_value)].add("name_parse")

    # Feeder 4: genre (raw_data["genre"])
    genre_raw = (raw_data or {}).get("genre")
    if genre_raw:
        for tag_type, tag_value, _conf in decompose(
            "genre", str(genre_raw), config=config
        ):
            feeder_map[(tag_type, tag_value)].add("genre")

    # Feeder 5: audio_annotation (detected_audio — sub/dub/multi language facets)
    # Emits language: (union), subtitle:, dub:, format: tags.
    # The union language: from this feeder merges with any language: from name_parse
    # (more feeders → higher confidence — intended behavior per DR-0006).
    if detected_audio:
        for tag_type, tag_value, _conf in decompose_audio(detected_audio):
            feeder_map[(tag_type, tag_value)].add("audio_annotation")

    # Feeder 6: ai_provenance (trailing "(AI Generated)" / "(AI)" name marker).
    # Emits a content_type: tag (ai_generated / ai_voiceover) so users can exclude
    # AI-generated content and/or AI voiceovers via the tag-facet query path.
    if name:
        for tag_type, tag_value, _conf in decompose_ai_provenance(name):
            feeder_map[(tag_type, tag_value)].add("name_ai_marker")

    # Re-facet content-descriptor groups by media_type.
    # Groups like "Sports", "Adult", "Kids" are placed in language/platform config
    # dicts for display-grouping but they are not locales or platforms; they denote
    # a content KIND.  Route them: category: for live, genre: for everything else.
    remap_content_descriptor_facets(feeder_map, media_type)

    # Flatten: each (type, value) pair is emitted once per contributing feeder.
    # TagRepository.set_content_tags will merge feeders on the link and compute
    # confidence as min(1.0, len(distinct_feeders) / 3).
    result: list[tuple[str, str, str]] = []
    for (tag_type, tag_value), feeders in feeder_map.items():
        for feeder in sorted(feeders):  # sorted for deterministic ordering
            result.append((tag_type, tag_value, feeder))

    return result
