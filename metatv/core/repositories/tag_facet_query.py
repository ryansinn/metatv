"""Faceted channel queries for ``TagRepository``: match, count and sample by tags.

The recipe / Browse engine — "which channels carry these facet values" — split
out of ``tag.py`` (D42, 2026-10-19) when that file hit its size ceiling. Composed
into ``TagRepository`` exactly like ``ContentTagCrudMixin``: every method runs
on ``self.session`` and reaches the shared visibility scope through
``self._scope_to_visible_channels``.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Set

from sqlalchemy import exists

from metatv.core.database import ChannelDB, ContentTagDB, TagDB
from metatv.core.tag_source import facet_match


class FacetQueryMixin:
    """Faceted match / count / sample methods; see the module docstring."""


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
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
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
            An unexecuted SQLAlchemy query selecting ``DISTINCT channel_key``
            (DB-9's internal int surrogate — every public caller below
            translates back to ``ChannelDB.id``) for every channel satisfying
            the constraints.  Callers choose how to consume it: ``.all()`` for
            the key set, ``.count()`` for a SQL count, ``.limit(n)`` for a
            bounded sample.
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
        # We anchor the outer query on ContentTagDB.channel_key and filter it
        # with correlated EXISTS subqueries — one per include facet (AND) and
        # one NOT EXISTS for the union of all exclude tags.  SQLite evaluates
        # each EXISTS as a correlated scan using the idx on content_tags(tag_id);
        # no full-table materialisation occurs at any facet count.

        # Anchor on the first include facet's tag membership so SQLite seeks the
        # tag_id index instead of scanning all of content_tags; the other facets
        # are correlated EXISTS (AND), excludes one NOT EXISTS. ~7.5s → ~0.4s.
        outer = aliased(ContentTagDB, flat=True)
        if constrained_facets:
            anchor_ftype, anchor_values = constrained_facets[0]
            remaining_facets = constrained_facets[1:]
            t_anchor = aliased(TagDB, flat=True)
            query = (
                self.session.query(outer.channel_key)
                .join(t_anchor, t_anchor.id == outer.tag_id)
                .filter(
                    facet_match(t_anchor.type, outer.qualifier, anchor_ftype),
                    t_anchor.value.in_(list(anchor_values)),
                )
                .distinct()
            )
        else:
            remaining_facets = []
            query = self.session.query(outer.channel_key).distinct()

        # Scope to a caller-provided pre-filter if given. base_channel_ids is
        # public ChannelDB.id strings — DB-9: translate to the int
        # channel_keys the query is actually anchored on.
        if base_channel_ids is not None:
            base_channel_keys = set(self._channel_keys(base_channel_ids).values())
            query = query.filter(outer.channel_key.in_(base_channel_keys))

        # Scope to visible channels on active sources when requested (recipe
        # YIELDS uses this so its count matches the pantry/cloud facet counts).
        # Global Exclusions ride along on the same scope so YIELDS/preview never
        # surface content the user has globally banished. Any axis switches the
        # scope on (ledger F25): gating it on excluded_provider_ids alone meant a
        # caller passing exclusions without provider ids lost every one.
        if excluded_provider_ids is not None or any((
                excluded_prefixes, excluded_categories, excluded_tag_content_types,
                excluded_keywords, dead_signal_streak_floor is not None)):
            query = self._scope_to_visible_channels(
                query, outer.channel_key, excluded_provider_ids,
                excluded_prefixes, excluded_categories, excluded_tag_content_types,
                excluded_keywords=excluded_keywords,
                dead_signal_streak_floor=dead_signal_streak_floor,
            )

        # --- include facets: one correlated EXISTS per facet (AND across facets) ---
        for ftype, allowed_values in remaining_facets:
            ct_i = aliased(ContentTagDB, flat=True)
            t_i = aliased(TagDB, flat=True)
            subq = (
                sa_select(ct_i.channel_key)
                .join(t_i, t_i.id == ct_i.tag_id)
                .where(
                    ct_i.channel_key == outer.channel_key,
                    facet_match(t_i.type, ct_i.qualifier, ftype),
                    t_i.value.in_(list(allowed_values)),
                )
                .correlate(outer)
            )
            query = query.filter(exists(subq))

        # --- exclude facets: ONE NOT EXISTS; SQLite has no tuple-IN, so an OR of
        # per-facet (facet AND value IN (...)) clauses.
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
                and_(facet_match(t_e.type, ct_e.qualifier, ftype), t_e.value.in_(list(vals)))
                for ftype, vals in excludes.items()
                if vals
            ]

            excl_subq = (
                sa_select(ct_e.channel_key)
                .join(t_e, t_e.id == ct_e.tag_id)
                .where(
                    ct_e.channel_key == outer.channel_key,
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
        excluded_tag_content_types: Optional[Set[str]] = None,
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
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
            excluded_tag_content_types=excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        )
        keys = {row.channel_key for row in query.all()}
        if not keys:
            return set()
        # DB-9: translate the (already small, already-filtered) match set back
        # to public channel_id strings, this method's contract.
        rows = self.session.query(ChannelDB.id).filter(ChannelDB.channel_key.in_(keys)).all()
        return {r.id for r in rows}

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
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
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
        from sqlalchemy import func as _func

        query = self._faceted_channel_id_query(
            includes, excludes,
            base_channel_ids=base_channel_ids,
            excluded_provider_ids=excluded_provider_ids,
            excluded_prefixes=excluded_prefixes,
            excluded_categories=excluded_categories,
            excluded_tag_content_types=excluded_tag_content_types,
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
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
                .join(matching, matching.c.channel_key == ChannelDB.channel_key)
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
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
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
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        )
        keys = [row.channel_key for row in query.limit(limit).all()]
        if not keys:
            return []
        rows = (
            self.session.query(ChannelDB.name)
            .filter(ChannelDB.channel_key.in_(keys))
            .order_by(ChannelDB.name)
            .all()
        )
        return [name for (name,) in rows]


    # ------------------------------------------------------------------
    # Variant-collapse helper (shared chokepoint for dedup Slice 2)
    # ------------------------------------------------------------------

    # (A third hardcoded quality ladder lived here as _QUALITY_RANK_CASE with
    # NO callers — dead, but the next person to need a rank would have found it
    # and used it. Deleted; the rank comes from QUALITY_TIER_RANK below.)

    def _build_collapsed_sample_query(
        self,
        matching_subq,
        *,
        name_filter: Optional[str] = None,
        media_types: Optional[Sequence[str]] = None,
        newest_first: bool = False,
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
            media_types: Optional ``ChannelDB.media_type`` whitelist, applied
                before collapse (so a group's representative is chosen from the
                rows that survive the filter, not discarded after election).
            newest_first: Order by the ingestion-computed ``detected_added``
                (DB-4, indexed) descending instead of alphabetically. SQLite
                sorts NULL below every value, so un-stamped rows land last.

        Returns:
            An unexecuted SQLAlchemy query yielding ``(ChannelDB, int)`` tuples
            where the int is ``_variant_count``.  Caller slices with
            ``.offset(n).limit(k).all()``.
        """
        from metatv.core.database import ChannelDB
        from sqlalchemy import case as _case, func as _func

        from metatv.core.quality_vocab import QUALITY_TIER_RANK, _QUALITY_TIER_RANK_DEFAULT

        # ── INNER ── join ChannelDB to the faceted match set; apply name filter.
        _title_expr = _func.coalesce(
            _func.nullif(ChannelDB.detected_title, ""), ChannelDB.name
        )
        inner_q = (
            self.session.query(ChannelDB)
            .join(matching_subq, matching_subq.c.channel_key == ChannelDB.channel_key)
        )
        if name_filter:
            inner_q = inner_q.filter(_title_expr.ilike(f"%{name_filter}%"))
        if media_types:
            inner_q = inner_q.filter(ChannelDB.media_type.in_(list(media_types)))
        inner = inner_q.subquery(name="inner_ch")

        # ── MIDDLE ── window functions over the inner set.
        # GROUP KEY: COALESCE(content_key, 'id:' || id) — NULL-safe per the spec.
        # REP RANK:  quality CASE (lower = better), tiebreak by id.
        _group_key = _func.coalesce(
            inner.c.content_key,
            _func.concat("id:", inner.c.id),
        )
        # Built from QUALITY_TIER_RANK, not a local ladder. The hardcoded CASE
        # this replaced DISAGREED with the canonical table on ORDERING, not just
        # values: it ranked HDR above HD (HDR is a dynamic-range descriptor, not
        # a resolution tier — the table deliberately leaves it unranked), and
        # tied 8K with 4K and SD with LQ. So a title with an HD copy and an HDR
        # copy elected HD in the channel list and HDR in Discover: two surfaces,
        # same data, different answer.
        _max_rank = max(QUALITY_TIER_RANK.values())
        _rep_rank = _case(
            *[(inner.c.detected_quality == tok, _max_rank - rank)
              for tok, rank in QUALITY_TIER_RANK.items()],
            else_=_max_rank - _QUALITY_TIER_RANK_DEFAULT,
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

        _order = ([middle.c.detected_added.desc(), middle.c.id] if newest_first
                  else [_outer_title_sort, middle.c.id])
        reps_q = (
            self.session.query(
                middle.c.id.label("rep_id"),
                middle.c._variant_count.label("vc"),
            )
            .filter(middle.c._rn == 1)
            .order_by(*_order)
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
        excluded_keywords: Optional[Set[str]] = None,
        dead_signal_streak_floor: Optional[int] = None,
        limit: int = 24,
        offset: int = 0,
        name_filter: Optional[str] = None,
        collapse_variants: bool = False,
        media_types: Optional[Sequence[str]] = None,
        newest_first: bool = False,
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
            excluded_prefixes / excluded_categories: see
                :meth:`_faceted_channel_id_query`.
            limit: Max cards to return (default 24 — the results-shelf cap).
            offset: Number of leading matches to skip (for paged "Show all").
            name_filter: Optional substring to match against
                ``COALESCE(detected_title, name)`` (case-insensitive).  When
                set, only channels whose clean title contains this string are
                returned.  Used by the "Show all" browse filter box so every
                page — including lazy-loaded ones — honours the filter at the
                SQL level rather than filtering an already-loaded subset.
            media_types: Optional ``media_type`` whitelist (e.g.
                ``("movie", "series")`` for a VOD-only shelf). ``None`` keeps
                every type, which is what every pre-PLAT-1 caller wants.
            newest_first: Order by ``detected_added`` desc (DB-4, indexed)
                instead of by clean title — what a "what has this platform
                added lately" shelf means. Applies to both paths.
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
            excluded_keywords=excluded_keywords,
            dead_signal_streak_floor=dead_signal_streak_floor,
        ).subquery()

        if collapse_variants:
            # ── Collapsed path ─────────────────────────────────────────────
            # One representative per content_key group, ordered by clean title.
            # _build_collapsed_sample_query returns (rep_id, vc) rows in order.
            reps_q = self._build_collapsed_sample_query(
                matching, name_filter=name_filter,
                media_types=media_types, newest_first=newest_first,
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
            .join(matching, matching.c.channel_key == ChannelDB.channel_key)
        )
        if name_filter:
            # SQL-level filter: COALESCE(detected_title, name) LIKE '%<filter>%'.
            # Applied before OFFSET/LIMIT so every page respects the filter, not
            # just the already-loaded subset (Bug D fix).
            q = q.filter(_title_expr.ilike(f"%{name_filter}%"))
        if media_types:
            q = q.filter(ChannelDB.media_type.in_(list(media_types)))
        _order = ([ChannelDB.detected_added.desc(), ChannelDB.id] if newest_first
                  else [_title_sort, ChannelDB.id])
        rows = (
            q.order_by(*_order)
            .offset(offset)
            .limit(limit)
            .all()
        )
        # _to_card builds a session-free ContentCard from each ORM row; engagement
        # badge sets are omitted (the preview shelf doesn't decorate them).
        return [_to_card(ch) for ch in rows]
