"""``content_tags`` write/CRUD path — split out of ``tag.py`` (DB-9).

``tag.py`` was already at its code-health baseline before DB-9 (the schema
change that gave every method here a public ``channel_id`` string ↔ internal
``ContentTagDB.channel_key`` int boundary to cross). This is the cohesive
half of that file that WRITES or looks up individual channels' tags — upsert,
delete, per-channel read, and the small content-type id-set helper. The other
half, left in ``tag.py``, is the faceted READ/aggregate query engine (facet
counts, the recipe builder's faceted search). ``TagRepository`` composes both
via ``ContentTagCrudMixin`` — split by isolation, not by line count.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set, Tuple

from loguru import logger
from sqlalchemy.exc import IntegrityError

from metatv.core.database import ChannelDB, ContentTagDB, TagDB

#: Confidence denominator — three independent feeders → full confidence.
_FEEDER_DENOMINATOR: int = 3

#: Per-feeder weight in the confidence sum. A feeder not listed weighs 1.
#: ``region_inference`` is a language GUESSED from a region code on a film or
#: series (LANG-1): kept so the title stays findable, weighted so any real
#: evidence outranks it — alone it reads 0.1, never "confirmed".
_FEEDER_WEIGHTS: dict[str, float] = {"region_inference": 0.3}


def _compute_confidence(feeders: List[str]) -> float:
    """Confidence v1 formula (LANG-1 weighted): ``min(1.0, sum(weight(f) for f
    in distinct_feeders) / 3)``.

    Every feeder weighs ``1.0`` unless listed in :data:`_FEEDER_WEIGHTS` — a
    ``region_inference`` feeder (a language guessed from a region/catalogue
    code, never a statement of the spoken language) weighs ``0.3`` so it reads
    as a low-confidence hint rather than corroborated fact, while any feeder
    that actually asserts the language (e.g. ``audio_annotation``) still
    outranks it. With no weighted feeders this is exactly the old pure-count
    formula: one feeder → 0.33, two → 0.67, three+ → 1.0 (capped).

    Args:
        feeders: List of feeder names (may contain duplicates; only distinct
            values are counted).

    Returns:
        Float in ``[0.0, 1.0]``; ``0.0`` for an empty list.
    """
    distinct = set(feeders)
    if not distinct:
        return 0.0
    weighted_sum = sum(_FEEDER_WEIGHTS.get(f, 1.0) for f in distinct)
    return min(1.0, weighted_sum / _FEEDER_DENOMINATOR)


class ContentTagCrudMixin:
    """Upsert / delete / per-channel read methods on ``ContentTagDB``.

    Composed into ``TagRepository`` (``tag.py``), which supplies
    ``self.session`` and ``self.get_or_create_tag_id`` — every method here
    runs inside the caller's session, same contract as the rest of that class.
    """

    # DB-9 chokepoint: resolve the public ChannelDB.id API boundary to the
    # int channel_key content_tags actually joins on — never re-derived inline.
    def _channel_key(self, channel_id: str) -> Optional[int]:
        """Resolve one public ``channel_id`` to its ``channel_key``, or None."""
        return (
            self.session.query(ChannelDB.channel_key)
            .filter(ChannelDB.id == channel_id)
            .scalar()
        )

    def _channel_keys(self, channel_ids) -> Dict[str, int]:
        """Bulk sibling of :meth:`_channel_key`: ``{channel_id: channel_key}``."""
        if not channel_ids:
            return {}
        return dict(
            self.session.query(ChannelDB.id, ChannelDB.channel_key)
            .filter(ChannelDB.id.in_(list(channel_ids))).all()
        )

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

        **Performance:** Replaces the original per-tag SELECT + conditional
        ``session.add`` loop with a single bulk SELECT over all existing links
        for this channel+source, Python-side feeder merge, then a single
        ``INSERT … ON CONFLICT DO UPDATE`` upsert for the full set.  This
        reduces ~2N small queries to 1 bulk SELECT + 1 bulk upsert per call.

        Args:
            channel_id: The ``ChannelDB.id`` to tag.
            tags: List of ``(type, value, feeder)`` tuples.
            source: Provenance label; ``"generated"`` or ``"user"``.
        """
        if not tags:
            return

        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

        channel_key = self._channel_key(channel_id)
        if channel_key is None:
            logger.warning("set_content_tags: no channel_key for channel_id={} — skipping", channel_id)
            return

        # Step 1: resolve tag ids (cached — typically 0 DB round-trips after warmup).
        tag_ids: List[Tuple[int, str]] = []  # (tag_id, feeder)
        for tag_type, tag_value, feeder in tags:
            tag_ids.append((self.get_or_create_tag_id(tag_type, tag_value), feeder))

        # Step 2: load all existing links for this channel+source in one SELECT.
        existing_tag_ids = [tid for tid, _ in tag_ids]
        existing_rows = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_key == channel_key,
                ContentTagDB.tag_id.in_(existing_tag_ids),
                ContentTagDB.source == source,
            )
            .all()
        )
        # Build a map tag_id → current feeders list for O(1) merge lookups.
        existing_feeders: Dict[int, List[str]] = {
            row.tag_id: list(row.feeders or []) for row in existing_rows
        }

        # Step 3: compute merged feeders + confidence for every (tag_id, feeder) pair.
        # Group by tag_id first so that duplicate (type, value) pairs in a single
        # `tags` call are handled correctly (multiple feeders for the same tag).
        merged: Dict[int, List[str]] = {}
        for tag_id, feeder in tag_ids:
            if tag_id not in merged:
                # Start from existing DB feeders so we don't clobber prior assertions.
                merged[tag_id] = list(existing_feeders.get(tag_id, []))
            if feeder not in merged[tag_id]:
                merged[tag_id].append(feeder)

        # Step 4: single bulk upsert — INSERT … ON CONFLICT(channel_key, tag_id, source)
        # DO UPDATE SET feeders=excluded.feeders. The composite PK is the
        # uniqueness constraint; ``confidence`` is derived, not stored (see
        # _compute_confidence).
        rows = [
            {
                "channel_key": channel_key,
                "tag_id": tag_id,
                "source": source,
                "feeders": feeders,
            }
            for tag_id, feeders in merged.items()
        ]

        try:
            stmt = _sqlite_insert(ContentTagDB).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_key", "tag_id", "source"],
                set_={"feeders": stmt.excluded.feeders},
            )
            self.session.execute(stmt)
            self.session.flush()
        except IntegrityError:
            logger.warning(
                "set_content_tags: integrity error for channel_id={} — skipping",
                channel_id,
            )
            self.session.rollback()

    def get_channel_tags_dto(self, channel_id: str) -> List:
        """Return ChannelTagDTO objects for all tags on ``channel_id``.

        Reads ``ContentTagDB`` + ``TagDB`` in one JOIN; maps feeders to the
        ``source_given`` provenance flag per DR-0006.  No ORM objects cross
        the session boundary — caller gets plain frozen dataclasses.

        Provenance rule: a tag is ``source_given=True`` when *any* feeder in
        its feeders list is a direct provider-field reader (``provider_category``,
        ``genre``, or ``user``).  If all feeders are inference-based
        (``name_parse``, ``header``, ``epg``), ``source_given=False``.

        Args:
            channel_id: The ``ChannelDB.id`` to look up.

        Returns:
            List of ``ChannelTagDTO``, sorted by facet then value.
            An empty list is returned when the channel has no tags.
        """
        from metatv.core.repositories.dtos import ChannelTagDTO, _SOURCE_GIVEN_FEEDERS

        rows = (
            self.session.query(
                TagDB.type,
                TagDB.value,
                ContentTagDB.feeders,
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .join(ChannelDB, ChannelDB.channel_key == ContentTagDB.channel_key)
            .filter(ChannelDB.id == channel_id)
            .order_by(TagDB.type, TagDB.value)
            .all()
        )

        dtos: List[ChannelTagDTO] = []
        for tag_type, value, feeders_raw in rows:
            feeder_list: List[str] = feeders_raw if isinstance(feeders_raw, list) else []
            # source_given = True when any feeder is a direct provider-field reader
            source_given = any(f in _SOURCE_GIVEN_FEEDERS for f in feeder_list)
            dtos.append(ChannelTagDTO(
                facet_type=tag_type,
                value=value,
                source_given=source_given,
                confidence=_compute_confidence(feeder_list),
                feeders=tuple(feeder_list),
            ))
        return dtos

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
            .join(ChannelDB, ChannelDB.channel_key == ContentTagDB.channel_key)
            .filter(ChannelDB.id == channel_id)
            .all()
        )
        return [(r.type, r.value) for r in rows]

    def collections_for(self, channel_ids: List[str]) -> Dict[str, str]:
        """Return each channel's stored ``collection`` tag value, in one query.

        The batch form of reading ``facet_type == "collection"`` off
        :meth:`get_channel_tags_dto`: when a channel carries several, the
        alphabetically first wins — the same one that single-channel read
        surfaces (it sorts by type, then value).

        Args:
            channel_ids: ``ChannelDB.id`` values to look up.

        Returns:
            ``{channel_id: collection}``; a channel with no collection tag is
            absent.
        """
        if not channel_ids:
            return {}
        rows = (
            self.session.query(ChannelDB.id, TagDB.value)
            .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
            .join(TagDB, TagDB.id == ContentTagDB.tag_id)
            .filter(ChannelDB.id.in_(channel_ids), TagDB.type == "collection")
            .order_by(TagDB.value)
            .all()
        )
        out: Dict[str, str] = {}
        for channel_id, value in rows:
            out.setdefault(channel_id, value)
        return out

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
            self.session.query(ChannelDB.id)
            .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
            .filter(ContentTagDB.tag_id == tag.id)
            .all()
        )
        return [r.id for r in rows]

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
        channel_key = self._channel_key(channel_id)
        if channel_key is None:
            return 0
        deleted = (
            self.session.query(ContentTagDB)
            .filter_by(channel_key=channel_key, source="generated")
            .delete(synchronize_session="fetch")
        )
        return deleted

    def delete_generated_for_channels(self, channel_ids: List[str]) -> int:
        """Delete ``source="generated"`` content-tag links for ALL channels in *channel_ids*.

        Single bulk DELETE for an entire batch, replacing N individual
        :meth:`delete_generated_for_channel` calls.  User tags
        (``source="user"``) are never touched.

        Args:
            channel_ids: The ``ChannelDB.id`` values whose generated tags should
                be cleared.  An empty list is a no-op.

        Returns:
            Total number of rows deleted.
        """
        if not channel_ids:
            return 0
        channel_keys = list(self._channel_keys(channel_ids).values())
        if not channel_keys:
            return 0
        deleted = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_key.in_(channel_keys),
                ContentTagDB.source == "generated",
            )
            .delete(synchronize_session="fetch")
        )
        # Measured tags are not re-derived by name parsing; put them back so a
        # re-tag never forgets what a played/probed stream proved (PLAYED-4).
        self.reapply_measured_tags(channel_ids)
        return deleted

    def apply_measured_tags(self, channel_id: str, info: dict | None) -> None:
        """Write the tags a stream measurement proves (``played_tracks`` feeder)."""
        from metatv.core.stream_info import measured_tags
        tags = measured_tags(info)
        if tags and self._channel_key(channel_id) is not None:   # episodes have no channel row
            self.set_content_tags(channel_id, tags)

    def reapply_measured_tags(self, channel_ids: List[str]) -> None:
        """Re-write measured tags for those of *channel_ids* that have a measurement."""
        from metatv.core.database import StreamInfoDB
        rows = (self.session.query(StreamInfoDB.channel_id, StreamInfoDB.info)
                .filter(StreamInfoDB.channel_id.in_(list(channel_ids))).all())
        for channel_id, info in rows:
            self.apply_measured_tags(channel_id, info)

    def set_content_tags_bulk(
        self,
        mapping: Dict[str, List[Tuple[str, str, str]]],
        source: str = "generated",
    ) -> None:
        """Upsert content-tag links for ALL channels in *mapping* in one bulk statement.

        Replaces N individual :meth:`set_content_tags` calls (one per channel)
        with two SQL statements for the entire batch:

        1. A single bulk SELECT to load existing links (all channels × all
           tag_ids in the batch).
        2. A single ``INSERT … ON CONFLICT DO UPDATE`` upsert for every
           ``(channel_id, tag_id, source)`` triple in the batch.

        Only rows with the given ``source`` are touched; rows with a different
        source (e.g. ``"user"``) are left unchanged.

        Args:
            mapping: ``{channel_id: [(type, value, feeder), ...]}`` — the
                decomposed tag tuples for each channel in the batch.  Channels
                with an empty list are silently skipped (no rows emitted).
            source: Provenance label; ``"generated"`` or ``"user"``.
        """
        if not mapping:
            return

        from sqlalchemy.dialects.sqlite import insert as _sqlite_insert

        key_by_cid = self._channel_keys(mapping.keys())
        unresolved = mapping.keys() - key_by_cid.keys()
        if unresolved:
            logger.warning(
                "set_content_tags_bulk: no channel_key for {} channel_id(s) — skipping them",
                len(unresolved),
            )

        # ── Step 1: resolve all tag ids (process-level cache → typically 0 DB
        # round-trips after warmup).  Build a flat list of
        # (channel_key, tag_id, feeder) triples across the whole batch.
        channel_tag_feeders: List[Tuple[int, int, str]] = []  # (ckey, tid, feeder)
        for channel_id, tags in mapping.items():
            channel_key = key_by_cid.get(channel_id)
            if not tags or channel_key is None:
                continue
            for tag_type, tag_value, feeder in tags:
                tag_id = self.get_or_create_tag_id(tag_type, tag_value)
                channel_tag_feeders.append((channel_key, tag_id, feeder))

        if not channel_tag_feeders:
            return

        # ── Step 2: one SELECT for ALL existing links in the batch.
        # We need to merge new feeders with any feeders already on existing rows
        # (the caller deleted generated rows before calling us during backfill,
        # so this mainly catches the incremental-tagging path where we might
        # revisit a channel).  Collect needed channel_keys and tag_ids.
        all_ckeys = list({ck for ck, _, _ in channel_tag_feeders})
        all_tids = list({tid for _, tid, _ in channel_tag_feeders})

        existing_rows = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_key.in_(all_ckeys),
                ContentTagDB.tag_id.in_(all_tids),
                ContentTagDB.source == source,
            )
            .all()
        )
        # existing_feeders[(channel_key, tag_id)] → list of feeders already on row
        existing_feeders: Dict[Tuple[int, int], List[str]] = {
            (row.channel_key, row.tag_id): list(row.feeders or [])
            for row in existing_rows
        }

        # ── Step 3: merge feeders per (channel_key, tag_id) across the whole batch.
        # merged[(channel_key, tag_id)] → deduplicated feeder list
        merged: Dict[Tuple[int, int], List[str]] = {}
        for ck, tid, feeder in channel_tag_feeders:
            key = (ck, tid)
            if key not in merged:
                merged[key] = list(existing_feeders.get(key, []))
            if feeder not in merged[key]:
                merged[key].append(feeder)

        # ── Step 4: single bulk upsert for the entire batch. ``confidence`` is
        # derived, not stored (see _compute_confidence).
        rows = [
            {
                "channel_key": ck,
                "tag_id": tid,
                "source": source,
                "feeders": feeders,
            }
            for (ck, tid), feeders in merged.items()
        ]

        try:
            stmt = _sqlite_insert(ContentTagDB).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_key", "tag_id", "source"],
                set_={"feeders": stmt.excluded.feeders},
            )
            self.session.execute(stmt)
            self.session.flush()
        except Exception:
            logger.warning(
                "set_content_tags_bulk: integrity error for batch of {} channels — skipping",
                len(mapping),
            )
            self.session.rollback()

    def channel_ids_for_content_types(self, values: Set[str]) -> Set[str]:
        """Return channel ids carrying a ``content_type`` tag whose value ∈ *values*.

        The Python id-set twin of
        ``filter_utils.tag_content_type_exclusion_criterion`` (the SQL NOT EXISTS):
        materialises the *excluded* channel-id set for the row-by-row surfaces that
        cannot express a correlated subquery over ChannelDB rows / DTOs — the
        channel list (``_apply_python_exclusions``), EPG On-Now, and details "Other
        Versions".  Both ``source="generated"`` and ``source="user"`` tags count.

        The population is small (content_type is a niche trailing marker), so this
        is a bounded, indexed lookup — safe to materialise off the UI thread.

        Args:
            values: The ``content_type`` slugs to resolve (e.g.
                ``{"ai_generated", "ai_voiceover"}``).  Empty → empty set.

        Returns:
            The set of ``channel_id`` strings carrying any of those content_type
            tags.  Empty when *values* is empty or nothing matches.
        """
        if not values:
            return set()
        rows = (
            self.session.query(ChannelDB.id)
            .join(ContentTagDB, ContentTagDB.channel_key == ChannelDB.channel_key)
            .join(TagDB, TagDB.id == ContentTagDB.tag_id)
            .filter(TagDB.type == "content_type", TagDB.value.in_(list(values)))
            .distinct()
            .all()
        )
        return {r.id for r in rows}
