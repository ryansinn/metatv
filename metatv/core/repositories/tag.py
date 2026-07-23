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

Performance note (tag-write throughput):
    ``get_or_create_tag`` is backed by a process-level cache (``_TAG_ID_CACHE``)
    guarded by ``_TAG_ID_LOCK``.  The tag vocabulary is small (a few thousand
    distinct ``(type, value)`` pairs) and strictly append-only — nothing ever
    deletes or renames ``TagDB`` rows — so caching ``(type, value) → id`` is safe
    across the entire process lifetime.  On a cache hit the SELECT is skipped
    entirely; on a miss a single SELECT-or-INSERT is executed and the result is
    cached.

    ``set_content_tags`` uses a single SQLite ``INSERT … ON CONFLICT(channel_id,
    tag_id, source) DO UPDATE`` upsert (via ``sqlalchemy.dialects.sqlite.insert``)
    instead of per-link SELECT + conditional ``session.add``.  This collapses
    ~N SELECT + N INSERT/UPDATE statements into one bulk statement per call, cutting
    query overhead by ~10× for typical 5-tag channels.

    Combined the two changes reduce the per-500-channel batch from ~2s to < 0.2s
    on a Ryzen 9 7940HS + NVMe.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Set, Tuple

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy import exists

from metatv.core.database import ContentTagDB, TagDB

# Confidence denominator — three independent feeders → full confidence.
_FEEDER_DENOMINATOR: int = 3

# ---------------------------------------------------------------------------
# Rating axis — the recipe's first non-tag ingredient
# ---------------------------------------------------------------------------
# The rating shown on Discover / Now-Plating cards comes from
# ``ChannelDB.raw_data["rating"]`` (see ``discovery_engine._raw_rating`` /
# ``_to_card``): a channel is *display-rated* only when that value parses to a
# float strictly between 0 and 10.  Anything else — a missing key, 0, a
# non-numeric string, or >= 10 — renders as UNRATED (no star).  The recipe's
# rating-range ingredient filters on this SAME field at the SAME layer.  The
# scale endpoints + full-range test live in ``core.recipe_state`` (one source of
# truth, shared with the slider widget).
from metatv.core.recipe_state import (  # noqa: E402
    RATING_SCALE_MAX as _RATING_MAX,
    RATING_SCALE_MIN as _RATING_MIN,
    rating_range_is_full as _rating_range_is_full,
)

# ---------------------------------------------------------------------------
# Process-level tag-id cache
# ---------------------------------------------------------------------------
# Tags are append-only (nothing deletes or renames TagDB rows), so caching
# (type, value) → id is safe for the entire process lifetime.  The loader
# worker thread AND the backfill thread both call get_or_create_tag, so the
# lock is mandatory.
_TAG_ID_CACHE: Dict[Tuple[str, str], int] = {}
_TAG_ID_LOCK: threading.Lock = threading.Lock()


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

        The result id is cached in the process-level ``_TAG_ID_CACHE`` dict so
        that repeated calls for the same ``(type, value)`` pair skip the SELECT
        entirely.  The cache is safe because ``TagDB`` rows are append-only —
        nothing ever deletes or renames them.

        Args:
            type: Namespace string, e.g. ``"region"``, ``"genre"``.
            value: Canonical value, e.g. ``"US"``, ``"Drama"``.

        Returns:
            The persistent ``TagDB`` row (id is populated after flush).
        """
        cache_key = (type, value)

        # Fast path — cache hit, no DB round-trip needed.
        with _TAG_ID_LOCK:
            cached_id = _TAG_ID_CACHE.get(cache_key)

        if cached_id is not None:
            # Re-attach to the current session via identity map (free if already loaded,
            # one primary-key lookup otherwise — far cheaper than a filter query).
            row = self.session.get(TagDB, cached_id)
            if row is not None:
                return row
            # Cache entry pointed at a row that doesn't exist in this DB (e.g. a
            # test that swapped the DB file).  Fall through to the slow path and
            # refresh the cache.
            with _TAG_ID_LOCK:
                _TAG_ID_CACHE.pop(cache_key, None)

        # Slow path — not cached yet: SELECT-or-INSERT, then cache the id.
        row = (
            self.session.query(TagDB)
            .filter_by(type=type, value=value)
            .first()
        )
        if row is None:
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

        with _TAG_ID_LOCK:
            _TAG_ID_CACHE[cache_key] = row.id

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

        # Step 1: resolve tag ids (cached — typically 0 DB round-trips after warmup).
        tag_ids: List[Tuple[int, str]] = []  # (tag_id, feeder)
        for tag_type, tag_value, feeder in tags:
            tag = self.get_or_create_tag(tag_type, tag_value)
            tag_ids.append((tag.id, feeder))

        # Step 2: load all existing links for this channel+source in one SELECT.
        existing_tag_ids = [tid for tid, _ in tag_ids]
        existing_rows = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_id == channel_id,
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

        # Step 4: single bulk upsert — INSERT … ON CONFLICT(channel_id, tag_id, source)
        # DO UPDATE SET feeders=excluded.feeders, confidence=excluded.confidence.
        # The unique constraint ``uq_content_tag`` is on (channel_id, tag_id, source).
        rows = [
            {
                "channel_id": channel_id,
                "tag_id": tag_id,
                "source": source,
                "feeders": feeders,
                "confidence": _compute_confidence(feeders),
            }
            for tag_id, feeders in merged.items()
        ]

        try:
            stmt = _sqlite_insert(ContentTagDB).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_id", "tag_id", "source"],
                set_={
                    "feeders": stmt.excluded.feeders,
                    "confidence": stmt.excluded.confidence,
                },
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
                ContentTagDB.confidence,
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(ContentTagDB.channel_id == channel_id)
            .order_by(TagDB.type, TagDB.value)
            .all()
        )

        dtos: List[ChannelTagDTO] = []
        for tag_type, value, feeders_raw, confidence in rows:
            feeder_list: List[str] = feeders_raw if isinstance(feeders_raw, list) else []
            # source_given = True when any feeder is a direct provider-field reader
            source_given = any(f in _SOURCE_GIVEN_FEEDERS for f in feeder_list)
            dtos.append(ChannelTagDTO(
                facet_type=tag_type,
                value=value,
                source_given=source_given,
                confidence=float(confidence or 0.0),
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
        deleted = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_id.in_(channel_ids),
                ContentTagDB.source == "generated",
            )
            .delete(synchronize_session="fetch")
        )
        return deleted

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

        # ── Step 1: resolve all tag ids (process-level cache → typically 0 DB
        # round-trips after warmup).  Build a flat list of
        # (channel_id, tag_id, feeder) triples across the whole batch.
        channel_tag_feeders: List[Tuple[str, int, str]] = []  # (cid, tid, feeder)
        for channel_id, tags in mapping.items():
            if not tags:
                continue
            for tag_type, tag_value, feeder in tags:
                tag = self.get_or_create_tag(tag_type, tag_value)
                channel_tag_feeders.append((channel_id, tag.id, feeder))

        if not channel_tag_feeders:
            return

        # ── Step 2: one SELECT for ALL existing links in the batch.
        # We need to merge new feeders with any feeders already on existing rows
        # (the caller deleted generated rows before calling us during backfill,
        # so this mainly catches the incremental-tagging path where we might
        # revisit a channel).  Collect needed channel_ids and tag_ids.
        all_cids = list({cid for cid, _, _ in channel_tag_feeders})
        all_tids = list({tid for _, tid, _ in channel_tag_feeders})

        existing_rows = (
            self.session.query(ContentTagDB)
            .filter(
                ContentTagDB.channel_id.in_(all_cids),
                ContentTagDB.tag_id.in_(all_tids),
                ContentTagDB.source == source,
            )
            .all()
        )
        # existing_feeders[(channel_id, tag_id)] → list of feeders already on row
        existing_feeders: Dict[Tuple[str, int], List[str]] = {
            (row.channel_id, row.tag_id): list(row.feeders or [])
            for row in existing_rows
        }

        # ── Step 3: merge feeders per (channel_id, tag_id) across the whole batch.
        # merged[(channel_id, tag_id)] → deduplicated feeder list
        merged: Dict[Tuple[str, int], List[str]] = {}
        for cid, tid, feeder in channel_tag_feeders:
            key = (cid, tid)
            if key not in merged:
                merged[key] = list(existing_feeders.get(key, []))
            if feeder not in merged[key]:
                merged[key].append(feeder)

        # ── Step 4: single bulk upsert for the entire batch.
        rows = [
            {
                "channel_id": cid,
                "tag_id": tid,
                "source": source,
                "feeders": feeders,
                "confidence": _compute_confidence(feeders),
            }
            for (cid, tid), feeders in merged.items()
        ]

        try:
            stmt = _sqlite_insert(ContentTagDB).values(rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["channel_id", "tag_id", "source"],
                set_={
                    "feeders": stmt.excluded.feeders,
                    "confidence": stmt.excluded.confidence,
                },
            )
            self.session.execute(stmt)
            self.session.flush()
        except Exception:
            logger.warning(
                "set_content_tags_bulk: integrity error for batch of {} channels — skipping",
                len(mapping),
            )
            self.session.rollback()

    # ------------------------------------------------------------------
    # Faceted stats
    # ------------------------------------------------------------------

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
            self.session.query(ContentTagDB.channel_id)
            .join(TagDB, TagDB.id == ContentTagDB.tag_id)
            .filter(TagDB.type == "content_type", TagDB.value.in_(list(values)))
            .distinct()
            .all()
        )
        return {r.channel_id for r in rows}

    def _scope_to_visible_channels(self, query, channel_id_col,
                                   excluded_provider_ids: Optional[List[str]] = None,
                                   excluded_prefixes: Optional[Set[str]] = None,
                                   excluded_categories: Optional[Set[str]] = None,
                                   excluded_tag_content_types: Optional[Set[str]] = None):
        """Join ``ChannelDB`` and restrict a tag query to *visible* channels.

        The single definition of "visible channel" for the tag repository's
        faceted queries: drop individually-hidden channels (``is_hidden``) and
        provider category headers (names beginning ``##``), exclude any provider
        in *excluded_provider_ids* (inactive ∪ expired — pass
        ``ProviderRepository.get_hidden_provider_ids()``), and apply the caller's
        Global Exclusions (*excluded_prefixes* / *excluded_categories*) so the
        recipe never surfaces content the user has globally banished.

        Consolidates the predicate that was previously inlined in
        ``get_facet_value_counts`` / ``get_facet_summary`` /
        ``get_tag_counts_for_facet`` (and was missing entirely from the faceted
        result engine, leaking hidden-source channels into recipe YIELDS).
        Tracked for cross-repo unification as task #59.

        **Global-exclusion semantics** — the SQL twin of the canonical predicate
        (``filter_utils.is_channel_excluded``, "language wins over region"): a
        channel is dropped when its ``detected_prefix`` is in *excluded_prefixes*,
        or — only when it has NO prefix — when its ``detected_region`` is; an
        un-excluded language prefix keeps the row despite an excluded region tag.
        The keep-condition is produced by ``filter_utils.channel_exclusion_criterion``
        so this surface never forks a parallel prefix/region rule (single
        chokepoint).  ``user_category`` in *excluded_categories* is a separate
        drop.  This is a pure caller-supplied scope: the engine never reads
        ``Config`` (DR-0007 — the control layer resolves the sets and passes them in).

        **NULL trap:** ``col NOT IN (...)`` evaluates to NULL (false) when
        ``col IS NULL``, which would wrongly drop untagged channels.  The
        criterion helper handles this for the prefix/region pair; the
        ``user_category`` filter uses the same ``or_(col.is_(None), col.notin_)``
        shape so a NULL category is kept.

        Args:
            query: The SQLAlchemy query to scope.
            channel_id_col: The column expression carrying the channel id to
                join ``ChannelDB.id`` against (e.g. ``ContentTagDB.channel_id``
                or an aliased equivalent).
            excluded_provider_ids: Provider IDs to additionally exclude.  An
                empty list still applies the is_hidden / ``##`` scope; ``None``
                also applies it — callers that want *no* scoping simply don't
                call this helper.
            excluded_prefixes: Global-exclusion prefix/region codes (the union of
                ``global_filter_excluded_categories`` and
                ``global_filter_excluded_prefixes``), matched by the canonical
                predicate (prefix wins, region is the no-prefix fallback).
                ``None``/empty → no prefix scope.
            excluded_categories: Global-exclusion user-category labels
                (``global_filter_excluded_user_categories``) matched against
                ``user_category``.  ``None``/empty → no category scope.
            excluded_tag_content_types: Global-exclusion ``content_type`` tag values
                (``global_filter_excluded_tag_content_types``) — drop channels
                carrying any of these via
                ``filter_utils.tag_content_type_exclusion_criterion`` (NOT EXISTS).
                ``None``/empty → no content-type scope.

        Returns:
            The query with the visibility join + filters applied.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.filter_utils import (
            channel_exclusion_criterion,
            tag_content_type_exclusion_criterion,
        )
        from sqlalchemy import or_

        query = query.join(ChannelDB, ChannelDB.id == channel_id_col).filter(
            ChannelDB.is_hidden == False,       # noqa: E712
            ChannelDB.name.notlike("##%"),      # exclude provider category headers
        )
        if excluded_provider_ids:
            query = query.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        if excluded_prefixes:
            # SQL twin of is_channel_excluded — keeps rows the canonical predicate
            # would NOT exclude (language wins over region).
            query = query.filter(channel_exclusion_criterion(set(excluded_prefixes), ChannelDB))
        if excluded_tag_content_types:
            # SQL twin of the content-provenance rule — drop channels carrying an
            # excluded content_type tag (NOT EXISTS; P1-6 family, single chokepoint).
            query = query.filter(
                tag_content_type_exclusion_criterion(
                    set(excluded_tag_content_types), ChannelDB.id
                )
            )
        if excluded_categories:
            _cats = list(excluded_categories)
            query = query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ChannelDB.user_category.notin_(_cats)),
            )
        return query

    def get_facet_value_counts(
        self,
        excluded_provider_ids: Optional[List[str]] = None,
    ) -> dict[str, dict[str, int]]:
        """Return per-facet value counts for the filter panel.

        Executes a single SQL GROUP BY over ``content_tags JOIN tags JOIN channels``
        scoped to visible (is_hidden=False), non-category-header channels on active
        sources. No Python-side materialisation — safe over 1M+ rows.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources).  Pass ``ProviderRepository.get_hidden_provider_ids()``.

        Returns:
            Nested dict ``{facet_type: {value: channel_count}}`` where
            ``channel_count`` is the number of **distinct channels** carrying that
            (type, value) tag from active sources.  Only types with at least one
            count are included; zero-count values are omitted.
        """
        from sqlalchemy import func as _func

        q = (
            self.session.query(
                TagDB.type,
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_id)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_id, excluded_provider_ids
        ).group_by(TagDB.type, TagDB.value)

        result: dict[str, dict[str, int]] = {}
        for tag_type, value, cnt in q.all():
            if cnt > 0:
                result.setdefault(tag_type, {})[value] = int(cnt)
        return result

    # ---------------------------------------------------------------------------
    # Canonical facet display order for the Recipe builder pantry sidebar
    # ---------------------------------------------------------------------------
    #
    # Controls the order returned by get_facet_summary().  Facets not present
    # in this list (e.g. future namespaces) are appended at the end in
    # alphabetical order so they are never silently dropped.
    _FACET_ORDER: tuple[str, ...] = (
        "genre",
        "language",
        "region",
        "platform",
        "decade",
        "quality",
        "collection",
    )

    def get_facet_summary(
        self,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
    ) -> list:
        """Return per-facet distinct-value counts for the Recipe builder Pantry sidebar.

        For each tag namespace (type) that has at least one value carried by
        active-source channels, returns a FacetSummaryDTO with the count of
        *distinct* tag values.  Results are ordered by the canonical display
        order (_FACET_ORDER) with any unseen namespaces appended alphabetically.

        Executes a single SQL GROUP BY over content_tags JOIN tags JOIN channels
        scoped to visible, non-header channels on active sources.  No Python-side
        materialisation — safe over 1M+ rows.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources). Pass the result of
                ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).  Caller-supplied — the
                engine never reads Config.
            excluded_categories: Global-exclusion ``user_category`` labels to
                drop (see :meth:`_scope_to_visible_channels`).

        Returns:
            List of ``FacetSummaryDTO``, in canonical facet display order.
            Zero-count facets are omitted.  No ORM objects are returned.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import FacetSummaryDTO

        q = (
            self.session.query(
                TagDB.type,
                _func.count(_func.distinct(TagDB.value)).label("distinct_vals"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_id, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
        ).group_by(TagDB.type)

        raw: dict[str, int] = {}
        for tag_type, distinct_vals in q.all():
            if distinct_vals > 0:
                raw[tag_type] = int(distinct_vals)

        # Order by canonical facet list; append unseen types alphabetically.
        ordered_types: list[str] = list(self._FACET_ORDER)
        for extra in sorted(raw.keys()):
            if extra not in ordered_types:
                ordered_types.append(extra)

        return [
            FacetSummaryDTO(facet_type=ft, distinct_values=raw[ft])
            for ft in ordered_types
            if ft in raw
        ]

    def get_tag_counts_for_facet(
        self,
        facet_type: str,
        excluded_provider_ids: Optional[List[str]] = None,
        limit: Optional[int] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
    ) -> list:
        """Return per-value channel counts for ONE facet type, sorted by count DESC.

        For the given ``facet_type`` (e.g. ``"genre"``), returns each distinct
        tag value plus the number of active-source channels carrying it.  Sorted
        by channel_count DESC so the weighted-cloud widget can size type by weight.

        Executes a single SQL GROUP BY over content_tags JOIN tags JOIN channels
        scoped to visible, non-header channels on active sources.  No Python-side
        materialisation — safe over 1M+ rows.

        Args:
            facet_type: The tag namespace to query (e.g. ``"genre"``).
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources). Pass the result of
                ``ProviderRepository.get_hidden_provider_ids()``.
            limit: Optional cap on the number of results returned.  When
                ``None``, all values are returned.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).  Caller-supplied — the
                engine never reads Config.
            excluded_categories: Global-exclusion ``user_category`` labels to
                drop (see :meth:`_scope_to_visible_channels`).

        Returns:
            List of ``TagCountDTO``, sorted by ``channel_count`` DESC.
            Zero-count values are omitted.  No ORM objects are returned.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import TagCountDTO

        q = (
            self.session.query(
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_id)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            .filter(TagDB.type == facet_type)
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_id, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
        ).group_by(TagDB.value).order_by(
            _func.count(_func.distinct(ContentTagDB.channel_id)).desc()
        )
        if limit is not None:
            q = q.limit(limit)

        return [
            TagCountDTO(value=value, channel_count=int(cnt))
            for value, cnt in q.all()
            if cnt > 0
        ]

    def search_tag_values_across_facets(
        self,
        query: str,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        limit: int = 300,
    ) -> list:
        """Search tag VALUES across ALL facet types, case-insensitively, sorted by count.

        The cross-facet sibling of :meth:`get_tag_counts_for_facet`: instead of
        restricting to one ``facet_type``, this scans every namespace and returns
        each ``(facet_type, value)`` group whose value contains *query* (a
        case-insensitive substring), plus the number of active-source channels
        carrying it.  Powers the Recipe builder's Pantry search — typing "comedy"
        surfaces "Comedy" (genre), "Comedy Central" (collection), etc. all at once
        in the center cloud, color-coded by facet.

        Scoping is IDENTICAL to :meth:`get_tag_counts_for_facet` (the same global
        exclusion sets + ``excluded_provider_ids`` via
        :meth:`_scope_to_visible_channels`), so the cross-facet counts agree with
        the per-facet cloud and the rest of the recipe view.

        Executes a single SQL GROUP BY over content_tags JOIN tags JOIN channels.
        No Python-side materialisation — safe over 1M+ rows.

        Args:
            query: Case-insensitive substring to match against the tag value.  An
                empty / whitespace-only query returns ``[]`` (no search).
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired
                sources).  Pass ``ProviderRepository.get_hidden_provider_ids()``.
            excluded_prefixes: Global-exclusion prefix/region codes to drop (see
                :meth:`_scope_to_visible_channels`).  Caller-supplied — the engine
                never reads Config.
            excluded_categories: Global-exclusion ``user_category`` labels to drop
                (see :meth:`_scope_to_visible_channels`).
            limit: Cap on the number of ``(facet_type, value)`` groups returned
                (default 300) so the cloud stays sane on a broad query.  Applied
                after sorting by count DESC, so the most popular matches win.

        Returns:
            List of ``TagSearchResultDTO`` (facet_type, value, channel_count),
            sorted by ``channel_count`` DESC.  Zero-count groups are omitted.
            No ORM objects are returned.
        """
        from sqlalchemy import func as _func
        from metatv.core.repositories.dtos import TagSearchResultDTO

        q_str = (query or "").strip()
        if not q_str:
            return []
        pattern = f"%{q_str.lower()}%"

        q = (
            self.session.query(
                TagDB.type,
                TagDB.value,
                _func.count(_func.distinct(ContentTagDB.channel_id)).label("cnt"),
            )
            .join(ContentTagDB, ContentTagDB.tag_id == TagDB.id)
            # Lower-cased LIKE = portable case-insensitive substring match.
            .filter(_func.lower(TagDB.value).like(pattern))
        )
        q = self._scope_to_visible_channels(
            q, ContentTagDB.channel_id, excluded_provider_ids,
            excluded_prefixes, excluded_categories, excluded_tag_content_types,
        ).group_by(TagDB.type, TagDB.value).order_by(
            _func.count(_func.distinct(ContentTagDB.channel_id)).desc()
        )
        if limit is not None:
            q = q.limit(limit)

        return [
            TagSearchResultDTO(
                facet_type=tag_type, value=value, channel_count=int(cnt)
            )
            for tag_type, value, cnt in q.all()
            if cnt > 0
        ]

    # ------------------------------------------------------------------
    # Faceted query engine
    # ------------------------------------------------------------------

    def _faceted_channel_id_query(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        rating_range: Optional[Tuple[float, float]] = None,
    ):
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
            excluded_provider_ids: When not ``None``, restrict the result to
                *visible* channels via :meth:`_scope_to_visible_channels` —
                dropping individually-hidden channels and ``##`` category
                headers, and excluding the given providers (inactive ∪ expired;
                pass ``ProviderRepository.get_hidden_provider_ids()``).  This is
                the same scope the pantry/cloud facet counts use, so recipe
                YIELDS agrees with the cloud.  ``None`` (default) keeps the
                method scope-agnostic for callers that scope another way.
            excluded_prefixes / excluded_categories: Global-exclusion sets (see
                :meth:`_scope_to_visible_channels`).  Applied only when
                *excluded_provider_ids* is not ``None`` (i.e. when the caller has
                opted into the visible-channel scope).  Caller-supplied — the
                engine never reads Config.
            rating_range: Optional ``(min, max)`` on the 0–10 rating scale,
                filtered against ``ChannelDB.raw_data["rating"]`` (the same field
                that drives the card star).  **NULL semantics:** a floor of 0
                (``min <= 0``) keeps unrated content (missing / 0 / non-numeric /
                >= 10 ratings); any ``min > 0`` requires a genuine rating in the
                band and therefore drops unrated content.  A full-span range
                (``min <= 0 and max >= 10``) and ``None`` add no filter at all.

        Returns:
            An unexecuted SQLAlchemy query selecting ``DISTINCT channel_id`` for
            every channel satisfying the constraints.  Callers choose how to
            consume it: ``.all()`` for the id set, ``.count()`` for a SQL count,
            ``.limit(n)`` for a bounded sample — so a count or preview never
            materialises the full match set.
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

        # Anchor the driving query directly on the first constrained include
        # facet's tag membership (JOIN tags … WHERE type/value), so SQLite seeks
        # the tag_id index and the driving scan is bounded to that facet's
        # channels — instead of `SELECT DISTINCT channel_id FROM content_tags`
        # enumerating the entire content_tags table (1M+ rows) and EXISTS-checking
        # each.  The remaining include facets stay as correlated EXISTS subqueries
        # (AND across facets), and the exclude block (NOT EXISTS) is unchanged.
        # The result set is identical — DISTINCT collapses a channel's multiple
        # anchor-tag rows; only the access path changes.  This took a single-facet
        # recipe count/sample from ~7.5s to ~0.3-0.5s on a 3GB / 1.2M-tag library.
        outer = aliased(ContentTagDB, flat=True)
        if constrained_facets:
            anchor_ftype, anchor_values = constrained_facets[0]
            remaining_facets = constrained_facets[1:]
            t_anchor = aliased(TagDB, flat=True)
            query = (
                self.session.query(outer.channel_id)
                .join(t_anchor, t_anchor.id == outer.tag_id)
                .filter(
                    t_anchor.type == anchor_ftype,
                    t_anchor.value.in_(list(anchor_values)),
                )
                .distinct()
            )
        else:
            remaining_facets = []
            query = self.session.query(outer.channel_id).distinct()

        # Scope to a caller-provided pre-filter if given.
        if base_channel_ids is not None:
            query = query.filter(outer.channel_id.in_(base_channel_ids))

        # Scope to visible channels on active sources when requested (recipe
        # YIELDS uses this so its count matches the pantry/cloud facet counts).
        # Global Exclusions ride along on the same scope so YIELDS/preview never
        # surface content the user has globally banished.
        if excluded_provider_ids is not None:
            query = self._scope_to_visible_channels(
                query, outer.channel_id, excluded_provider_ids,
                excluded_prefixes, excluded_categories, excluded_tag_content_types,
            )

        # --- include facets: one EXISTS per facet (AND across facets) ---
        #
        # For each facet: EXISTS (
        #   SELECT 1 FROM content_tags AS ct_i
        #   JOIN tags AS t_i ON t_i.id = ct_i.tag_id
        #   WHERE ct_i.channel_id = outer.channel_id
        #     AND t_i.type = <ftype>
        #     AND t_i.value IN (<allowed_values>)
        # )

        for ftype, allowed_values in remaining_facets:
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

        # --- rating axis: correlated EXISTS on ChannelDB.raw_data["rating"] ---
        #
        # EXISTS (
        #   SELECT 1 FROM channels AS ch_r
        #   WHERE ch_r.id = outer.channel_id AND <rating band>
        # )
        #
        # Skipped entirely for a full-span (or None) range — no extra scan.
        if not _rating_range_is_full(rating_range):
            from metatv.core.database import ChannelDB
            from sqlalchemy import (
                and_ as _and,
                cast as _cast,
                Float as _Float,
                func as _func,
                or_ as _or,
            )

            lo, hi = rating_range  # type: ignore[misc]  # guarded non-full above
            ch_r = aliased(ChannelDB, flat=True)
            # SQLite json_extract → NULL when the "rating" key is absent;
            # CAST(... AS REAL) parses a numeric string ("7.5" → 7.5) and yields
            # 0.0 for a non-numeric one — mirroring discovery_engine._raw_rating.
            rating_num = _cast(_func.json_extract(ch_r.raw_data, "$.rating"), _Float)
            # Display-rated iff 0 < r < 10 (matches the card-star predicate).
            is_rated = _and(rating_num > 0, rating_num < 10)
            if lo > _RATING_MIN:
                # A real floor → require a genuine rating within [lo, hi].
                # Unrated content is dropped (its rating can't satisfy >= lo).
                band = _and(is_rated, rating_num >= lo, rating_num <= hi)
            else:
                # Full-left floor (min == 0) → INCLUDE unrated content
                # (NULL / <= 0 / >= 10) PLUS any genuine rating <= the ceiling.
                unrated = _or(rating_num.is_(None), rating_num <= 0, rating_num >= 10)
                band = _or(unrated, _and(is_rated, rating_num <= hi))
            rating_subq = (
                sa_select(ch_r.id)
                .where(ch_r.id == outer.channel_id, band)
                .correlate(outer)
            )
            query = query.filter(exists(rating_subq))

        return query

    def get_channel_ids_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        rating_range: Optional[Tuple[float, float]] = None,
    ) -> set[str]:
        """Return the set of channel ids matching the faceted constraints.

        Standard faceted search (OR within a facet, AND across facets, NOT for
        excludes).  See :meth:`_faceted_channel_id_query` for the full semantics
        and the meaning of *base_channel_ids* / *excluded_provider_ids* /
        *excluded_prefixes* / *excluded_categories* / *rating_range* (incl. its
        NULL/unrated semantics).

        Note: this materialises *every* matching id.  For a count or a small
        preview use :meth:`count_channels_by_tag_facets` /
        :meth:`sample_channel_names_by_tag_facets`, which stay in SQL.
        """
        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            rating_range=rating_range,
        )
        return {row.channel_id for row in query.all()}

    def count_channels_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        rating_range: Optional[Tuple[float, float]] = None,
        collapse_variants: bool = False,
    ) -> int:
        """Count channels matching the faceted constraints — entirely in SQL.

        Issues a single ``SELECT count(*) FROM (SELECT DISTINCT channel_id …)``,
        so a 170k-match facet costs one integer round-trip, not 170k id strings
        crossing into Python.  Arguments match :meth:`_faceted_channel_id_query`.

        Args:
            collapse_variants: When True, count DISTINCT content_key groups
                (one per collapsed production) using
                ``COUNT(DISTINCT COALESCE(content_key, 'id:' || id))``.
                When False (default), counts raw matching channel rows.  The
                collapsed count matches the number of cards returned by
                ``sample_channels_by_tag_facets(collapse_variants=True)``.
        """
        from metatv.core.database import ChannelDB
        from sqlalchemy import func as _func, text as _text

        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            rating_range=rating_range,
        )
        if collapse_variants:
            # COUNT(DISTINCT group_key) — one per collapsed production.
            # The match query selects distinct channel_ids; we join ChannelDB to
            # read content_key, then count distinct group keys.
            matching = query.subquery()
            _group_key = _func.coalesce(
                ChannelDB.content_key,
                _func.concat("id:", ChannelDB.id),
            )
            return (
                self.session.query(
                    _func.count(_func.distinct(_group_key))
                )
                .join(matching, matching.c.channel_id == ChannelDB.id)
                .scalar()
            ) or 0
        return query.count()

    def sample_channel_names_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        rating_range: Optional[Tuple[float, float]] = None,
        limit: int = 20,
    ) -> list[str]:
        """Return up to *limit* channel display names matching the constraints.

        Takes a bounded ``LIMIT`` slice of the match query (the full set is never
        materialised), then resolves names for those ``<=limit`` ids in a second
        tiny query.  Used for the recipe "now plating" preview.
        """
        from metatv.core.database import ChannelDB

        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            rating_range=rating_range,
        )
        ids = [row.channel_id for row in query.limit(limit).all()]
        if not ids:
            return []
        rows = (
            self.session.query(ChannelDB.name)
            .filter(ChannelDB.id.in_(ids))
            .order_by(ChannelDB.name)
            .all()
        )
        return [name for (name,) in rows]


    # ------------------------------------------------------------------
    # Variant-collapse helper (shared chokepoint for dedup Slice 2)
    # ------------------------------------------------------------------

    # Quality rank constants used in the representative-pick CASE expression.
    # Lower rank = higher quality = preferred representative.
    # All tiers: 4K/8K/UHD=0, FHD/HDR=1, HD=2, everything else (SD/LQ/NULL)=3.
    _QUALITY_RANK_CASE = (
        "CASE detected_quality"
        " WHEN '4K'  THEN 0"
        " WHEN '8K'  THEN 0"
        " WHEN 'UHD' THEN 0"
        " WHEN 'FHD' THEN 1"
        " WHEN 'HDR' THEN 1"
        " WHEN 'HD'  THEN 2"
        " ELSE 3 END"
    )

    def _build_collapsed_sample_query(
        self,
        matching_subq,
        *,
        name_filter: Optional[str] = None,
    ):
        """Wrap *matching_subq* (channel ids) with window-function collapse.

        Applies SQLite ROW_NUMBER() + COUNT() window functions partitioned by
        ``COALESCE(content_key, 'id:' || id)`` so:
        - Every NULL content_key row forms its OWN singleton group (the COALESCE
          guard — a bare PARTITION BY content_key would merge ALL unkeyed rows).
        - The representative per group is the highest-quality variant
          (``detected_quality`` ranked lowest-int-wins) with ``id`` as a
          deterministic tiebreaker.
        - ``_variant_count`` carries the group size into the outer result.

        Returns a query over ``ChannelDB`` restricted to the ``_rn = 1``
        representatives, ordered alphabetically by the stored clean title
        (``detected_title`` NOCASE, fallback to ``name``).  The caller applies
        OFFSET/LIMIT on top.

        Args:
            matching_subq: The already-built subquery of matching channel_ids
                (the output of ``_faceted_channel_id_query(...).subquery()``).
            name_filter: Optional ILIKE filter applied before collapse so every
                collapsed page respects it at the SQL level.

        Returns:
            An unexecuted SQLAlchemy query yielding ``(ChannelDB, int)`` tuples
            where the int is ``_variant_count``.  Caller slices with
            ``.offset(n).limit(k).all()``.
        """
        from metatv.core.database import ChannelDB
        from sqlalchemy import func as _func, text as _text

        # ── INNER ── join ChannelDB to the faceted match set; apply name filter.
        _title_expr = _func.coalesce(
            _func.nullif(ChannelDB.detected_title, ""), ChannelDB.name
        )
        inner_q = (
            self.session.query(ChannelDB)
            .join(matching_subq, matching_subq.c.channel_id == ChannelDB.id)
        )
        if name_filter:
            inner_q = inner_q.filter(_title_expr.ilike(f"%{name_filter}%"))
        inner = inner_q.subquery(name="inner_ch")

        # ── MIDDLE ── window functions over the inner set.
        # GROUP KEY: COALESCE(content_key, 'id:' || id) — NULL-safe per the spec.
        # REP RANK:  quality CASE (lower = better), tiebreak by id.
        _group_key = _func.coalesce(
            inner.c.content_key,
            _func.concat("id:", inner.c.id),
        )
        _rep_rank = _text(
            "CASE inner_ch.detected_quality"
            " WHEN '4K'  THEN 0"
            " WHEN '8K'  THEN 0"
            " WHEN 'UHD' THEN 0"
            " WHEN 'FHD' THEN 1"
            " WHEN 'HDR' THEN 1"
            " WHEN 'HD'  THEN 2"
            " ELSE 3 END"
        )

        # SQLAlchemy doesn't have a first-class window-function API that maps
        # cleanly to PARTITION BY arbitrary expressions here.  We use text()
        # for the window clauses and label the results for the outer query.
        _rn = _func.row_number().over(
            partition_by=_group_key,
            order_by=[_rep_rank, inner.c.id],
        ).label("_rn")
        _vc = _func.count(inner.c.id).over(
            partition_by=_group_key,
        ).label("_variant_count")

        # Select all ChannelDB columns + the two window labels.
        middle = (
            self.session.query(inner, _rn, _vc)
        ).subquery(name="windowed")

        # ── OUTER ── keep the representative (rn=1), order by clean title.
        # We can only SELECT the windowed subquery columns, not the ORM directly.
        # Strategy: collect the representative channel ids + variant_counts, then
        # join back to ChannelDB for the full ORM objects in the right order.
        #
        # The outer query needs: id, _variant_count, and the title sort expression.
        _outer_title_sort = _func.coalesce(
            _func.nullif(middle.c.detected_title, ""), middle.c.name
        ).collate("NOCASE")

        reps_q = (
            self.session.query(
                middle.c.id.label("rep_id"),
                middle.c._variant_count.label("vc"),
            )
            .filter(middle.c._rn == 1)
            .order_by(_outer_title_sort, middle.c.id)
        )
        return reps_q

    def sample_channels_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        excluded_tag_content_types: Optional[Set[str]] = None,
        rating_range: Optional[Tuple[float, float]] = None,
        limit: int = 24,
        offset: int = 0,
        name_filter: Optional[str] = None,
        collapse_variants: bool = False,
    ) -> list:
        """Return *limit* result cards matching the faceted constraints, from *offset*.

        The card-bearing sibling of :meth:`sample_channel_names_by_tag_facets`:
        used by the recipe's "Now Plating" results shelf and its "Show all"
        browse drill-down, which render real, clickable poster cards (reusing the
        Discover ``_ContentCard`` surface) rather than dead title chips.

        Takes a bounded ``LIMIT``/``OFFSET`` slice of the match query (the full
        set is never materialised) and maps each ``ChannelDB`` row to a
        :class:`~metatv.core.discovery_engine.ContentCard` — a session-free value
        object (poster url, title, media_type, year, provider scoping already
        applied).  No ORM object crosses the worker→main boundary.

        **Stable pagination.** Pages are ordered by the stored clean title
        (``detected_title`` — quality/region/category prefixes like "4K -" or
        "|EN|" already stripped at ingestion), case-insensitive, falling back to
        the raw ``name`` when no title was detected, with ``channel_id`` as a
        deterministic tiebreaker.  So successive ``(limit, offset)`` pages are
        disjoint and together cover the whole match set — no overlap, no gaps —
        and the browse reads as ONE true A→Z run (no "4K leads" or per-prefix /
        per-case sub-runs).  The teaser (``offset=0``) and every "Show all" page
        share this one ordering, so page boundaries align with the seeded teaser.

        Scoping is IDENTICAL to the count/preview path (hidden providers + the
        caller's Global Exclusions), so the shelf agrees with YIELDS.

        Args:
            includes / excludes / base_channel_ids / excluded_provider_ids /
            excluded_prefixes / excluded_categories / rating_range: see
                :meth:`_faceted_channel_id_query` (rating_range carries the
                unrated/NULL semantics).
            limit: Max cards to return (default 24 — the results-shelf cap).
            offset: Number of leading matches to skip (for paged "Show all").
            name_filter: Optional substring to match against
                ``COALESCE(detected_title, name)`` (case-insensitive).  When
                set, only channels whose clean title contains this string are
                returned.  Used by the "Show all" browse filter box so every
                page — including lazy-loaded ones — honours the filter at the
                SQL level rather than filtering an already-loaded subset.
            collapse_variants: When True, collapse same-``content_key`` channels
                into one representative card per group (highest-quality variant,
                tiebreak by id).  The card's ``variant_count`` is set to the
                group size.  When False (default), behaviour is exactly as before
                this parameter was added — no change for existing callers.

        Returns:
            List of ``ContentCard`` value objects in clean-title
            (``detected_title``, case-insensitive) order.  Empty when no channel
            matches.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.discovery_engine import _to_card

        # The faceted match set as a subquery of channel ids (EXISTS-filtered and
        # scoped) — never materialised in Python.
        matching = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            rating_range=rating_range,
        ).subquery()

        if collapse_variants:
            # ── Collapsed path ─────────────────────────────────────────────
            # One representative per content_key group, ordered by clean title.
            # _build_collapsed_sample_query returns (rep_id, vc) rows in order.
            reps_q = self._build_collapsed_sample_query(
                matching, name_filter=name_filter
            )
            reps = reps_q.offset(offset).limit(limit).all()
            if not reps:
                return []
            # Build a mapping rep_id → variant_count before re-fetching ORM rows.
            vc_by_id = {row.rep_id: row.vc for row in reps}
            rep_ids = [row.rep_id for row in reps]
            # Preserve the collapse-ordered sequence (alphabetical by title, not
            # insertion order) by doing a SELECT then restoring the order.
            rows_unordered = (
                self.session.query(ChannelDB)
                .filter(ChannelDB.id.in_(rep_ids))
                .all()
            )
            # Restore the collapsed order (reps list is already ordered).
            order_map = {rid: i for i, rid in enumerate(rep_ids)}
            rows = sorted(rows_unordered, key=lambda ch: order_map.get(ch.id, 0))
            cards = []
            for ch in rows:
                card = _to_card(ch)
                card.variant_count = vc_by_id.get(ch.id, 1)
                cards.append(card)
            return cards

        # ── Non-collapsed path (existing behaviour, unchanged) ──────────────
        from sqlalchemy import func as _func

        _title_expr = _func.coalesce(
            _func.nullif(ChannelDB.detected_title, ""), ChannelDB.name
        )
        _title_sort = _title_expr.collate("NOCASE")
        q = (
            self.session.query(ChannelDB)
            .join(matching, matching.c.channel_id == ChannelDB.id)
        )
        if name_filter:
            # SQL-level filter: COALESCE(detected_title, name) LIKE '%<filter>%'.
            # Applied before OFFSET/LIMIT so every page respects the filter, not
            # just the already-loaded subset (Bug D fix).
            q = q.filter(_title_expr.ilike(f"%{name_filter}%"))
        rows = (
            q.order_by(_title_sort, ChannelDB.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        # _to_card builds a session-free ContentCard from each ORM row; engagement
        # badge sets are omitted (the preview shelf doesn't decorate them).
        return [_to_card(ch) for ch in rows]



# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clear_tag_cache() -> None:
    """Clear the process-level tag-id cache.

    Intended for test isolation only — not needed in production because the
    cache is keyed by ``(type, value)`` which are stable for a given DB file.
    Call this in test fixtures that create a fresh DB to avoid stale ids from
    a prior test leaking into the new DB's identity space.
    """
    with _TAG_ID_LOCK:
        _TAG_ID_CACHE.clear()


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
