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

    # ------------------------------------------------------------------
    # Faceted stats
    # ------------------------------------------------------------------

    def _scope_to_visible_channels(self, query, channel_id_col,
                                   excluded_provider_ids: Optional[List[str]] = None,
                                   excluded_prefixes: Optional[Set[str]] = None,
                                   excluded_categories: Optional[Set[str]] = None):
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

        **Global-exclusion semantics** (replicated from the main channel list —
        ``main_window_channels.py`` ``_query_channels_page``): a channel is
        dropped when its ``detected_prefix`` OR its ``detected_region`` is in
        *excluded_prefixes*, or its ``user_category`` is in
        *excluded_categories*.  This is a pure caller-supplied scope: the engine
        never reads ``Config`` (DR-0007 — the control layer resolves the sets
        and passes them in).

        **NULL trap:** ``col NOT IN (...)`` evaluates to NULL (false) when
        ``col IS NULL``, which would wrongly drop untagged channels (no prefix /
        region / category).  Each filter is therefore expressed as
        ``or_(col.is_(None), col.notin_(values))`` so a NULL column is kept.

        Args:
            query: The SQLAlchemy query to scope.
            channel_id_col: The column expression carrying the channel id to
                join ``ChannelDB.id`` against (e.g. ``ContentTagDB.channel_id``
                or an aliased equivalent).
            excluded_provider_ids: Provider IDs to additionally exclude.  An
                empty list still applies the is_hidden / ``##`` scope; ``None``
                also applies it — callers that want *no* scoping simply don't
                call this helper.
            excluded_prefixes: Global-exclusion prefix codes (the union of
                ``global_filter_excluded_categories`` and
                ``global_filter_excluded_prefixes``) matched against BOTH
                ``detected_prefix`` and ``detected_region``.  ``None``/empty →
                no prefix scope.
            excluded_categories: Global-exclusion user-category labels
                (``global_filter_excluded_user_categories``) matched against
                ``user_category``.  ``None``/empty → no category scope.

        Returns:
            The query with the visibility join + filters applied.
        """
        from metatv.core.database import ChannelDB
        from sqlalchemy import or_

        query = query.join(ChannelDB, ChannelDB.id == channel_id_col).filter(
            ChannelDB.is_hidden == False,       # noqa: E712
            ChannelDB.name.notlike("##%"),      # exclude provider category headers
        )
        if excluded_provider_ids:
            query = query.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        if excluded_prefixes:
            _pref = list(excluded_prefixes)
            # detected_prefix and detected_region are independent signals — a
            # channel is banished if EITHER is in the excluded set (matches the
            # main list's `prefix not in … and region not in …` keep-condition).
            # or_(is None, notin) keeps NULL columns (the NULL trap above).
            query = query.filter(
                or_(ChannelDB.detected_prefix.is_(None),
                    ChannelDB.detected_prefix.notin_(_pref)),
                or_(ChannelDB.detected_region.is_(None),
                    ChannelDB.detected_region.notin_(_pref)),
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
            excluded_prefixes, excluded_categories,
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
            excluded_prefixes, excluded_categories,
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

        outer = aliased(ContentTagDB, flat=True)
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
                excluded_prefixes, excluded_categories,
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
    ) -> set[str]:
        """Return the set of channel ids matching the faceted constraints.

        Standard faceted search (OR within a facet, AND across facets, NOT for
        excludes).  See :meth:`_faceted_channel_id_query` for the full semantics
        and the meaning of *base_channel_ids* / *excluded_provider_ids* /
        *excluded_prefixes* / *excluded_categories*.

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
    ) -> int:
        """Count channels matching the faceted constraints — entirely in SQL.

        Issues a single ``SELECT count(*) FROM (SELECT DISTINCT channel_id …)``,
        so a 170k-match facet costs one integer round-trip, not 170k id strings
        crossing into Python.  Arguments match :meth:`_faceted_channel_id_query`.
        """
        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
        )
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

    def sample_channels_by_tag_facets(
        self,
        includes: dict[str, set[str]],
        excludes: Optional[dict[str, set[str]]] = None,
        *,
        base_channel_ids: Optional[Set[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        excluded_prefixes: Optional[Set[str]] = None,
        excluded_categories: Optional[Set[str]] = None,
        limit: int = 24,
    ) -> list:
        """Return up to *limit* result cards matching the faceted constraints.

        The card-bearing sibling of :meth:`sample_channel_names_by_tag_facets`:
        used by the recipe's "Now Plating" results shelf, which renders real,
        clickable poster cards (reusing the Discover ``_ContentCard`` surface)
        rather than dead title chips.

        Takes a bounded ``LIMIT`` slice of the match query (the full set is never
        materialised), loads the full ``ChannelDB`` rows for those ``<=limit``
        ids, and maps each to a :class:`~metatv.core.discovery_engine.ContentCard`
        — a session-free value object (poster url, title, media_type, year,
        provider scoping already applied).  No ORM object crosses the worker→main
        boundary.

        Scoping is IDENTICAL to the count/preview path (hidden providers + the
        caller's Global Exclusions), so the shelf agrees with YIELDS.

        Args:
            includes / excludes / base_channel_ids / excluded_provider_ids /
            excluded_prefixes / excluded_categories: see
                :meth:`_faceted_channel_id_query`.
            limit: Max cards to return (default 24 — the results-shelf cap).

        Returns:
            List of ``ContentCard`` value objects, name-sorted.  Empty when no
            channel matches.
        """
        from metatv.core.database import ChannelDB
        from metatv.core.discovery_engine import _to_card

        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
        )
        ids = [row.channel_id for row in query.limit(limit).all()]
        if not ids:
            return []
        rows = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(ids))
            .order_by(ChannelDB.name)
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
