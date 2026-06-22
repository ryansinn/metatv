"""Repository for tag / content-tag management (DR-0005, Tags Slice T1).

Provides ``get_or_create_tag``, ``set_content_tags`` (upsert + feeder merge),
``tags_for``, ``channels_for_tag``, ``reprocess_delete_generated``, and
``get_channel_ids_by_tag_facets`` (faceted filter engine).

Confidence formula (v1):
    confidence = min(1.0, len(distinct_feeders) / 3)

One feeder asserts a tag  → 0.33.
Two feeders assert it     → 0.67.
Three or more feeders     → 1.0 (capped).

This is deliberately coarse; a future slice may replace it with a signal-
weighted blend once real feeder data is available.
"""

from __future__ import annotations

from typing import List, Optional, Set, Tuple

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import exists

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

    def delete_generated_for_channel(self, channel_id: str) -> int:
        """Delete only the ``source="generated"`` content-tag links for *channel_id*.

        User tags (``source="user"``) for the same channel are left intact.
        This is the per-channel non-destructive scrub used by the backfill task
        before re-deriving tags for each channel.

        Args:
            channel_id: The ``ChannelDB.id`` whose generated tags should be cleared.

        Returns:
            Number of rows deleted.
        """
        deleted = (
            self.session.query(ContentTagDB)
            .filter_by(channel_id=channel_id, source="generated")
            .delete(synchronize_session="fetch")
        )
        return deleted

    # ------------------------------------------------------------------
    # Faceted query engine
    # ------------------------------------------------------------------

    def get_channel_ids_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
    ) -> set[str]:
        """Return the set of channel ids that match all include facets and no exclude facets.

        Semantics — standard faceted search:

        **Within a facet (OR):** A channel satisfies an include facet if it
        carries *at least one* ``content_tag`` whose ``(type, value)`` appears
        in the allowed set for that facet.  An absent or empty entry in
        ``includes`` imposes no constraint on that facet — any (or no) value is
        fine.

        **Across facets (AND):** The channel must satisfy *every* constrained
        facet in ``includes``.

        **Excludes (NOT):** A channel is rejected if it carries *any* tag
        listed in ``excludes``, regardless of which facet the tag belongs to.

        **Empty inputs:** When both ``includes`` and ``excludes`` are empty (or
        omitted), all channel ids are returned (optionally scoped to
        ``base_channel_ids``).

        **Memory safety:** Filtering is done entirely in SQL via per-facet
        ``EXISTS`` subqueries joined against ``tags``.  No full-table
        materialisation occurs; the method is safe over 1 M+ channel rows.

        Args:
            includes: Mapping from facet type (e.g. ``"platform"``) to a set of
                allowed values (e.g. ``{"Disney+"}``).  Only non-empty sets are
                treated as constraints; an empty set for a facet key is ignored.
            excludes: Optional mapping from facet type to a set of forbidden
                values.  A channel is removed if it has *any* matching tag.
                Pass ``None`` or an empty dict to apply no exclusions.
            base_channel_ids: Optional pre-filter — only consider channels whose
                ids appear in this set.  Use this to intersect with an existing
                result set (e.g. the active-source-scoped channel list) without
                an extra round-trip.  ``None`` means consider all channels.

        Returns:
            A ``set[str]`` of channel ids satisfying all constraints.
        """
        from sqlalchemy.orm import aliased
        from sqlalchemy import select as sa_select

        excludes = excludes or {}

        # Resolve active include constraints (skip empty value sets).
        constrained_facets: list[tuple[str, set[str]]] = [
            (ftype, vals)
            for ftype, vals in includes.items()
            if vals
        ]

        # --- build the base query: distinct channel_ids in content_tags ---
        #
        # We anchor the outer query on ContentTagDB.channel_id and filter it
        # with correlated EXISTS subqueries — one per include facet (AND) and
        # one NOT EXISTS for the union of all exclude tags.  SQLite evaluates
        # each EXISTS as a correlated scan using the idx on content_tags(tag_id);
        # no full-table materialisation occurs at any facet count.

        outer = aliased(ContentTagDB, flat=True)
        query = self.session.query(outer.channel_id).distinct()

        # Scope to a caller-provided pre-filter if given.
        if base_channel_ids is not None:
            query = query.filter(outer.channel_id.in_(base_channel_ids))

        # --- include facets: one EXISTS per facet (AND across facets) ---
        #
        # For each facet: EXISTS (
        #   SELECT 1 FROM content_tags AS ct_i
        #   JOIN tags AS t_i ON t_i.id = ct_i.tag_id
        #   WHERE ct_i.channel_id = outer.channel_id
        #     AND t_i.type = <ftype>
        #     AND t_i.value IN (<allowed_values>)
        # )

        for ftype, allowed_values in constrained_facets:
            ct_i = aliased(ContentTagDB, flat=True)
            t_i = aliased(TagDB, flat=True)
            subq = (
                sa_select(ct_i.channel_id)
                .join(t_i, t_i.id == ct_i.tag_id)
                .where(
                    ct_i.channel_id == outer.channel_id,
                    t_i.type == ftype,
                    t_i.value.in_(list(allowed_values)),
                )
                .correlate(outer)
            )
            query = query.filter(exists(subq))

        # --- exclude facets: NOT EXISTS over all excluded (type, value) pairs ---
        #
        # NOT EXISTS (
        #   SELECT 1 FROM content_tags AS ct_e
        #   JOIN tags AS t_e ON t_e.id = ct_e.tag_id
        #   WHERE ct_e.channel_id = outer.channel_id
        #     AND (t_e.type, t_e.value) IN (<exclude_pairs>)
        # )
        #
        # SQLite doesn't support tuple IN syntax natively, so we express it as:
        #   AND (  (t_e.type = ftype1 AND t_e.value IN (...))
        #       OR (t_e.type = ftype2 AND t_e.value IN (...))
        #       OR ...  )

        # Build the exclusion subquery if there are any excluded (type, value) pairs.
        exclude_pairs: list[tuple[str, str]] = [
            (ftype, val)
            for ftype, vals in excludes.items()
            if vals
            for val in vals
        ]
        if exclude_pairs:
            ct_e = aliased(ContentTagDB, flat=True)
            t_e = aliased(TagDB, flat=True)

            # Build per-facet OR clauses for the exclude subquery.
            from sqlalchemy import or_, and_
            excl_facet_clauses = [
                and_(t_e.type == ftype, t_e.value.in_(list(vals)))
                for ftype, vals in excludes.items()
                if vals
            ]

            excl_subq = (
                sa_select(ct_e.channel_id)
                .join(t_e, t_e.id == ct_e.tag_id)
                .where(
                    ct_e.channel_id == outer.channel_id,
                    or_(*excl_facet_clauses),
                )
                .correlate(outer)
            )
            query = query.filter(~exists(excl_subq))

        rows = query.all()
        return {row.channel_id for row in rows}


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
