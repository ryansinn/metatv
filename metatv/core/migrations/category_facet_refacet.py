"""Migration task: re-facet content-descriptor group tags to `category:` / `genre:`.

Background
----------
Groups such as "Sports", "Adult", "Kids", "Music", "News", "Religious", and
"24/7" live in ``BASE_PREFIX_GROUPS`` (config) or ``BASE_PLATFORM_GROUPS`` for
display-grouping purposes.  Before this migration the tag decomposer inherited
their group's facet namespace:

- "Adult" in ``BASE_PREFIX_GROUPS`` → ``language:Adult``  (wrong)
- "Sports" / "Kids" / etc. in ``BASE_PLATFORM_GROUPS`` → ``platform:Sports``  (wrong)

These are content-descriptor groups, not locales or platforms.  The correct
facet depends on ``media_type``:

- ``live``                → ``category:`` (a live-channel programming kind)
- ``movie`` / ``series``  → ``genre:``    (a VOD content descriptor)
- unknown / ``None``      → ``genre:``    (safe fallback)

"Pay TV" is a real distribution platform and is deliberately excluded.

What this task does
-------------------
1. Finds all channels that carry ≥1 content_tag whose ``TagDB.value`` is in
   :data:`~metatv.core.channel_name_utils.CONTENT_DESCRIPTOR_GROUPS` and whose
   ``TagDB.type`` is **not** already the correct facet for that channel's
   ``media_type``.
2. For each affected channel (batched ~2000, one ``session_scope`` per batch),
   re-runs ``_collect_tags(..., media_type=…)`` + ``set_content_tags()``.
   ``set_content_tags`` with ``source="generated"`` replaces all generated
   tags for the channel, so the mis-faceted row is removed and the correctly-
   faceted one is written in its place.  User-curated tags are never touched.
3. On full completion, bumps ``config.category_facet_version`` to
   ``CURRENT_VERSION`` and prunes any ``TagDB`` rows for the old wrong-facet
   values (``language:Adult``, ``platform:Sports``, etc.) that now have zero
   ``content_tags`` links.

Idempotency
-----------
``needs_run`` returns True when ``config.category_facet_version`` is behind
``CURRENT_VERSION``.  An interrupted run leaves the version unbumped; the task
restarts on the next launch from scratch (already-committed batches are durable
because ``set_content_tags`` is a REPLACE operation).
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.database import Database

# Bump to re-run the re-facet for all users on next launch.
# History:
#   1 — initial pass: move language:Adult → genre:Adult (movies) / category:Adult (live)
#       and platform:Sports/Kids/Music/News/Religious/24-7 similarly; prune orphan tags.
CURRENT_VERSION: int = 1

# Batch size for the per-channel re-tag loop (channels per session_scope).
_BATCH_SIZE: int = 2_000

# Yield size for SQLAlchemy streaming queries inside a batch.
_YIELD_SIZE: int = 2_000


class CategoryFacetRefacetTask:
    """Re-facet content-descriptor group tags from language:/platform: to category:/genre:.

    ``needs_run`` checks ``config.category_facet_version`` against
    ``CURRENT_VERSION``.  On full completion the task bumps the version,
    saves config, and prunes orphaned wrong-facet ``TagDB`` rows.
    """

    id: str = "category_facet_refacet"
    label: str = "Re-faceting content-kind tags (Sports/Adult/Kids/Music/News…)"

    def __init__(self, db: "Database", config: "Config | None" = None) -> None:
        """
        Args:
            db:     Database instance.
            config: Live Config instance.  If None, a default Config is loaded
                    lazily at run time (allows driving the task in tests without
                    a full application boot).
        """
        self._db = db
        self._config = config

    def needs_run(self, config: "Config") -> bool:
        """Return True when the re-facet has not yet completed for this version.

        Args:
            config: The application Config instance.

        Returns:
            True when ``config.category_facet_version`` is behind
            ``CURRENT_VERSION``.
        """
        stored = getattr(config, "category_facet_version", 0)
        return stored < CURRENT_VERSION

    def run(
        self,
        progress_cb: Callable[[int, int], None],
        is_cancelled: Callable[[], bool],
        config: "Config | None" = None,
    ) -> None:
        """Execute the content-descriptor facet re-migration.

        Runs on a **worker thread** (called by MigrationManager).  For each
        affected channel, scrubs its generated tags and re-derives them with the
        corrected ``media_type``-aware routing.

        Args:
            progress_cb:  ``(done, total)`` called after each batch commit.
            is_cancelled: Returns True when the manager has been asked to stop.
            config:       Overrides ``self._config`` when provided (forward-compat
                          with MigrationManager callers that pass config as a kwarg).
        """
        cfg = config or self._config
        if cfg is None:
            from metatv.core.config import Config as _Config
            cfg = _Config.load()

        logger.info(
            "CategoryFacetRefacetTask: starting (version={})", CURRENT_VERSION
        )

        channel_ids = self._find_affected_channel_ids()
        total = len(channel_ids)

        if total == 0:
            logger.info(
                "CategoryFacetRefacetTask: no affected channels found — nothing to do"
            )
            progress_cb(0, 0)
            return

        logger.info(
            "CategoryFacetRefacetTask: re-tagging {:,} affected channels", total
        )

        done = 0
        for batch_start in range(0, total, _BATCH_SIZE):
            if is_cancelled():
                logger.info(
                    "CategoryFacetRefacetTask: cancelled after {}/{}", done, total
                )
                return

            chunk = channel_ids[batch_start : batch_start + _BATCH_SIZE]
            self._process_batch(chunk, cfg)
            done = batch_start + len(chunk)
            logger.debug(
                "CategoryFacetRefacetTask: committed batch {}–{}", batch_start, done
            )
            progress_cb(done, total)

        logger.info(
            "CategoryFacetRefacetTask: completed — re-tagged {:,} channels", total
        )

    def on_completed(self, config: "Config") -> None:
        """Bump the version, save config, and prune orphaned wrong-facet tags.

        Args:
            config: The application Config instance.
        """
        config.category_facet_version = CURRENT_VERSION
        config.save()
        logger.debug(
            "CategoryFacetRefacetTask: bumped category_facet_version={}",
            CURRENT_VERSION,
        )
        self._prune_orphan_descriptor_tags()

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _find_affected_channel_ids(self) -> list[str]:
        """Return IDs of channels that have ≥1 content-descriptor tag under the wrong facet.

        A channel is "affected" when it has a ``ContentTagDB`` link to a
        ``TagDB`` whose ``value`` is in ``CONTENT_DESCRIPTOR_GROUPS`` and whose
        ``type`` is any of the historically-wrong namespaces (``language``,
        ``platform``, ``genre`` when the channel is live and the tag is a live-
        kind descriptor, or ``category`` when the channel is VOD).

        In practice we take the conservative approach: find all channels that
        have any content-descriptor value linked at all (regardless of whether
        the facet is already correct), and re-run ``_collect_tags`` for them.
        This is safe because ``_collect_tags`` is idempotent — re-running it on
        an already-correct channel produces the same tags.
        """
        from metatv.core.channel_name_utils import CONTENT_DESCRIPTOR_GROUPS
        from metatv.core.database import ContentTagDB, TagDB

        with self._db.session_scope(commit=False) as session:
            rows = (
                session.query(ContentTagDB.channel_id)
                .join(TagDB, ContentTagDB.tag_id == TagDB.id)
                .filter(TagDB.value.in_(list(CONTENT_DESCRIPTOR_GROUPS)))
                .distinct()
                .all()
            )
        return [r[0] for r in rows]

    def _process_batch(self, channel_ids: list[str], config: "Config") -> None:
        """Re-tag one batch of channels inside a single session_scope.

        Scrubs only generated tags for each channel, then re-derives and writes
        them with the corrected ``media_type``-aware routing.

        Args:
            channel_ids: Slice of channel IDs to process.
            config:      Live Config instance.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.migrations.tag_backfill import _collect_tags
        from metatv.core.repositories import RepositoryFactory

        with self._db.session_scope() as session:
            repos = RepositoryFactory(session)

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
                    ChannelDB.media_type,
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
                    media_type,
                ) = row

                # Scrub only generated tags — user tags survive.
                repos.tags.delete_generated_for_channel(channel_id)

                all_tags = _collect_tags(
                    config=config,
                    category=category,
                    source_category=source_category,
                    detected_prefix=detected_prefix,
                    detected_quality=detected_quality,
                    detected_region=detected_region,
                    detected_year=detected_year,
                    raw_data=raw_data,
                    media_type=media_type,
                )

                if all_tags:
                    repos.tags.set_content_tags(
                        channel_id, all_tags, source="generated"
                    )

    def _prune_orphan_descriptor_tags(self) -> None:
        """Delete TagDB rows for wrong-facet descriptor values with zero content_tags links.

        After re-tagging, rows like ``(type="language", value="Adult")`` and
        ``(type="platform", value="Sports")`` should have no remaining links
        (all channels now use the correct ``category:`` or ``genre:`` facet).
        This prune keeps the ``tags`` table tidy.
        """
        from metatv.core.channel_name_utils import CONTENT_DESCRIPTOR_GROUPS
        from metatv.core.database import ContentTagDB, TagDB
        from sqlalchemy import select

        # Facets that were historically used for descriptor values (wrong ones).
        wrong_facets = {"language", "platform"}

        try:
            with self._db.session_scope() as session:
                # Find TagDB rows: wrong facet + descriptor value + zero links.
                # A subquery checks that no ContentTagDB row references this tag.
                tag_rows = (
                    session.query(TagDB)
                    .filter(
                        TagDB.type.in_(list(wrong_facets)),
                        TagDB.value.in_(list(CONTENT_DESCRIPTOR_GROUPS)),
                    )
                    .all()
                )

                pruned = 0
                for tag in tag_rows:
                    link_count = (
                        session.query(ContentTagDB)
                        .filter(ContentTagDB.tag_id == tag.id)
                        .count()
                    )
                    if link_count == 0:
                        session.delete(tag)
                        pruned += 1

                if pruned:
                    logger.info(
                        "CategoryFacetRefacetTask: pruned {:,} orphaned wrong-facet"
                        " descriptor tag rows",
                        pruned,
                    )
        except Exception:
            logger.exception(
                "CategoryFacetRefacetTask: error pruning orphan descriptor tags"
                " (non-fatal, re-run will clean up)"
            )
