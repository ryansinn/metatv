"""Channel repository for data access"""

import inspect
import re
from functools import lru_cache
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime
from sqlalchemy.orm import Session, defer
from sqlalchemy import and_, func, or_, update
from loguru import logger

from metatv.core.db_lock import (
    LOCK_RETRY_ATTEMPTS, LOCK_RETRY_DELAY_S, retry_on_lock,
)
from metatv.core.database import (
    ChannelDB, MetadataDB, StreamRetryDB,
)
from metatv.core import channel_visibility, visibility_resolver
from metatv.core.repositories import channel_downloads
from metatv.core.repositories.search_ranking import (
    channel_text_search_predicate, search_order_terms)
from metatv.core.channel_name_utils import (
    QUALITY_TIER_RANK,
)
from metatv.core.repositories.dtos import (
    LiveEventDTO,
)
from metatv.core.repositories.channel_stats import _ChannelStatsMixin
from metatv.core.repositories.channel_history import _ChannelHistoryMixin
from metatv.core.repositories.channel_pruning import _ChannelPruningMixin
from metatv.core.repositories.channel_enrichment import ChannelEnrichmentMixin
from metatv.core.repositories.channel_provider_ops import ChannelProviderOpsMixin
from metatv.core.repositories.channel_user_state import ChannelUserStateMixin
# Facet lenses + the predicates the channel-list person/genre filters share with
# them — one definition, so "See all in Search" lands on the set the lens showed.
from metatv.core.repositories.channel_ingestion import (
    ChannelIngestionMixin,
)
from metatv.core.repositories.channel_lens import (
    GENRE_MEDIA_TYPES, collapse_best_variant,
    genre_predicate, lens_channels, person_predicate,
)


# _GENRE_NORM and normalize_genre now live in metatv.core.filter_utils (a dependency-free
# leaf) — single source of truth, re-imported above so existing `channel._GENRE_NORM` /
# `channel.normalize_genre` references keep working. See filter_utils for the table.

# Similar-titles tuning — shared by the single chokepoint
# ``ChannelRepository.get_similar_channels`` (both the details-pane "Similar Titles"
# row and the similar-titles lightbox route through it).
_SIMILAR_CANDIDATE_SCAN = 200  # max rows the word-overlap heuristic scans per lookup
_SIMILAR_NON_ASCII_RE = re.compile(r"[^\x00-\x7F]+")  # blanked before candidate word-split

# update_detected_prefixes batch lock-retry tuning. The engine already applies a
# 30s PRAGMA busy_timeout to every connection (database.py), so an OperationalError
# reaching here means a concurrent bulk writer (EPG auto-refresh's batched inserts,
# another Migration Center task) held the write lock for even longer than that —
# a real, if rare, collision under the startup write storm. Retry a few times with
# a short sleep rather than aborting the whole multi-batch run (see
# _commit_prefix_batch_with_retry).
#
# The loop itself now lives in metatv.core.db_lock, because the watch-list
# writer needs the same policy and has no repository to hang it on.
_LOCK_RETRY_ATTEMPTS = LOCK_RETRY_ATTEMPTS
_LOCK_RETRY_DELAY_S = LOCK_RETRY_DELAY_S



# Axes ``_apply_channel_filters`` understands that ``count_watched_matching``
# deliberately does NOT forward, each with the reason it is excluded.
_COUNT_WATCHED_OMITS = frozenset({
    "query",            # the query object itself, passed positionally
    "exclude_watched",  # this method narrows TO watched rows
    "include_hidden",   # the count is always over the visible set
    "hidden_only",      # same
    "downloaded_only",  # same — a record/engaged-view axis, not a SQL COUNT concern
})

# Axes a caller may splat in that this count knowingly skips: ``get_all``
# applies them in Python after the query returns, or they are pagination, so
# there is nothing to forward to a SQL COUNT.  Accepted silently so a caller can
# pass its whole axis dict; see the method docstring's "Known limit".
_COUNT_WATCHED_IGNORED = frozenset({
    "collapse_variants",
    "excluded_channel_ids",
    "excluded_prefixes",
    "excluded_user_categories",
    "tag_excludes",
    "limit",
    "offset",
})


@lru_cache(maxsize=1)
def _apply_channel_filters_axes() -> frozenset:
    """Axis names :meth:`ChannelRepository._apply_channel_filters` accepts.

    Derived from the signature so a newly added axis reaches every forwarder
    without anyone remembering to list it — the enumeration failure that let
    ``channel_ids`` / ``excluded_keywords`` / ``include_dead`` reach ``get_all``
    and never reach the watched count.
    """
    sig = inspect.signature(ChannelRepository._apply_channel_filters)
    return frozenset(sig.parameters) - {"self"}






#: Widest quality rank the packing below has to encode. Read from the lookup
#: table rather than written down, so a new tier cannot silently change how
#: wide the sort prefix needs to be.
_MAX_QUALITY_RANK = max(QUALITY_TIER_RANK.values())


def _collapse_rank_penalty(
    *,
    excluded_prefixes=None,
    excluded_user_categories=None,
    excluded_channel_ids=None,
    channel_cls,
):
    """A 3-tier penalty for how good an ambassador a row is for its title.

    Sorted ascending ahead of quality, so a title puts forward the least
    compromised copy it has:

    ``0`` — untouched by any exclusion.
    ``1`` — visible, but its ``detected_region`` is a code the user excluded.
    ``2`` — will be dropped by the caller's Python exclusion pass.

    **Tier 1 is the owner's observation, and it is not the same question as
    tier 2.** ``is_channel_excluded`` says "language wins over region": a row
    with an explicit un-excluded prefix stays VISIBLE even when its region is
    excluded, because excluding German must not hide an English film merely
    filed under a German category. That rule is right, and it is about
    visibility.

    Election is a different question. Given several visible copies, the one
    whose region is a code you excluded is the worst of them to put forward.
    The real case: ``aladdin|movie|`` elected ``|MULTI| Aladdin 4K``
    (prefix MULTI, region DE) while ``|EN| Aladdin 4K`` sat beside it at the
    same quality with no excluded code on it at all — so the German Disney copy
    represented the title to someone who excludes German.

    Tier 1 changes nothing about what is VISIBLE. A region-tainted row is still
    shown, still counted, and still wins the slot when it is the only copy
    there is.

    Used only to ORDER the collapse's representative election, never to filter
    — see ``_get_all_collapsed``. Composed from the canonical Global-Exclusion
    predicates rather than a hand-rolled ``or_``: ``channel_exclusion_criterion``
    is the KEEP twin of ``is_channel_excluded`` and owns the "language wins over
    region" rule, so negating it here keeps one definition of excluded rather
    than growing a second that can drift from the Python pass it is mirroring.

    Returns None when nothing is excluded, so the caller adds no rank term at
    all and the SQL is byte-for-byte what it was.
    """
    from sqlalchemy import case as _case, not_ as _not, or_ as _or

    from metatv.core.filter_utils import channel_exclusion_criterion

    drop = []
    if excluded_prefixes:
        # NOT(keep) == excluded, by the twin's own definition — so the
        # "language wins over region" rule stays owned by one function.
        drop.append(
            _not(channel_exclusion_criterion(set(excluded_prefixes), channel_cls))
        )
    if excluded_user_categories:
        drop.append(channel_cls.user_category.in_(list(excluded_user_categories)))
    if excluded_channel_ids:
        drop.append(channel_cls.id.in_(list(excluded_channel_ids)))

    if not drop:
        return None
    dropped = drop[0] if len(drop) == 1 else _or(*drop)

    branches = [(dropped, 2)]
    if excluded_prefixes:
        # Reached only when the row is NOT dropped — CASE takes the first true
        # branch — so this is exactly "visible, but region-tainted".
        branches.append(
            (channel_cls.detected_region.in_(list(excluded_prefixes)), 1)
        )
    return _case(*branches, else_=0)


class ChannelRepository(ChannelIngestionMixin, ChannelEnrichmentMixin,
                        ChannelProviderOpsMixin, ChannelUserStateMixin,
                        _ChannelStatsMixin, _ChannelHistoryMixin,
                        _ChannelPruningMixin):
    """Repository for channel data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, channel_id: str) -> Optional[ChannelDB]:
        """Get channel by ID"""
        return self.session.query(ChannelDB).filter_by(id=channel_id).first()

    def get_detected_genre(self, channel_id: str) -> Optional[str]:
        """Return the channel's ingestion-computed primary genre, or None.

        Reads the stored ``detected_genre`` rather than re-deriving it from
        ``raw_data`` (compute-once; one indexed column beats a JSON scan). One
        column, one row — safe to call from a click handler.

        Args:
            channel_id: The ``ChannelDB.id``.

        Returns:
            The genre, or None when the row is gone or carries no usable value.
        """
        row = (
            self.session.query(ChannelDB.detected_genre)
            .filter(ChannelDB.id == channel_id)
            .first()
        )
        if not row:
            return None
        return (row[0] or "").strip() or None

    def get_playable_dto(self, channel_id: str) -> "Optional[PlayableChannelDTO]":
        """Return a PlayableChannelDTO for *channel_id*, or None if not found.

        Must be called inside a session_scope().  No ORM object escapes — the
        returned frozen dataclass is safe to use after the session closes.
        """
        from metatv.core.repositories.dtos import PlayableChannelDTO
        ch = self.get_by_id(channel_id)
        if ch is None:
            return None
        return PlayableChannelDTO(
            id=ch.id,
            source_id=ch.source_id,
            provider_id=ch.provider_id,
            name=ch.name,
            stream_url=ch.stream_url,
            media_type=ch.media_type,
            is_favorite=bool(ch.is_favorite),
            is_hidden=bool(ch.is_hidden),
            is_adult=bool(ch.is_adult),
            logo_url=ch.logo_url,
            detected_prefix=ch.detected_prefix,
            detected_quality=ch.detected_quality,
            detected_region=ch.detected_region,
            detected_title=ch.detected_title,
            detected_year=ch.detected_year,
            raw_data=ch.raw_data,
            metadata_id=ch.metadata_id,
            watch_progress=int(getattr(ch, "watch_progress", 0) or 0),
            watch_completed=bool(getattr(ch, "watch_completed", False)),
            event_start_time=getattr(ch, "event_start_time", None),
        )

    def get_sample_channel_id(self, kind: str) -> Optional[str]:
        """Return one representative channel id for a QA deep-link ``sample:<kind>``.

        Backs the dev QA checklist's "Go ▸" deep-links: a content link can't
        hardcode a per-user title, so the app finds a matching channel instead.
        Returns a plain string id (safe to hand across the async seam), or
        ``None`` when nothing matches.  Hidden channels are excluded so the
        sample is something actually visible in Browse.

        Args:
            kind: One of ``"vod"`` / ``"movie"`` (a movie), ``"live"`` (a live
                channel), ``"series"`` (a series), or ``"partial"`` (a
                partially-watched, not-yet-completed item).

        Returns:
            A channel id, or ``None`` if no channel matches.
        """
        from metatv.core.models import MediaType

        kind = (kind or "").strip().lower()
        q = self.session.query(ChannelDB.id).filter(ChannelDB.is_hidden == False)  # noqa: E712
        if kind in ("vod", "movie"):
            q = q.filter(ChannelDB.media_type == MediaType.MOVIE)
        elif kind == "live":
            q = q.filter(ChannelDB.media_type == MediaType.LIVE)
        elif kind == "series":
            q = q.filter(ChannelDB.media_type == MediaType.SERIES)
        elif kind == "partial":
            q = q.filter(
                ChannelDB.watch_progress > 0,
                ChannelDB.watch_completed == False,  # noqa: E712
            )
        else:
            logger.warning("get_sample_channel_id: unknown kind '{}'", kind)
            return None
        row = q.order_by(ChannelDB.id).first()
        return row[0] if row else None

    def get_by_source_id(self, provider_id: str, source_id: str) -> Optional[ChannelDB]:
        """Get channel by provider and source ID"""
        return self.session.query(ChannelDB).filter_by(
            provider_id=provider_id,
            source_id=source_id
        ).first()
    
    def get_all(self, provider_id=None,
                media_type: Optional[str] = None,
                media_types: Optional[List[str]] = None,
                language_prefixes: Optional[List[str]] = None,
                region_prefixes: Optional[List[str]] = None,
                quality_prefixes: Optional[List[str]] = None,
                platform_prefixes: Optional[List[str]] = None,
                genre_filters: Optional[List[str]] = None,
                include_hidden: bool = False,
                hidden_only: bool = False,
                downloaded_only: bool = False,
                invert_prefix_filters: bool = False,
                include_untagged: bool = True,
                include_untagged_quality: bool = True,
                adult_mode: str = "all",
                force_adult_provider_ids: Optional[List[str]] = None,
                source_categories: Optional[List[str]] = None,
                include_uncategorized_content_types: bool = True,
                search_query: Optional[str] = None,
                strict_genre_filter: Optional[str] = None,
                person_filter: Optional[str] = None,
                excluded_provider_ids: Optional[List[str]] = None,
                tag_includes: Optional[Dict[str, Set[str]]] = None,
                facets_hiding_untagged: Optional[Set[str]] = None,
                tag_excludes: Optional[Dict[str, Set[str]]] = None,
                context_tag_filter: Optional[Tuple[str, str]] = None,
                context_category_filter: Optional[str] = None,
                channel_ids: Optional[Set[str]] = None,
                exclude_watched: bool = False,
                include_dead: bool = False,
                excluded_keywords: Optional[List[str]] = None,
                collapse_variants: bool = False,
                excluded_prefixes: Optional[Set[str]] = None,
                excluded_user_categories: Optional[Set[str]] = None,
                excluded_channel_ids: Optional[Set[str]] = None,
                limit: Optional[int] = None,
                offset: Optional[int] = None) -> List[ChannelDB]:
        """Get all channels with optional filters.

        Args:
            provider_id: Filter by provider — str for one provider, List[str] for multiple.
            media_type: Filter by single media type (deprecated, use media_types).
            media_types: Filter by list of media types (e.g. ['live', 'movies']).
            language_prefixes: Language axis — detected_prefix IN list (OR detected_region).
            region_prefixes: Region axis — detected_prefix IN list (geographic hierarchy).
            quality_prefixes: Quality axis — restrictive AND filter on detected_quality.
            include_hidden: Include hidden channels (visible + hidden).
            hidden_only: Show only hidden channels (overrides include_hidden).
            downloaded_only: DL-5 record view — see channel_downloads.py.
            invert_prefix_filters: If True, show only items NOT matching the identity pool.
            include_untagged: When False, exclude channels with no detected_prefix.
            source_categories: Raw source_category labels to include (live channels only).
                None = no filter (show all). Only meaningful when querying live channels.
            include_uncategorized_content_types: When source_categories is set, also
                include live channels with no source_category (True by default).
            tag_includes: Faceted tag filter — ``{facet_type: set(values)}``.  A channel
                must carry at least one value in *each* constrained facet (AND across
                facets, OR within).  An empty or None set for a facet key is ignored.
                Implemented as per-facet correlated EXISTS subqueries so pagination
                and row counts stay entirely in SQL (no id-set materialisation).
            facets_hiding_untagged: Facet types whose per-section "Untagged"
                footer toggle the user has UNCHECKED. For those, the include
                criterion reverts to its strict form (must carry a ticked
                value); every other facet lets untagged content through. See
                filter_utils.facet_include_criterion.
            tag_excludes: Faceted tag exclusion — same shape as tag_includes.  A channel
                is rejected if it carries *any* matching tag.  Currently unused (reserved
                for the tri-state slice).
            context_tag_filter: Strict details-pane context filter — ``(facet_type, value)``.
                Keeps only channels carrying that EXACT tag (no hierarchy rollup), via a
                correlated EXISTS subquery.  Separate from ``tag_includes`` (the filter
                panel owns that) so the context chip is mutually exclusive + ephemeral.
                Used by the left-click-a-tag-chip path.
            context_category_filter: Strict details-pane context filter on the curated
                provider category (``ChannelDB.category == value``).  Used for COLLECTION
                tag clicks so the result is the actual human-curated provider grouping,
                not a re-derived query on the lossy 'collection' residual.
            exclude_watched: When True, exclude channels where ``watch_completed=True``.
                Default False (show everything, filter is opt-in).
            excluded_keywords: Global Exclusions keyword axis — user-defined
                free-text terms matched case-insensitively as a substring
                against ``detected_title``/``name`` (build with
                ``filter_utils.keyword_exclusion_list``). None/empty → no
                keyword filtering.
            include_dead: When True, lift the dead-stream gate (channels whose
                ``StreamRetryDB.reliability_state == "dead"``) so those rows are
                returned alongside the rest — used both to reveal them on demand
                (mirror-not-cage) and to measure how many the gate is hiding.
                Default False (gate stays applied, same as today). No effect when
                ``include_hidden``/``hidden_only`` already bypass the whole block.
            collapse_variants: When True, collapse same-``content_key`` channels
                (quality/language/source variants of the same production) into
                one representative row per ``COALESCE(content_key, 'id:' || id)``
                group — the highest-quality-tier variant (:func:`quality_tier_rank`
                in ``channel_name_utils``, the lookup-table single source of
                truth), tiebroken by id.  The representative carries a transient
                ``_variant_count`` attribute (group size) read by
                ``ChannelListDTO.from_orm``.  The collapse happens entirely in
                SQL via window functions (mirrors
                ``TagRepository._build_collapsed_sample_query``'s algorithm) so
                paginated pages stay full-sized and non-overlapping — never a
                post-fetch Python collapse of a page.  Never merges across
                ``media_type`` (already encoded in ``content_key`` itself).
                Since ``excluded_provider_ids`` is applied as a WHERE predicate
                BEFORE the window function runs, a hidden/expired-provider
                variant can never be excluded-from-set-yet-still-win the
                representative slot — it simply isn't a candidate, so the best
                *visible* variant always wins.  Default False — existing
                callers/behaviour unchanged.

        Returns:
            List of channels matching all filters.

        Filter logic:
            identity_pool = (language_prefixes OR region_prefixes OR platform_prefixes)
            result        = identity_pool AND quality_prefixes AND tag_includes
            Language, Region, Platform all OR together — selecting more always grows the
            result set. Quality is the only restrictive axis (AND).
            Tag facets are AND across facets, OR within each facet.
        """
        # raw_data is DEFERRED, not selected. It is ~369 MB across 785,489 rows —
        # roughly a third of the channels table — and nothing on this path reads
        # it: ChannelListDTO does not carry the field, and no caller of get_all()
        # touches it (checked across every file that calls this method).
        #
        # This is the busiest query in the app: every list render, every search,
        # every filter change. The identical change on preference_engine's
        # candidate query measured -29% wall clock and -25% peak memory on
        # 106,918 rows; this one runs on far more, far more often.
        #
        # defer() is transparent — a caller that did read .raw_data would still
        # get it via a lazy load rather than an error — so the failure mode of
        # being wrong here is a slow N+1, not a break. That is why the check
        # above was for readers, not for crashes.
        #
        # The collapsed path (_get_all_collapsed) builds its subquery from THIS
        # query, so deferring here covers both shapes.
        query = self.session.query(ChannelDB).options(defer(ChannelDB.raw_data))
        query = self._apply_channel_filters(
            query,
            provider_id=provider_id,
            media_type=media_type,
            media_types=media_types,
            language_prefixes=language_prefixes,
            region_prefixes=region_prefixes,
            quality_prefixes=quality_prefixes,
            platform_prefixes=platform_prefixes,
            genre_filters=genre_filters,
            include_hidden=include_hidden,
            hidden_only=hidden_only,
            downloaded_only=downloaded_only,
            invert_prefix_filters=invert_prefix_filters,
            include_untagged=include_untagged,
            include_untagged_quality=include_untagged_quality,
            adult_mode=adult_mode,
            force_adult_provider_ids=force_adult_provider_ids,
            source_categories=source_categories,
            include_uncategorized_content_types=include_uncategorized_content_types,
            search_query=search_query,
            strict_genre_filter=strict_genre_filter,
            person_filter=person_filter,
            excluded_provider_ids=excluded_provider_ids,
            tag_includes=tag_includes,
            facets_hiding_untagged=facets_hiding_untagged,
            context_tag_filter=context_tag_filter,
            context_category_filter=context_category_filter,
            channel_ids=channel_ids,
            exclude_watched=exclude_watched,
            include_dead=include_dead,
            excluded_keywords=excluded_keywords,
        )

        if collapse_variants:
            return self._get_all_collapsed(
                query, limit=limit, offset=offset,
                search_query=search_query,
                exclusion_sets={
                    "excluded_prefixes": excluded_prefixes,
                    "excluded_user_categories": excluded_user_categories,
                    "excluded_channel_ids": excluded_channel_ids,
                },
            )

        # Tie-break on id, not name alone. Two things depend on ties ordering
        # identically across separate executions: OFFSET paging (an unstable sort
        # can repeat or skip a tied row between pages) and the transparency
        # counters, whose floor is a set difference between this query and the
        # same query with one axis lifted — a tie that shuffles would read as a
        # row the axis hid. The collapse path below already tie-breaks this way.
        # Relevance first when searching, then the existing alphabetical
        # tie-break — which stays, so an un-searched list is byte-identical and
        # ties never shuffle. search_relevance_tier returns a constant when the
        # term is empty, so this is one expression rather than a branch.
        query = query.order_by(*search_order_terms(search_query, ChannelDB))

        # Comfy+ density's plot line (and the channel-list thumbnail's poster
        # URL): outerjoin MetadataDB and select ONLY its plot + poster_url
        # columns in this SAME paginated round-trip — never a per-row lookup.
        # metadata_id is a FK-by-convention onto MetadataDB's primary key, so the
        # join is 1:0-or-1 per channel row (no fan-out). add_columns() turns each
        # result into a (ChannelDB, plot, poster_url) tuple; we unpack immediately
        # and stash the values on transient (non-mapped, non-persisted) instance
        # attributes so get_all() keeps returning List[ChannelDB] — every existing
        # caller (get_hidden_channels, count, _apply_python_exclusions, ...) is
        # unaffected. ChannelListDTO.from_orm reads them back via ``_joined_plot``
        # / ``_joined_poster_url``.
        query = query.outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
        # COALESCE, not MetadataDB.poster_url alone: enrichment covers ~0.5% of
        # a real library while ingestion stores the provider's own poster on
        # logo_url for 97% of movies. Numbers and the search that exposed it:
        # tests/test_channel_list_posters.py.
        query = query.add_columns(
            MetadataDB.plot,
            func.coalesce(
                func.nullif(MetadataDB.poster_url, ""),
                func.nullif(ChannelDB.logo_url, ""),
            ),
        )

        if offset is not None:
            query = query.offset(offset)
        rows = query.limit(limit).all() if limit is not None else query.all()

        result = []
        for ch, plot, poster_url in rows:
            ch._joined_plot = plot or ""
            ch._joined_poster_url = poster_url or ""
            result.append(ch)
        return result

    def _get_all_collapsed(
        self, filtered_query, *, limit: Optional[int], offset: Optional[int],
        exclusion_sets=None, search_query: Optional[str] = None,
    ) -> List[ChannelDB]:
        """Collapse *filtered_query* (an already-WHERE-filtered ChannelDB query)
        to one representative row per content_key group, in SQL.

        Shares the window-function algorithm
        ``TagRepository._build_collapsed_sample_query`` already uses for the
        Discover/recipe collapse surfaces — ``ROW_NUMBER()``/``COUNT()``
        partitioned by ``COALESCE(content_key, 'id:' || id)`` — so pagination
        stays exact (a page never returns fewer than ``limit`` rows just
        because some were collapsed away; the LIMIT/OFFSET apply to GROUPS,
        not raw rows). Representative quality ranking is sourced from
        ``channel_name_utils.quality_tier_rank`` (the lookup-table single
        source of truth), not a second local ranking table.

        Only the bounded page of representative ids is re-fetched as full
        ORM rows (+ the same MetadataDB plot/poster outerjoin the
        uncollapsed path uses) and reordered in Python — reordering a
        page-sized list, never the whole matching set.
        """
        from sqlalchemy import case as _case, func as _func

        from metatv.core.channel_name_utils import (
            QUALITY_TIER_RANK, _QUALITY_TIER_RANK_DEFAULT,
        )

        inner = filtered_query.subquery(name="inner_ch")

        group_key = _func.coalesce(
            inner.c.content_key, _func.concat("id:", inner.c.id)
        )

        # Invert QUALITY_TIER_RANK (higher int = better quality) into an
        # ascending SQL rank (lower = better) for ROW_NUMBER()'s default
        # ascending ORDER BY — single lookup source, never a parallel table.
        max_rank = max(QUALITY_TIER_RANK.values())
        whens = [
            (inner.c.detected_quality == token, max_rank - rank)
            for token, rank in QUALITY_TIER_RANK.items()
        ]
        rep_rank = _case(*whens, else_=max_rank - _QUALITY_TIER_RANK_DEFAULT)

        # Rows the caller will drop AFTER this query sort last, whatever their
        # quality. Without this the representative is elected from ALL variants
        # and only then filtered — so a title whose best-quality variant happens
        # to be globally excluded lost its representative and vanished entirely,
        # taking its perfectly visible variants with it. Measured on the real
        # library: 18,486 titles disappeared that way, each with at least one
        # variant the user had not excluded.
        #
        # The docstring for ``excluded_provider_ids`` already states this
        # invariant — "a hidden/expired-provider variant can never be
        # excluded-from-set-yet-still-win the representative slot" — because
        # that axis is a WHERE predicate. The Global-Exclusion axes are applied
        # in Python by the caller, so they needed the same guarantee by another
        # route.
        #
        # DEPRIORITISE, not filter. Filtering here would elect no representative
        # at all for a fully-excluded group, which is the right outcome — but it
        # would also silently change ``_variant_count`` (the ×N badge) and
        # zero out the caller's hidden-by-exclusions diff, which is computed by
        # comparing row counts either side of its Python pass. Ranking leaves
        # both intact: a group with any visible variant elects a visible one, a
        # group with none still elects the row the caller then correctly drops.
        # Built against ``inner.c``, NOT against ChannelDB. The window runs over
        # the subquery; a clause referencing the mapped class would add
        # ``channels`` as a second FROM element and SQLite would answer with a
        # cartesian product — which it did, turning a 15-row group into a
        # variant count of 7,386,000 before this was caught.
        rank_terms = [rep_rank, inner.c.id]
        penalty = _collapse_rank_penalty(
            channel_cls=inner.c, **(exclusion_sets or {})
        )
        if penalty is not None:
            rank_terms.insert(0, penalty)

        # GROUP BY + MIN(packed key), NOT ROW_NUMBER(). Measured on the owner's
        # library: 8.34 s -> 1.63 s, with byte-identical output — same
        # representative ids, same variant counts, same order, verified across
        # six page/filter combinations including deep offsets and both the
        # with- and without-penalty forms.
        #
        # The window form has to materialise a row number for EVERY row before
        # it can keep the ones numbered 1, so LIMIT cannot prune anything and
        # asking for 100 rows costs the same as asking for 1,000. Grouping
        # collapses each title as it scans.
        #
        # HOW THE PACKING WORKS, because an off-by-one here elects the wrong
        # row silently. `ORDER BY penalty, rank, id` and `MIN(penalty || rank
        # || id)` agree only while penalty and rank are FIXED WIDTH — otherwise
        # a two-digit rank sorts before a one-digit one. Both widths are
        # therefore derived from their actual ranges rather than assumed, and
        # the substr offset is derived from the widths, so adding a quality
        # tier that pushes rank to two digits stays correct instead of quietly
        # re-electing every representative.
        pen_width = 1 if penalty is not None else 0
        rank_width = len(str(_MAX_QUALITY_RANK))
        parts = _func.printf(f"%0{rank_width}d", rep_rank)
        if penalty is not None:
            parts = _func.printf(f"%0{pen_width}d", penalty).concat(parts)
        packed = parts.concat(inner.c.id)

        grouped = (
            self.session.query(
                _func.min(packed).label("packed"),
                _func.count(inner.c.id).label("vc"),
            )
            .group_by(group_key)
            .subquery(name="grouped")
        )

        # Order representatives the same way the uncollapsed path orders rows
        # (ChannelDB.name) — the representative's own name, with an id
        # tiebreak so ties can't reorder between adjacent LIMIT/OFFSET pages.
        # The join back is what makes that name available: the grouped query
        # holds only aggregates, and MIN(name) would be the alphabetically
        # first name in the GROUP, which is a different row than the one
        # elected. That distinction is the whole reason this is a join and not
        # one more aggregate.
        rep_id_expr = _func.substr(grouped.c.packed, pen_width + rank_width + 1)
        reps_q = (
            self.session.query(
                ChannelDB.id.label("rep_id"),
                grouped.c.vc.label("vc"),
            )
            .select_from(grouped)
            .join(ChannelDB, ChannelDB.id == rep_id_expr)
        )
        reps_q = reps_q.order_by(*search_order_terms(search_query, ChannelDB))
        if offset is not None:
            reps_q = reps_q.offset(offset)
        reps = reps_q.limit(limit).all() if limit is not None else reps_q.all()
        if not reps:
            return []

        vc_by_id = {row.rep_id: row.vc for row in reps}
        rep_ids = [row.rep_id for row in reps]
        order_map = {rid: i for i, rid in enumerate(rep_ids)}

        rows = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(rep_ids))
            .outerjoin(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
            .add_columns(
                MetadataDB.plot,
                func.coalesce(
                    func.nullif(MetadataDB.poster_url, ""),
                    func.nullif(ChannelDB.logo_url, ""),
                ),
            )
            .all()
        )
        result = []
        for ch, plot, poster_url in rows:
            ch._joined_plot = plot or ""
            ch._joined_poster_url = poster_url or ""
            ch._variant_count = vc_by_id.get(ch.id, 1)
            result.append(ch)
        result.sort(key=lambda ch: order_map.get(ch.id, 0))
        return result

    def _apply_channel_filters(
        self,
        query,
        *,
        provider_id=None,
        media_type: Optional[str] = None,
        media_types: Optional[List[str]] = None,
        language_prefixes: Optional[List[str]] = None,
        region_prefixes: Optional[List[str]] = None,
        quality_prefixes: Optional[List[str]] = None,
        platform_prefixes: Optional[List[str]] = None,
        genre_filters: Optional[List[str]] = None,
        include_hidden: bool = False,
        hidden_only: bool = False,
        downloaded_only: bool = False,
        invert_prefix_filters: bool = False,
        include_untagged: bool = True,
        include_untagged_quality: bool = True,
        adult_mode: str = "all",
        force_adult_provider_ids: Optional[List[str]] = None,
        source_categories: Optional[List[str]] = None,
        include_uncategorized_content_types: bool = True,
        search_query: Optional[str] = None,
        strict_genre_filter: Optional[str] = None,
        person_filter: Optional[str] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        tag_includes: Optional[Dict[str, Set[str]]] = None,
        facets_hiding_untagged: Optional[Set[str]] = None,
        context_tag_filter: Optional[Tuple[str, str]] = None,
        context_category_filter: Optional[str] = None,
        channel_ids: Optional[Set[str]] = None,
        exclude_watched: bool = False,
        include_dead: bool = False,
        excluded_keywords: Optional[List[str]] = None,
    ):
        """Apply the shared channel-list WHERE predicates to ``query``.

        Single source of truth for the channel-list filter clauses so the visible
        set (:meth:`get_all`) and any derived count (:meth:`count_watched_matching`)
        apply the SAME predicates and never drift.  Applies everything except
        ORDER BY / LIMIT / OFFSET and the watched-only constraint — callers add
        those.  See :meth:`get_all` for per-argument semantics.
        """
        if isinstance(provider_id, list):
            if provider_id:
                query = query.filter(ChannelDB.provider_id.in_(provider_id))
        elif provider_id:
            query = query.filter_by(provider_id=provider_id)

        # Media type filtering
        if media_types:
            query = query.filter(ChannelDB.media_type.in_(media_types))
        elif media_type:
            query = query.filter_by(media_type=media_type)

        # ── Channel visibility (provider / hidden / keyword / adult axes) ──────
        # Single chokepoint: metatv.core.channel_visibility.apply() — the
        # extracted, single definition of "which channels are visible" (see that
        # module's docstring). ``hidden_only`` (show ONLY hidden channels) has no
        # VisibilityScope field — it is the opposite direction from
        # ``include_hidden`` (show hidden ones TOO), so it stays a separate
        # predicate below. When ``hidden_only`` is set the scope's own
        # ``is_hidden == False`` gate must NOT also apply (it would contradict
        # ``hidden_only``'s own ``is_hidden == True`` filter below), hence
        # ``include_hidden=(include_hidden or hidden_only)``. ``downloaded_only``
        # forces provider/keyword exclusion empty — see channel_downloads.py.
        query = channel_visibility.apply(
            query,
            channel_visibility.VisibilityScope(
                **channel_downloads.visibility_overrides(
                    downloaded_only, excluded_provider_ids, excluded_keywords),
                adult_mode=adult_mode,
                force_adult_provider_ids=list(force_adult_provider_ids or []),
                include_hidden=bool(include_hidden or hidden_only),
            ),
            channel_cls=ChannelDB,
        )

        if hidden_only:
            query = query.filter(ChannelDB.is_hidden == True)  # noqa: E712
        elif downloaded_only:
            query = query.filter(channel_downloads.predicate())  # also skips the dead-stream gate below
        elif not include_hidden:
            # Graduated play-failure ledger (roadmap S3): a channel whose
            # reliability_state has graduated to "dead" (6+ consecutive
            # user-initiated play failures — StreamRetryRepository) is gated
            # out of the forward-looking list the same way is_hidden is, right
            # above. "flagged"/"degraded" rows stay visible — "degraded" is
            # rendered grayed-but-clickable via ChannelListDTO.reliability_state
            # (see channel_list_model.py). Engaged/record views (Favorites,
            # History, Queue) don't route through get_all(), so they stay exempt
            # per DR-0007, same as the is_hidden gate above.
            #
            # include_dead lifts this one gate on request — the list-query path's
            # mirror-not-cage reveal (wave6/hidden-accounting): the caller can
            # re-run the identical query with the gate off to count/show exactly
            # what it is hiding, without touching is_hidden or the junk filters
            # below.
            if not include_dead:
                dead_channel_ids = (
                    self.session.query(StreamRetryDB.channel_id)
                    .filter(StreamRetryDB.reliability_state == "dead")
                    .scalar_subquery()
                )
                query = query.filter(~ChannelDB.id.in_(dead_channel_ids))

        # Exclude provider category-header rows (e.g. "##### BEIN SPORTS #####").
        # These are label-only separators injected by some providers — not playable
        # streams.  Deliberate provider-junk drops, not user content: they are NOT
        # part of the user-facing hidden accounting (no count, no reveal — there is
        # nothing for the user to recover) and this predicate is unconditional.
        # The SQL pattern "##%" matches any name starting with ≥2 '#'.
        query = query.filter(ChannelDB.name.notlike("##%"))

        # Exclude PPV/event placeholder rows (e.g.
        # "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 ...").
        # These slots have no actual event scheduled — they are not playable.
        # Same as the "##%" filter above: deliberate provider-junk, not content —
        # intentionally excluded from the hidden-by-* accounting/reveal surfaces.
        # The "NO EVENT STREAMING" substring is the universal provider marker.
        query = query.filter(ChannelDB.name.notlike("%NO EVENT STREAMING%"))

        # ── Identity pool: Language OR Region OR Platform (all grow the result set) ──
        # Selecting more always expands results. Quality is the only restrictive axis.
        # When invert_prefix_filters=True, show channels NOT in the identity pool.
        identity_active = bool(language_prefixes or region_prefixes or platform_prefixes)

        if identity_active:
            # Build per-axis conditions, then OR them into one identity pool
            axis_conditions = []

            if language_prefixes:
                # Language matches on detected_prefix OR parenthetical detected_region suffix
                axis_conditions.append(or_(
                    ChannelDB.detected_prefix.in_(language_prefixes),
                    ChannelDB.detected_region.in_(language_prefixes),
                ))

            if region_prefixes:
                axis_conditions.append(
                    ChannelDB.detected_prefix.in_(region_prefixes)
                )

            if platform_prefixes:
                axis_conditions.append(
                    ChannelDB.detected_prefix.in_(platform_prefixes)
                )

            identity_cond = or_(*axis_conditions)

            if invert_prefix_filters:
                # Show channels whose detected_prefix is NOT in the identity pool.
                # Uses a flat NOT IN on detected_prefix only — the detected_region
                # OR branch used in the forward direction returns NULL (not False)
                # for null-region rows, and NOT NULL = NULL is falsy, incorrectly
                # excluding unidentified channels from the inverted result.
                pool_prefixes: list[str] = []
                if language_prefixes:
                    pool_prefixes.extend(language_prefixes)
                if region_prefixes:
                    pool_prefixes.extend(region_prefixes)
                if platform_prefixes:
                    pool_prefixes.extend(platform_prefixes)
                query = query.filter(
                    ~ChannelDB.detected_prefix.in_(pool_prefixes),
                    ChannelDB.detected_prefix.isnot(None),
                )
            elif include_untagged:
                # Include identity matches OR channels with no prefix/region at all
                query = query.filter(
                    or_(
                        identity_cond,
                        and_(
                            ChannelDB.detected_prefix.is_(None),
                            ChannelDB.detected_region.is_(None),
                        ),
                    )
                )
            else:
                query = query.filter(identity_cond)

        elif not include_untagged:
            # No identity filter active but caller wants to hide channels with no prefix
            query = query.filter(ChannelDB.detected_prefix.isnot(None))

        # ── Quality axis: AND/restrictive — narrows the identity pool ──
        # Excludes channels explicitly tagged with a non-selected quality tier.
        # By default (include_untagged_quality=True), channels with no quality tag
        # always pass — deselecting SD hides SD channels, not untagged content.
        if quality_prefixes:
            if include_untagged_quality:
                query = query.filter(or_(
                    ChannelDB.detected_quality.in_(quality_prefixes),
                    ChannelDB.detected_quality.is_(None),
                ))
            else:
                query = query.filter(ChannelDB.detected_quality.in_(quality_prefixes))

        # Content-type filter (source_category — live channels only)
        if source_categories is not None:
            cond = ChannelDB.source_category.in_(source_categories)
            if include_uncategorized_content_types:
                cond = or_(cond, ChannelDB.source_category.is_(None))
            query = query.filter(cond)

        # Genre filter — OR across selected genres; channels with no genre always pass.
        # genre_filters is a list of individual genre strings (already split from compound).
        if genre_filters:
            from sqlalchemy import text as _text
            no_genre_cond = or_(
                ChannelDB.raw_data.is_(None),
                _text("json_extract(raw_data, '$.genre') IS NULL"),
                _text("json_extract(raw_data, '$.genre') = ''"),
            )
            genre_like_conds = [no_genre_cond]
            for i, g in enumerate(genre_filters):
                genre_like_conds.append(
                    _text(f"json_extract(raw_data, '$.genre') LIKE :_genre{i}").bindparams(
                        **{f"_genre{i}": f"%{g}%"}
                    )
                )
            query = query.filter(or_(*genre_like_conds))

        # SQL text search pushdown (case-insensitive LIKE on channel name, director, cast)
        if search_query:
            query = query.filter(channel_text_search_predicate(search_query))

        # Strict genre filter — from details-pane genre chip clicks. No passthrough:
        # only movies/series matching the requested genre. Primary match is
        # ``detected_genres`` — the ingestion-computed canonical genre list
        # (same field ``discovery_engine.get_by_genre`` reads, see
        # ``update_detected_prefixes()``) — via the exact-match ``json_each``
        # pattern that function uses; falls back to a raw_data.genre LIKE for
        # rows ingested before detected_genres existed / not yet re-swept.
        if strict_genre_filter:
            query = query.filter(
                ChannelDB.media_type.in_(GENRE_MEDIA_TYPES),
                genre_predicate(strict_genre_filter),
            )

        # Person filter — from details-pane cast/director/crew chip clicks, and
        # the lightbox person lens. The predicate (enriched metadata, the channel
        # NAME incl. live, and the raw provider blobs) is defined once in
        # channel_lens.person_predicate so both surfaces resolve the same set.
        if person_filter:
            query = query.filter(person_predicate(person_filter))

        # ── Tag facet filter: per-facet correlated EXISTS (AND across, OR within) ──
        # Each constrained facet gets one EXISTS subquery against content_tags JOIN tags.
        # No id-set materialisation — the subqueries are ANDed into the outer WHERE so
        # pagination (LIMIT/OFFSET) and row counts remain in SQL.
        if tag_includes:
            # One criterion per facet, from the shared chokepoint: "a value I
            # ticked, OR nothing on this facet at all". This was a bare
            # EXISTS(matching tag), which made ABSENCE indistinguishable from a
            # wrong value — and since the tag corpus is deliberately sparse,
            # that made one unticked box cull the library (see
            # filter_utils.facet_include_criterion for the measured numbers).
            # Unticking a VALUE still excludes it exactly as strictly as before.
            from metatv.core.filter_utils import facet_include_criterion

            _strict = facets_hiding_untagged or set()
            for _ftype, _allowed in tag_includes.items():
                if not _allowed:
                    continue   # empty set = no constraint for this facet
                query = query.filter(facet_include_criterion(
                    _ftype, _allowed, allow_untagged=_ftype not in _strict,
                ))

        # ── Context filter chip (details-pane tag click): strict, exact, one tag ──
        # Separate from tag_includes (filter panel) so the chip is mutually exclusive
        # and ephemeral.  Exact (type, value) match — no hierarchy rollup (v1).
        if context_tag_filter:
            from sqlalchemy import exists as _exists, select as _sa_select
            from sqlalchemy.orm import aliased as _aliased
            from metatv.core.database import ContentTagDB as _ContentTagDB, TagDB as _TagDB

            _ctype, _cvalue = context_tag_filter
            _ct = _aliased(_ContentTagDB, flat=True)
            _t  = _aliased(_TagDB, flat=True)
            _subq = (
                _sa_select(_ct.channel_id)
                .join(_t, _t.id == _ct.tag_id)
                .where(
                    _ct.channel_id == ChannelDB.id,
                    _t.type == _ctype,
                    _t.value == _cvalue,
                )
                .correlate(ChannelDB)
            )
            query = query.filter(_exists(_subq))

        # ── Context filter chip (COLLECTION click): the curated provider category ──
        # Group on the stored category (the human-curated grouping), NOT the lossy
        # 'collection' residual facet.  The control layer resolves the category value.
        if context_category_filter:
            query = query.filter(ChannelDB.category == context_category_filter)

        # ── Strict id-set filter (alert "show matches"): only these exact channels.
        # The stored ``alerted_ids`` for a watch-for rule — the normal visibility /
        # provider-scoping predicates above still apply, so an id on a hidden source
        # falls out and reads as "hidden by filters" downstream.
        if channel_ids is not None:
            query = query.filter(ChannelDB.id.in_(list(channel_ids)))

        # ── Watched filter: exclude channels the user has marked complete ──────
        # OFF by default (show everything). When ON, hides watch_completed=True rows.
        # Uses NOT (watch_completed == True) to safely pass NULL rows (never watched).
        if exclude_watched:
            query = query.filter(
                or_(
                    ChannelDB.watch_completed.is_(None),
                    ChannelDB.watch_completed == False,  # noqa: E712
                )
            )

        return query

    def _apply_adult_filter(self, q, adult_mode: str,
                            force_adult_provider_ids: Optional[List[str]] = None):
        """Apply adult content filter to a query. No-op when adult_mode == 'all'."""
        if adult_mode == "all":
            return q
        force_ids = force_adult_provider_ids or []
        is_adult_expr = (
            or_(ChannelDB.is_adult == True, ChannelDB.provider_id.in_(force_ids))  # noqa: E712
            if force_ids else (ChannelDB.is_adult == True)  # noqa: E712
        )
        return q.filter(~is_adult_expr) if adult_mode == "hide" else q.filter(is_adult_expr)

    def get_recent_history(self, limit: int = 30, adult_mode: str = "all",
                           force_adult_provider_ids: Optional[List[str]] = None) -> List[ChannelDB]:
        """Get recently played channels."""
        q = self.session.query(ChannelDB).filter(ChannelDB.last_played.isnot(None))
        q = self._apply_adult_filter(q, adult_mode, force_adult_provider_ids)
        return q.order_by(ChannelDB.last_played.desc()).limit(limit).all()
    
    def mark_played(self, channel_id: str):
        """Mark channel as played - updates last_played and increments play_count"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.last_played = datetime.now()
            channel.play_count = (channel.play_count or 0) + 1
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Marked channel as played: {channel.name} (count: {channel.play_count})")

    def update_stream_url(self, channel_id: str, stream_url: str) -> None:
        """Persist a URL that a play-time failover proved works, so it sticks.

        Called once, by the play-time failover path (``_bg_validate_and_play``
        in ``main_window_streaming.py``) after
        ``validate_and_failover_stream_url`` finds a working alternate host —
        otherwise every subsequent play of this item re-starts from the dead
        host and re-pays the failover stall. Scoped to this one channel row
        only (never a provider-wide rewrite). A no-op, not an error, if the
        channel no longer exists (e.g. deleted mid-flight).

        Args:
            channel_id: The channel row to update.
            stream_url: The new, already-validated stream URL to store.
        """
        channel = self.get_by_id(channel_id)
        if not channel:
            return
        channel.stream_url = stream_url
        channel.updated_at = datetime.now()
        self.session.commit()

    def search(self, query: str, provider_id: Optional[str] = None,
               media_type: Optional[str] = None,
               hidden_only: bool = False,
               excluded_provider_ids: Optional[List[str]] = None) -> List[ChannelDB]:
        """Search channels by name"""
        if hidden_only:
            hidden_filter = (ChannelDB.is_hidden == True)  # noqa: E712
        else:
            hidden_filter = (ChannelDB.is_hidden == False)  # noqa: E712
        db_query = self.session.query(ChannelDB).filter(
            channel_text_search_predicate(query),
            hidden_filter,
        )

        if provider_id:
            db_query = db_query.filter_by(provider_id=provider_id)

        if media_type:
            db_query = db_query.filter_by(media_type=media_type)

        if excluded_provider_ids:
            db_query = db_query.filter(
                ~ChannelDB.provider_id.in_(excluded_provider_ids)
            )

        return db_query.order_by(ChannelDB.name).all()
    
    def get_by_category(self, category: str, provider_id: Optional[str] = None) -> List[ChannelDB]:
        """Get channels by category"""
        query = self.session.query(ChannelDB).filter_by(
            category=category,
            is_hidden=False
        )
        
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        
        return query.order_by(ChannelDB.name).all()
    
    def get_categories(self, provider_id: Optional[str] = None) -> List[str]:
        """Get list of unique categories"""
        query = self.session.query(ChannelDB.category).distinct()
        
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        
        return [cat[0] for cat in query.all() if cat[0]]
    
    def bulk_create_or_update(self, channels: List[ChannelDB]):
        """Bulk create or update channels.

        On update, only provider-catalog columns are copied from the incoming row —
        user/derived fields (is_favorite, last_played, play_count, watch_progress,
        watch_completed, detected_*, content_key, tag_fingerprint, is_hidden,
        user_category, …) are preserved, exactly like the primary provider-refresh
        upsert path.
        """
        # Reuse the single catalog-column allowlist that the provider-refresh upsert
        # uses (imported lazily so this core repo keeps no load-time UI dependency).
        # Copying only these guards user/derived fields from being clobbered.
        from metatv.core.provider_loader import _CATALOG_UPDATE_COLS

        for channel in channels:
            existing = self.get_by_id(channel.id)
            if existing:
                # Update existing — catalog columns only, never user/derived fields.
                for key in _CATALOG_UPDATE_COLS:
                    setattr(existing, key, getattr(channel, key))
                existing.updated_at = datetime.now()
            else:
                # Create new
                self.session.add(channel)

        self.session.commit()
        logger.info(f"Bulk created/updated {len(channels)} channels")
    
    def count(self, provider_id: Optional[str] = None,
              media_type: Optional[str] = None) -> int:
        """Count channels with optional filters"""
        query = self.session.query(ChannelDB).filter_by(is_hidden=False)

        if provider_id:
            query = query.filter_by(provider_id=provider_id)

        if media_type:
            query = query.filter_by(media_type=media_type)

        return query.count()

    def count_keyword_matches(self, keywords: List[str]) -> Dict[str, int]:
        """Return ``{keyword: matching_channel_count}`` for the Global Exclusions
        Keywords section's live per-row counts ("wrestling — 412 channels").

        Runs one bounded ``COUNT(*)`` per keyword — an indexed-column scan plus an
        ``ilike`` substring test against ``COALESCE(detected_title, name)``, the
        SAME expression :func:`~metatv.core.filter_utils.keyword_exclusion_criterion`
        filters on, so a count shown here always matches what that keyword would
        actually hide. No id-set materialisation; safe to call off the UI thread
        against the full ``channels`` table (240k+ rows) — a leading-wildcard
        ``ilike`` cannot use an index, so each keyword is one full-table COUNT scan,
        but the keyword list itself is small (dozens at most).

        Scope mirrors the Exclusions dialog's other per-item counts (prefix,
        content-type): ``media_type IN (movie, series, live)``, no ``is_hidden``
        filter (so a count reflects the whole library, not just what's currently
        visible under other filters — consistent with ``_load_prefix_counts``).

        Args:
            keywords: Keyword strings to count (blank/whitespace-only entries are
                skipped and omitted from the result).

        Returns:
            ``{keyword: count}`` — a key is omitted only when *keywords* itself
            was blank; an unmatched keyword still gets an entry with count 0.
        """
        if not keywords:
            return {}
        from sqlalchemy import func as _func
        title_expr = _func.coalesce(ChannelDB.detected_title, ChannelDB.name)
        counts: Dict[str, int] = {}
        for kw in keywords:
            cleaned = (kw or "").strip()
            if not cleaned:
                continue
            counts[cleaned] = (
                self.session.query(_func.count(ChannelDB.id))
                .filter(ChannelDB.media_type.in_(["movie", "series", "live"]))
                .filter(title_expr.ilike(f"%{cleaned}%"))
                .scalar()
            ) or 0
        return counts

    def filter_available_ids(
        self,
        ids: Set[str],
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> Set[str]:
        """Return the subset of *ids* whose channel is currently AVAILABLE.

        Single re-validation chokepoint for stored match ids (e.g. a watch-for
        rule's ``alerted_ids``, which can reference channels whose source was
        later disabled/expired).  Available = the channel exists, its provider is
        NOT in ``excluded_provider_ids`` (disabled/expired sources —
        ``ProviderRepository.get_hidden_provider_ids``, a top-level gate), and the
        channel itself is not user-hidden.  One bounded ``IN`` query — *ids* is a
        small stored set (dozens–hundreds).

        Args:
            ids: Stored channel ids to re-validate.
            excluded_provider_ids: Hidden (inactive ∪ expired) provider ids to gate out.

        Returns:
            The subset of *ids* that are currently available (never any id whose
            source is hidden or whose channel is hidden).
        """
        if not ids:
            return set()
        query = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.id.in_(list(ids)))
            .filter(ChannelDB.is_hidden.isnot(True))
        )
        if excluded_provider_ids:
            query = query.filter(~ChannelDB.provider_id.in_(list(excluded_provider_ids)))
        return {row[0] for row in query.all()}

    def count_watched_matching(self, **axes) -> int:
        """Count visible channels with ``watch_completed=True`` matching *axes*.

        Powers the "N hidden because watched" figure in the stats label when the
        "Hide watched" axis is ON.  Accepts the **same axis keyword arguments as
        :meth:`get_all`** and forwards every one that
        :meth:`_apply_channel_filters` understands, so the count is computed by
        the same predicates as the list it describes.

        **It takes ``**axes`` rather than re-declaring them for a reason.**  It
        used to hand-list 23 parameters and forward 26, and the caller hand-listed
        22 more to feed it — three enumerations of one axis set, kept in step by
        memory alone.  They had already drifted: ``channel_ids``,
        ``excluded_keywords`` and ``include_dead`` reached ``get_all`` and never
        reached the count, so a watched row excluded by a keyword was counted as
        "hidden because watched" when the list had dropped it for another reason
        entirely.  Forwarding by *derivation* — see ``_COUNT_WATCHED_OMITS`` — is
        what makes a newly added axis reach both paths without anyone
        remembering to add it, which is the whole failure mode CLAUDE.md names.

        Unknown keys raise ``TypeError`` rather than being silently ignored; the
        Python-side axes in ``_COUNT_WATCHED_IGNORED`` are accepted and skipped
        so a caller can splat its whole axis dict in.

        **Known limit, deliberate:** the axes ``get_all`` applies in *Python*
        after the query returns (``excluded_prefixes``,
        ``excluded_user_categories``, ``excluded_channel_ids``, ``tag_excludes``,
        ``collapse_variants``) cannot be applied to a SQL ``COUNT`` — there is no
        materialised list to post-filter.  When one of those is active this
        figure over-counts, by at most the number of watched rows that axis
        removes.  Materialising the list to make it exact would cost a second
        full scan for a number displayed in a status label; the honest cheap
        answer is preferred, exactly as with the page-cap floor in the sibling
        transparency counters.

        Args:
            **axes: Any :meth:`get_all` filter axis.  ``exclude_watched`` is
                ignored (this method narrows *to* watched rows) and visibility
                is forced to the visible set.

        Returns:
            Count of visible, watched channels matching *axes*.

        Raises:
            TypeError: If an axis name is not one ``get_all`` accepts.
        """
        forwarded = {
            k: v
            for k, v in axes.items()
            if k in _apply_channel_filters_axes() and k not in _COUNT_WATCHED_OMITS
        }
        unknown = (
            set(axes)
            - set(forwarded)
            - _COUNT_WATCHED_OMITS
            - _COUNT_WATCHED_IGNORED
        )
        if unknown:
            raise TypeError(
                f"count_watched_matching() got unexpected axis(es): "
                f"{sorted(unknown)}"
            )

        query = self._apply_channel_filters(
            self.session.query(ChannelDB),
            include_hidden=False,
            hidden_only=False,
            **forwarded,
        )

        # Watched-only constraint — the whole point of this method.  exclude_watched
        # is omitted (see _COUNT_WATCHED_OMITS) so this NARROWS to the watched rows.
        query = query.filter(ChannelDB.watch_completed == True)  # noqa: E712

        return query.count()


    def _retry_on_lock(self, label: str, fn, *args, **kwargs):
        """Call ``fn(*args, **kwargs)``, retrying on a transient SQLite lock.

        Shared by every write phase of :meth:`update_detected_prefixes` — the
        per-batch commit (:meth:`_commit_prefix_batch_with_retry`), region
        sibling propagation (:meth:`_propagate_region_from_siblings`), and tmdb
        sibling propagation (:meth:`propagate_tmdb_from_title_siblings`) — one
        helper instead of three copies (owner log 2026-08-01: the tmdb-sibling
        phase crashed on ``database is locked`` because only the batch commit
        had retry coverage before this).

        The loop is :func:`metatv.core.db_lock.retry_on_lock`; what stays here
        is the one thing that is genuinely this class's — rolling back the
        long-lived ``self.session`` between attempts, which a caller opening a
        fresh ``session_scope()`` per attempt does not need.

        A failed commit's rollback discards any pending in-memory changes, so
        ``fn`` must be safe to re-run from scratch — every current caller is a
        fill-empty-only bulk pass that re-queries on each call, so a retry
        simply re-scans and only re-applies whatever didn't make it into the
        last successful commit. Any other exception, or a lock error on the
        final attempt, re-raises immediately so the caller's
        crash-without-version-bump contract (#364) is unchanged.

        Args:
            label: Short phase name used in log messages only.
            fn: Callable to invoke (and retry from scratch on a lock error).
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            ``fn``'s return value from the successful attempt.
        """
        return retry_on_lock(
            label,
            lambda: fn(*args, **kwargs),
            before_retry=self.session.rollback,
            attempts=_LOCK_RETRY_ATTEMPTS,
            delay_s=_LOCK_RETRY_DELAY_S,
        )

    def reset_tmdb_enrich_state(self, provider_id: str) -> int:
        """Clear the attempt marker for one provider's rows **that are still idless**.

        Called from the content-refresh chokepoint (``provider_loader``) after a
        source is re-ingested, so an idless row that was previously attempted-empty
        (``'none'``) gets one more chance against the (possibly changed) catalog on
        the next lazy fetch.  Only the generated marker is touched.

        **Narrowed to idless rows only** (``detected_tmdb_id IS NULL``): a row that
        already carries an id — from the list (``'list'``), a title sibling
        (``'propagated'``), or a provider-detail fetch (``'fetched'``) — keeps both
        its id (preserved on refresh by the ``COALESCE`` in ``_flush_batch``) and
        its provenance marker, so enrichment is never re-done for a row that already
        resolved.  This is the fetch-once guarantee surviving refresh.

        Args:
            provider_id: The just-refreshed provider.

        Returns:
            Number of rows whose marker was cleared.
        """
        result = self.session.execute(
            update(ChannelDB)
            .where(ChannelDB.provider_id == provider_id)
            .where(ChannelDB.tmdb_enrich_state.isnot(None))
            .where(ChannelDB.detected_tmdb_id.is_(None))
            .values(tmdb_enrich_state=None)
        )
        self.session.commit()
        return result.rowcount or 0

    # ── Cross-source sibling lookup (content_key-based failover) ───────────────

    def get_content_key_siblings(
        self,
        content_key: str,
        exclude_channel_id: str,
        excluded_provider_ids: "Optional[Set[str] | List[str]]" = None,
    ) -> list[dict]:
        """Return sibling channels that share *content_key* but differ from the given channel.

        Two callers, one query:
        - **Cross-source playback failover** passes no ``excluded_provider_ids`` — it
          deliberately wants every sibling (including inactive/expired ones) so the
          failure toast can offer them and the failover can rank active-first itself.
        - **The Similar-titles lightbox "Other Versions" row** passes
          ``ProviderRepository.get_hidden_provider_ids()`` so hidden/expired/orphaned
          sources never surface — the same absolute gate as ``get_similar_channels``
          (DR-0007 active-source scoping).

        Ranking:
        1. Active providers first (``ProviderDB.is_active == True``).
        2. Higher detected quality (4K > FHD > HD > SD — channels without a quality
           token sort last within each tier).
        3. Name for stable ordering within each tier.

        NULL-guard: a NULL or empty ``content_key`` has no siblings by definition
        (rows with no key have arbitrary semantics) — returns [] immediately.

        Args:
            content_key: The stored ``content_key`` to match on.
            exclude_channel_id: The channel that just failed; excluded from results.
            excluded_provider_ids: Hidden provider ids to gate out (inactive ∪ expired
                ∪ orphaned). ``None``/empty applies no provider gate (the failover
                default). The visibility-scoped surfaces always pass
                ``get_hidden_provider_ids()``.

        Returns:
            List of plain dicts — safe to cross the Qt thread boundary:
            ``{id, name, stream_url, provider_id, source_id, media_type,
               provider_name, provider_icon, provider_color, detected_quality,
               detected_region, detected_prefix, is_active}`` (``is_active``/
               ``provider_name``/``provider_icon``/``provider_color`` come from
               the joined ``ProviderDB`` — the lightbox's "Other Versions" chips
               render the icon/colour as a compact source badge; ``source_id``/
               ``media_type`` let series-monitor mirror discovery resolve a
               fetchable (provider, source_id) pair without a second query).
        """
        from metatv.core.database import ProviderDB  # local import avoids circular

        if not content_key:
            return []

        _QUALITY_ORDER: dict[str, int] = {
            "4K": 0, "UHD": 0, "FHD": 1, "FHD+": 1, "HD": 2, "SD": 3,
        }

        q = (
            self.session.query(
                ChannelDB,
                ProviderDB.is_active,
                ProviderDB.name,
                ProviderDB.icon,
                ProviderDB.color,
            )
            .join(ProviderDB, ChannelDB.provider_id == ProviderDB.id, isouter=True)
            .filter(
                ChannelDB.content_key == content_key,
                ChannelDB.id != exclude_channel_id,
            )
        )
        excluded = list(excluded_provider_ids or [])
        if excluded:
            # Absolute gate: inactive/expired/orphaned sources never surface here.
            q = q.filter(~ChannelDB.provider_id.in_(excluded))
        rows = q.all()

        result: list[dict] = []
        for ch, is_active, provider_name, provider_icon, provider_color in rows:
            quality_rank = _QUALITY_ORDER.get(ch.detected_quality or "", 4)
            result.append({
                "id": ch.id,
                "name": ch.name,
                "stream_url": ch.stream_url,
                "provider_id": ch.provider_id,
                "source_id": ch.source_id,
                "media_type": ch.media_type,
                "provider_name": provider_name,
                # Source badge data for the lightbox "Other Versions" chips.
                "provider_icon": provider_icon or "",
                "provider_color": provider_color or "",
                "detected_quality": ch.detected_quality,
                "detected_region": ch.detected_region,
                "detected_prefix": ch.detected_prefix,
                "is_active": bool(is_active),
                "_quality_rank": quality_rank,
            })

        # Sort: active first, then quality rank, then name for stability
        result.sort(key=lambda r: (not r["is_active"], r["_quality_rank"], r["name"]))
        # Strip the private sort key before returning
        for r in result:
            r.pop("_quality_rank", None)
        return result

    def get_similar_channels(
        self,
        channel_id: str,
        excluded_provider_ids: "Optional[Set[str] | List[str]]" = None,
        limit: int = 20,
        config=None,
    ) -> "List[ChannelDB]":
        """Canonical "Similar Titles" query — ranked, content_key-deduped, provider-scoped.

        Single source of truth for the two Similar-Titles surfaces (the details-pane
        row and the similar-titles lightbox). Both call this **inside their own
        session** and shape their own output DTO from the returned rows: this method
        owns the candidate selection *and the visibility predicate*; the callers own
        hydration. It replaces the two near-duplicate hand-rolled queries that each
        filtered only ``is_hidden`` and leaked disabled/expired-source content.

        Matching (preserves the prior behavior of both surfaces):
        - Same ``media_type`` as the origin channel; excludes the origin row itself.
        - Word-overlap heuristic on the origin's ``normalize_title`` words of length
          ≥ 4: a candidate qualifies when it shares ≥ ``max(1, len(words)//2)`` of
          them (non-ASCII is blanked before splitting a candidate's words).
        - Collapses same-production variants via the shared
          ``channel_lens.collapse_best_variant`` (``content_key`` or title,
          best-scored variant per group — requires *config*; without it the first
          variant encountered per group wins).
        - Drops any candidate whose ``build_dedup_key`` equals the origin's current
          key (its own other-source variants belong in "Other Versions", not here).

        Visibility — the absolute gate (DR-0007 active-source scoping):
        - every axis in ``VisibilityScope`` — per-channel hide, hidden
          providers, prefixes, categories, content-type tags, keywords and the
          adult gate — applied by the one predicate, **and**
        - ``provider_id NOT IN excluded_provider_ids`` — the inactive ∪ expired ∪
          orphaned providers the caller supplies via
          ``ProviderRepository.get_hidden_provider_ids()``. Content from a
          disabled/expired source must never surface here.

        Global Filter (Exclusions) — the SAME language/category blacklist Discover
        applies (all three Similar surfaces route through here, so a globally-hidden
        language never leaks into Similar / Explore / the lightbox strip):
        - When *config* is supplied and Global Exclusions are not paused, drops any
          candidate whose ``detected_prefix`` is in the excluded set (the category
          blacklist ∪ the explicit "Block [PREFIX]" codes), honoring
          ``include_uncategorized`` (untagged rows stay visible unless it is False).
        - Resolved via the shared ``filter_utils`` resolvers and applied with the
          canonical ``discovery_engine._apply_prefix_filter`` predicate (single
          source of truth — never a parallel excluded-set). ``config=None`` or paused
          applies nothing.

        Args:
            channel_id: Origin channel whose neighbours to find.
            excluded_provider_ids: Hidden provider ids to exclude. None/empty applies
                no provider gate — callers always pass ``get_hidden_provider_ids()``.
            limit: Max number of collapsed groups to return.
            config: Optional ``Config``. Scores the per-group winner by the user's
                version preferences (prefix/provider/quality) AND supplies the Global
                Filter exclusions above. ``None`` applies neither.

        Returns:
            Ranked list of ``ChannelDB`` rows. These are ORM objects — consume them
            inside the caller's session and map to DTOs before crossing a thread
            boundary (ORM-to-DTO rule).
        """
        from metatv.core.content_dedup import normalize_title, build_dedup_key

        channel = self.session.get(ChannelDB, channel_id)
        if not channel:
            return []

        norm = normalize_title(channel.name, channel.detected_prefix)
        words = [w for w in norm.split() if len(w) >= 4]
        if not words:
            return []

        q = (
            self.session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == channel.media_type,
                ChannelDB.id != channel_id,
                channel_text_search_predicate(words[0]),
            )
        )
        # EVERY exclusion axis, through the one predicate. This used to hand-roll
        # is_hidden and the provider gate and then call a helper that applied two
        # of the six axes — so 215 adult/restricted rows and 114 content-type
        # tagged rows could surface in all three Similar surfaces while every
        # other view hid them. Adding an axis to VisibilityScope now reaches this
        # query without anyone remembering it exists.
        q = channel_visibility.apply(q, visibility_resolver.resolve_scope(
            self.session, config,
            excluded_provider_ids=excluded_provider_ids or ()))
        candidates = q.limit(_SIMILAR_CANDIDATE_SCAN).all()

        threshold = max(1, len(words) // 2)
        current_meta = (
            self.session.get(MetadataDB, channel.metadata_id)
            if channel.metadata_id else None
        )
        current_key = build_dedup_key(channel, current_meta)

        # Collapse same-production variants, keeping the best-scored version per group
        # so a user with a preferred prefix/provider/quality sees that copy. Group key
        # prefers the stored content_key (localized/translated + "MULTI" variants share
        # a key and collapse exactly as on Discover/Other-Versions); falls back to the
        # normalized title only for rows with no content_key (pre-backfill).
        matches: "list[ChannelDB]" = []
        for ch in candidates:
            ch_norm = normalize_title(ch.name, ch.detected_prefix)
            ch_norm_ascii = _SIMILAR_NON_ASCII_RE.sub(" ", ch_norm).strip()
            ch_words = {w for w in ch_norm_ascii.split() if len(w) >= 4}
            overlap = sum(1 for w in words if w in ch_words)
            if overlap < threshold or ch_norm == norm:
                continue
            if current_key:
                ch_meta = (
                    self.session.get(MetadataDB, ch.metadata_id)
                    if ch.metadata_id else None
                )
                if build_dedup_key(ch, ch_meta) == current_key:
                    continue
            matches.append(ch)

        return collapse_best_variant(matches, config=config, limit=limit)

    def get_lens_channels(self, lens: str, value: str, **kwargs) -> "List[ChannelDB]":
        """Every visible title matching a facet — see ``channel_lens.lens_channels``.

        Lives on the repository so callers reach it the same way they reach
        every other channel query; the implementation is in
        ``metatv.core.repositories.channel_lens`` because the channel-list
        context chip and the lightbox lens must share one definition (and
        because this file is already 4k lines of recorded debt).
        """
        return lens_channels(self.session, lens, value, **kwargs)

    def get_live_events_dto(
        self,
        excluded_provider_ids: set[str] | None = None,
    ) -> list[LiveEventDTO]:
        """Return platform-event channels as plain DTOs — thread-safe, no live session.

        Queries ``ChannelDB.special_view == 'live_event'``, excluding hidden channels
        and channels on inactive/expired providers (forward-looking view). The caller
        should pass ``ProviderRepository.get_hidden_provider_ids()`` as
        ``excluded_provider_ids``.

        Sorting and grouping (Timeline / By-Network) are performed by the view layer,
        not here.

        Args:
            excluded_provider_ids: Provider IDs to exclude (inactive ∪ expired).

        Returns:
            List of :class:`LiveEventDTO` — safe to cross the Qt thread boundary.
        """
        q = (
            self.session.query(ChannelDB)
            .filter(
                ChannelDB.special_view == "live_event",
                ChannelDB.is_hidden == False,  # noqa: E712
            )
        )
        if excluded_provider_ids:
            q = q.filter(~ChannelDB.provider_id.in_(excluded_provider_ids))

        rows: list[LiveEventDTO] = []
        for ch in q.all():
            meta: dict = ch.event_metadata or {}
            network = meta.get("network", "") or ""
            region = meta.get("region", "") or ""
            channel_num = meta.get("channel_num", "") or ""
            availability = meta.get("availability", "") or ""
            always_available = (
                availability == "always" or ch.event_start_time is None
            )
            rows.append(LiveEventDTO(
                channel_id=ch.id,
                name=ch.name,
                detected_title=ch.detected_title,
                network=network,
                region=region,
                channel_num=channel_num,
                start_time=ch.event_start_time,
                always_available=always_available,
            ))
        return rows

    def update_category_mood(self, category: str, mood: str | None) -> int:
        """Update the mood for all channels in a user category."""
        updated = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.user_category == category)
            .update(
                {"category_mood": mood, "updated_at": datetime.now()},
                synchronize_session="fetch",
            )
        )
        self.session.commit()
        return updated

    # ── Cascade prune ──────────────────────────────────────────────────────────

    # Retained for backwards-compatibility (referenced by an existing test), but the
    # prune is no longer id-batched: it uses set-based, provider-scoped deletes that
    # resolve the doomed set with an indexed ``provider_id`` subquery — never
    # shipping the 294k+ ids to Python. See ``prune_provider_content``.
    _PRUNE_BATCH_SIZE = 2000

    def record_metadata_enrich_success(self, channel_id: str) -> None:
        """Clear retry bookkeeping after a successful enrichment.

        The freshly written ``MetadataDB.fetched_at`` is what actually excludes
        the channel from future candidate queries — this just resets the retry
        counter so a channel that failed a few times before eventually
        succeeding doesn't carry a stale count into its next staleness cycle.
        """
        self.session.execute(
            update(ChannelDB)
            .where(ChannelDB.id == channel_id)
            .values(metadata_enrich_state=None, metadata_enrich_attempts=0)
        )

    def record_metadata_enrich_failure(self, channel_id: str, max_attempts: int) -> int:
        """Bump *channel_id*'s failure count; mark permanently failed at *max_attempts*.

        Bounded-retry gate: once ``metadata_enrich_attempts`` reaches
        *max_attempts* the row is marked ``metadata_enrich_state='failed'``,
        which the candidate predicate excludes forever after — a chronically
        erroring channel (dead provider entry, no metadata anywhere) stops being
        re-attempted every drain.

        Args:
            channel_id: The channel whose fetch just failed.
            max_attempts: Attempt count at which the row is marked permanently failed.

        Returns:
            The row's attempt count after this failure (0 if the channel no
            longer exists — deleted between read and write).
        """
        row = (
            self.session.query(ChannelDB.metadata_enrich_attempts)
            .filter(ChannelDB.id == channel_id)
            .first()
        )
        if row is None:
            return 0
        attempts = (row[0] or 0) + 1
        state = "failed" if attempts >= max_attempts else None
        self.session.execute(
            update(ChannelDB)
            .where(ChannelDB.id == channel_id)
            .values(metadata_enrich_attempts=attempts, metadata_enrich_state=state)
        )
        return attempts

