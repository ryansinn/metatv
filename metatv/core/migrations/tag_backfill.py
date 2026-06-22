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

from collections import defaultdict
from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump this constant to re-run the backfill for all users on next launch.
#
# History:
#   1 — initial backfill: populate content_tags from provider_category,
#       header (source_category), name_parse, and genre feeders.
CURRENT_TAG_BACKFILL_VERSION = 1

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
            "TagBackfillTask: starting (version=%d)", CURRENT_TAG_BACKFILL_VERSION
        )

        channel_ids = self._collect_channel_ids()
        total = len(channel_ids)

        if total == 0:
            logger.info("TagBackfillTask: no channels found — nothing to do")
            progress_cb(0, 0)
            return

        logger.info("TagBackfillTask: processing %d channels", total)

        done = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            if is_cancelled():
                logger.info(
                    "TagBackfillTask: cancelled after %d/%d", done, total
                )
                return

            chunk = channel_ids[batch_start : batch_start + _BATCH_SIZE]
            self._process_batch(chunk, config)
            done = batch_start + len(chunk)
            logger.debug(
                "TagBackfillTask: committed batch %d–%d", batch_start, done
            )
            progress_cb(done, total)

        logger.info(
            "TagBackfillTask: completed — tagged %d channels", total
        )

    def on_completed(self, config: "Config") -> None:
        """Bump the version field so the task won't re-run on next launch.

        Args:
            config: The application Config instance.
        """
        config.tag_backfill_version = CURRENT_TAG_BACKFILL_VERSION
        config.save()
        logger.debug(
            "TagBackfillTask: bumped tag_backfill_version=%d",
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

        Args:
            channel_ids: Slice of channel IDs to process.
            config: Live Config instance.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.repositories import RepositoryFactory
        from metatv.core.tag_decomposer import decompose, decompose_name_parse

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)

            # Load only the columns we need for the four feeders — no JSON for
            # channels that have none.
            rows = (
                session.query(
                    ChannelDB.id,
                    ChannelDB.category,
                    ChannelDB.source_category,
                    ChannelDB.detected_prefix,
                    ChannelDB.detected_quality,
                    ChannelDB.detected_region,
                    ChannelDB.detected_year,
                    ChannelDB.raw_data,
                )
                .filter(ChannelDB.id.in_(channel_ids))
                .yield_per(_YIELD_SIZE)
                .all()
            )

            for row in rows:
                (
                    channel_id,
                    category,
                    source_category,
                    detected_prefix,
                    detected_quality,
                    detected_region,
                    detected_year,
                    raw_data,
                ) = row

                # 1. Scrub only this channel's generated tags (user tags survive).
                repos.tags.delete_generated_for_channel(channel_id)

                # 2. Collect (type, value, feeder) tuples from all feeders.
                all_tags = _collect_tags(
                    config=config,
                    category=category,
                    source_category=source_category,
                    detected_prefix=detected_prefix,
                    detected_quality=detected_quality,
                    detected_region=detected_region,
                    detected_year=detected_year,
                    raw_data=raw_data,
                )

                if not all_tags:
                    continue

                # 3. Write — set_content_tags merges feeders + recomputes confidence.
                repos.tags.set_content_tags(channel_id, all_tags, source="generated")


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
) -> list[tuple[str, str, str]]:
    """Run all four feeders and return a merged ``(type, value, feeder)`` list.

    Each distinct ``(type, value)`` pair carries ALL feeder names that produced
    it, deduplicated.  The TagRepository's ``set_content_tags`` uses feeder
    count as the v1 confidence signal, so more independent feeders → higher
    confidence automatically.

    Args:
        config: Live Config instance.
        category:       ``ChannelDB.category`` (provider_category feeder).
        source_category: ``ChannelDB.source_category`` (header feeder).
        detected_prefix:  ``ChannelDB.detected_prefix`` (name_parse feeder).
        detected_quality: ``ChannelDB.detected_quality`` (name_parse feeder).
        detected_region:  ``ChannelDB.detected_region`` (name_parse feeder).
        detected_year:    ``ChannelDB.detected_year`` (name_parse feeder).
        raw_data:         ``ChannelDB.raw_data`` dict (genre feeder).

    Returns:
        List of ``(type, value, feeder)`` tuples ready for
        :meth:`~metatv.core.repositories.tag.TagRepository.set_content_tags`.
    """
    from metatv.core.tag_decomposer import decompose, decompose_name_parse

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

    # Flatten: each (type, value) pair is emitted once per contributing feeder.
    # TagRepository.set_content_tags will merge feeders on the link and compute
    # confidence as min(1.0, len(distinct_feeders) / 3).
    result: list[tuple[str, str, str]] = []
    for (tag_type, tag_value), feeders in feeder_map.items():
        for feeder in sorted(feeders):  # sorted for deterministic ordering
            result.append((tag_type, tag_value, feeder))

    return result
