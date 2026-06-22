"""Repository for tag / content-tag management (DR-0005, Tags Slice T1).

Provides ``get_or_create_tag``, ``set_content_tags`` (upsert + feeder merge),
``tags_for``, ``channels_for_tag``, and ``reprocess_delete_generated``.

Confidence formula (v1):
    confidence = min(1.0, len(distinct_feeders) / 3)

One feeder asserts a tag  → 0.33.
Two feeders assert it     → 0.67.
Three or more feeders     → 1.0 (capped).

This is deliberately coarse; a future slice may replace it with a signal-
weighted blend once real feeder data is available.
"""

from __future__ import annotations

from typing import List, Tuple

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from metatv.core.database import ContentTagDB, TagDB

# Confidence denominator — three independent feeders → full confidence.
_FEEDER_DENOMINATOR: int = 3


class TagRepository:
    """CRUD + upsert operations for ``TagDB`` / ``ContentTagDB``.

    All methods run inside the *caller's* session; commit / rollback is
    the caller's responsibility (use ``Database.session_scope()``).
    """

    def __init__(self, session: Session) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Tag (namespace) level
    # ------------------------------------------------------------------

    def get_or_create_tag(self, type: str, value: str) -> TagDB:
        """Return the existing ``TagDB`` for ``(type, value)`` or create one.

        Deduplication is on the ``uq_tag_type_value`` unique constraint.  On a
        race / retry the constraint catches the duplicate and the row is
        fetched instead.

        Args:
            type: Namespace string, e.g. ``"region"``, ``"genre"``.
            value: Canonical value, e.g. ``"US"``, ``"Drama"``.

        Returns:
            The persistent ``TagDB`` row (id is populated after flush).
        """
        row = (
            self.session.query(TagDB)
            .filter_by(type=type, value=value)
            .first()
        )
        if row is not None:
            return row

        row = TagDB(type=type, value=value)
        self.session.add(row)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            row = (
                self.session.query(TagDB)
                .filter_by(type=type, value=value)
                .one()
            )
        return row

    # ------------------------------------------------------------------
    # ContentTag level
    # ------------------------------------------------------------------

    def set_content_tags(
        self,
        channel_id: str,
        tags: List[Tuple[str, str, str]],
        source: str = "generated",
    ) -> None:
        """Upsert content-tag links for ``channel_id``, merging feeders.

        Each element of ``tags`` is ``(type, value, feeder)``.  For each
        distinct ``(type, value)`` pair:

        - If no link exists, one is created with ``feeders=[feeder]``.
        - If a link already exists (same source), the feeder is added to the
          existing ``feeders`` list (deduplicated) and ``confidence`` is
          recomputed using the v1 formula.

        Only rows with the given ``source`` are touched; rows written by a
        different source are left unchanged.

        Args:
            channel_id: The ``ChannelDB.id`` to tag.
            tags: List of ``(type, value, feeder)`` tuples.
            source: Provenance label; ``"generated"`` or ``"user"``.
        """
        for tag_type, tag_value, feeder in tags:
            tag = self.get_or_create_tag(tag_type, tag_value)

            link = (
                self.session.query(ContentTagDB)
                .filter_by(channel_id=channel_id, tag_id=tag.id, source=source)
                .first()
            )

            if link is None:
                link = ContentTagDB(
                    channel_id=channel_id,
                    tag_id=tag.id,
                    source=source,
                    feeders=[feeder],
                    confidence=_compute_confidence([feeder]),
                )
                self.session.add(link)
            else:
                existing: List[str] = list(link.feeders or [])
                if feeder not in existing:
                    existing.append(feeder)
                link.feeders = existing
                link.confidence = _compute_confidence(existing)

        try:
            self.session.flush()
        except IntegrityError:
            logger.warning(
                "set_content_tags: integrity error for channel_id={} — skipping",
                channel_id,
            )
            self.session.rollback()

    def tags_for(self, channel_id: str) -> List[Tuple[str, str]]:
        """Return all ``(type, value)`` tuples tagged on ``channel_id``.

        Returns plain tuples — no ORM objects cross the session boundary.

        Args:
            channel_id: The ``ChannelDB.id`` to look up.

        Returns:
            List of ``(type, value)`` pairs, unordered.
        """
        rows = (
            self.session.query(TagDB.type, TagDB.value)
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == channel_id)
            .all()
        )
        return [(r.type, r.value) for r in rows]

    def channels_for_tag(self, type: str, value: str) -> List[str]:
        """Return ``channel_id`` strings for every channel carrying ``(type, value)``.

        Returns plain strings — no ORM objects cross the session boundary.

        Args:
            type: Tag namespace.
            value: Canonical tag value.

        Returns:
            List of ``channel_id`` strings, unordered.
        """
        tag = (
            self.session.query(TagDB)
            .filter_by(type=type, value=value)
            .first()
        )
        if tag is None:
            return []

        rows = (
            self.session.query(ContentTagDB.channel_id)
            .filter_by(tag_id=tag.id)
            .all()
        )
        return [r.channel_id for r in rows]

    # ------------------------------------------------------------------
    # Reprocess support
    # ------------------------------------------------------------------

    def reprocess_delete_generated(self) -> int:
        """Delete all ``source="generated"`` content-tag links.

        User tags (``source="user"``) are untouched.  This is the non-
        destructive reprocess primitive: callers can wipe machine-derived
        tags and re-run detection without touching user curation.

        Returns:
            Number of rows deleted.
        """
        deleted = (
            self.session.query(ContentTagDB)
            .filter_by(source="generated")
            .delete(synchronize_session="fetch")
        )
        logger.info("reprocess_delete_generated: removed {} content_tag rows", deleted)
        return deleted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_confidence(feeders: List[str]) -> float:
    """Confidence v1 formula: ``min(1.0, len(distinct_feeders) / 3)``.

    Args:
        feeders: List of feeder names (may contain duplicates; only distinct
            values are counted).

    Returns:
        Float in ``[0.33, 1.0]`` for non-empty lists; ``0.0`` for empty.
    """
    distinct = len(set(feeders))
    if distinct == 0:
        return 0.0
    return min(1.0, distinct / _FEEDER_DENOMINATOR)
