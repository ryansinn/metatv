"""Channel repository for data access"""

import re
import time
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import OperationalError
from loguru import logger

from metatv.core.database import (
    ChannelDB, MetadataDB, SeasonDB, EpisodeDB,
    EpgProgramDB, UserRatingDB, AlertMatchDB, WatchQueueDB, ProviderDB,
    ContentTagDB, StreamRetryDB,
)
from metatv.core.filter_utils import (
    extract_prefix, categorize_prefix, normalize_genre, _GENRE_NORM, genres_from_raw,
)
from metatv.core.channel_name_utils import (
    parse_channel_name, normalize_region_code, QUALITY_TOKENS,
    _COMPOUND_PREFIX_RE, _PAREN_PREFIX_RE, detect_ai_provenance,
    AI_VOICEOVER_VALUE, is_restricted,
)
from metatv.core.repositories.dtos import (
    FavoriteDTO, LiveEventDTO,
    TmdbFunnelDTO, MissingTmdbRowDTO, MissingTmdbSourceDTO,
)
from metatv.core.repositories.channel_stats import _ChannelStatsMixin
from metatv.core.content_identity import content_key_for, valid_tmdb_id
from metatv.core.tag_decomposer import region_code_from_category


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
_LOCK_RETRY_ATTEMPTS = 3
_LOCK_RETRY_DELAY_S = 2.0


class _TmdbKeyProxy:
    """Minimal duck-typed channel for :func:`content_key_for` (tmdb-first path).

    ``content_key_for`` reads its inputs via ``getattr(..., default)``; a valid
    ``detected_tmdb_id`` short-circuits to ``"tmdb:{id}|{media_type}"`` before the
    title/year fields are consulted, so only these three attributes are needed to
    recompute the key when the enrichment discovers an id.
    """

    __slots__ = ("detected_tmdb_id", "media_type", "id")

    def __init__(self, detected_tmdb_id: str, media_type: str, id: str) -> None:
        self.detected_tmdb_id = detected_tmdb_id
        self.media_type = media_type
        self.id = id


_YEAR4_RE = re.compile(r"\b(\d{4})\b")


def _start_year_int(detected_year) -> Optional[int]:
    """Return the first 4-digit year in *detected_year* as an int, or ``None``.

    Mirrors ``content_identity._start_year`` (ranges ``"2015-2018"`` → 2015,
    ``"(2024)"`` → 2024, junk/empty → ``None``) but yields an ``int`` for the
    ``abs(a - b) <= 1`` remake-compatibility comparison used by the tmdb
    title-sibling propagation.
    """
    if not detected_year:
        return None
    m = _YEAR4_RE.search(str(detected_year))
    return int(m.group(1)) if m else None


# Scene-release noise tokens — their presence in a "title" means the row kept a
# release filename (e.g. "Movie.2019.1080p.WEB.x264-GROUP"), which a title search
# would NOT match cleanly.  Used only for the qualitative TMDb-addressability flag
# in the Missing-TMDb diagnostic (never for identity/collapse).
_SCENE_NOISE_TOKENS = frozenset({
    "1080p", "720p", "480p", "2160p", "4k", "x264", "x265", "h264", "h265",
    "hevc", "web", "webrip", "web-dl", "webdl", "bluray", "brrip", "bdrip",
    "hdrip", "dvdrip", "hdtv", "xvid", "aac", "ac3", "dts", "hdr", "remux",
})


def _looks_tmdb_addressable(detected_title, media_type, detected_year) -> bool:
    """Qualitative guess: could an external TMDb title search likely resolve this row?

    Decision-support only (never identity): a clean, short title — plus a year for
    movies — is plausibly matchable; a scene-release filename or an empty title is
    not.  Deliberately conservative so the "K titles the TMDb API could resolve"
    figure isn't inflated by junk rows.

    Args:
        detected_title: The stored, already-stripped title (may be None).
        media_type: ``"movie"`` / ``"series"``.
        detected_year: The stored year string (may be None).

    Returns:
        True when the row looks like a plausible title-search target.
    """
    if not detected_title:
        return False
    # Split on any non-alphanumeric run so dot-separated scene filenames
    # ("Movie.2019.1080p.WEB.x264-GRP") tokenize like space-separated ones.
    tokens = [t for t in re.split(r"[^a-z0-9]+", detected_title.lower()) if t]
    if not tokens or len(tokens) > 12:
        return False
    if any(t in _SCENE_NOISE_TOKENS for t in tokens):
        return False
    # Movies benefit from a disambiguating year; series are matchable on title alone.
    if media_type == "movie":
        return _start_year_int(detected_year) is not None
    return True


def _channel_text_search_predicate(search_term: str):
    """Shared free-text search predicate: channel name OR linked metadata director/cast.

    Single chokepoint for every "search box" filter over ``ChannelDB`` — every call
    site (``_apply_channel_filters``, ``search``, ``get_similar_channels``,
    ``get_hidden_channels``) routes through this instead of hand-rolling
    ``ChannelDB.name.ilike(...)`` alone, so a search for a cast member or director
    ("Nicole Kidman") also matches even when the channel *name* doesn't contain it.

    ``MetadataDB.cast`` is a ``JSONEncoded`` (``Text``-backed) column storing
    ``[{"name": ..., "character": ..., "photo_url": ...}]`` — matched with a plain
    substring ``ILIKE`` against the serialized JSON text, which is sufficient for a
    name lookup without a ``json_each`` split. ``MetadataDB.director`` is matched the
    same way. Both comparisons wrap the column in ``type_coerce(..., Text)`` first —
    without it, SQLAlchemy runs the ``JSONEncoded`` bind-processor on the search
    pattern too (JSON-encoding it into a quoted string literal), which silently
    never matches. Joins to ``MetadataDB`` via a correlated ``EXISTS`` (not a real
    JOIN) so callers can ``.filter()`` this onto any existing ``Query(ChannelDB)``
    without altering row cardinality or interacting with joins the caller already
    applied.

    Args:
        search_term: Raw (non-empty) user search text; wildcards are added here.

    Returns:
        A SQLAlchemy boolean clause suitable for ``query.filter(...)``.
    """
    pattern = f"%{search_term}%"
    return or_(ChannelDB.name.ilike(pattern), _metadata_person_exists(pattern))


def _metadata_person_exists(pattern: str):
    """Correlated EXISTS: the channel's linked ``MetadataDB`` row has a
    director/cast match for *pattern* (a SQL ``LIKE``/``ILIKE`` pattern,
    e.g. ``f"%{name}%"``).

    Single chokepoint for "does this channel's *enriched* metadata mention
    this person" — shared by :func:`_channel_text_search_predicate` (free-text
    search box) and the details-pane Cast/Crew context-chip filter
    (``ChannelRepository._apply_channel_filters`` ``person_filter`` branch).
    Both need the same shape (details pane displays ``MetadataDB.cast``/
    ``director``, so any filter over "who's in this" must match what's
    displayed, not the raw provider blob) — extend this helper for a future
    variant rather than forking a second correlated subquery.

    ``MetadataDB.cast`` is a ``JSONEncoded`` (``Text``-backed) column storing
    ``[{"name": ..., "character": ..., "photo_url": ...}]`` — matched with a
    plain substring ``ILIKE`` against the serialized JSON text, which is
    sufficient for a name lookup without a ``json_each`` split.
    ``MetadataDB.director`` is matched the same way. Both comparisons wrap the
    column in ``type_coerce(..., Text)`` first — without it, SQLAlchemy runs
    the ``JSONEncoded`` bind-processor on the search pattern too (JSON-encoding
    it into a quoted string literal), which silently never matches.
    """
    from sqlalchemy import exists as _exists, select as _sa_select, type_coerce as _type_coerce, Text as _Text

    # correlate(ChannelDB) is REQUIRED: get_all() now outerjoins MetadataDB (for
    # the list DTO's plot/poster columns), so without an explicit correlation
    # SQLAlchemy auto-correlates MetadataDB out of this subquery too and raises
    # "returned no FROM clauses due to auto-correlation".
    return _exists(
        _sa_select(MetadataDB.id)
        .where(
            MetadataDB.id == ChannelDB.metadata_id,
            or_(
                MetadataDB.director.ilike(pattern),
                _type_coerce(MetadataDB.cast, _Text).ilike(pattern),
            ),
        )
        .correlate(ChannelDB)
    )


class ChannelRepository(_ChannelStatsMixin):
    """Repository for channel data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, channel_id: str) -> Optional[ChannelDB]:
        """Get channel by ID"""
        return self.session.query(ChannelDB).filter_by(id=channel_id).first()

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
                tag_excludes: Optional[Dict[str, Set[str]]] = None,
                context_tag_filter: Optional[Tuple[str, str]] = None,
                context_category_filter: Optional[str] = None,
                channel_ids: Optional[Set[str]] = None,
                exclude_watched: bool = False,
                include_dead: bool = False,
                collapse_variants: bool = False,
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
        query = self.session.query(ChannelDB)
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
            context_tag_filter=context_tag_filter,
            context_category_filter=context_category_filter,
            channel_ids=channel_ids,
            exclude_watched=exclude_watched,
            include_dead=include_dead,
        )

        if collapse_variants:
            return self._get_all_collapsed(query, limit=limit, offset=offset)

        query = query.order_by(ChannelDB.name)

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
        query = query.add_columns(MetadataDB.plot, MetadataDB.poster_url)

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

        row_num = _func.row_number().over(
            partition_by=group_key,
            order_by=[rep_rank, inner.c.id],
        ).label("_rn")
        variant_count = _func.count(inner.c.id).over(
            partition_by=group_key,
        ).label("_variant_count")

        middle = self.session.query(inner, row_num, variant_count).subquery(
            name="windowed"
        )

        # Order representatives the same way the uncollapsed path orders rows
        # (ChannelDB.name) — the representative's own name, with an id
        # tiebreak so ties can't reorder between adjacent LIMIT/OFFSET pages.
        reps_q = (
            self.session.query(
                middle.c.id.label("rep_id"),
                middle.c._variant_count.label("vc"),
            )
            .filter(middle.c._rn == 1)
            .order_by(middle.c.name, middle.c.id)
        )
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
            .add_columns(MetadataDB.plot, MetadataDB.poster_url)
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
        context_tag_filter: Optional[Tuple[str, str]] = None,
        context_category_filter: Optional[str] = None,
        channel_ids: Optional[Set[str]] = None,
        exclude_watched: bool = False,
        include_dead: bool = False,
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

        if excluded_provider_ids:
            query = query.filter(~ChannelDB.provider_id.in_(excluded_provider_ids))

        # Media type filtering
        if media_types:
            query = query.filter(ChannelDB.media_type.in_(media_types))
        elif media_type:
            query = query.filter_by(media_type=media_type)

        if hidden_only:
            query = query.filter(ChannelDB.is_hidden == True)  # noqa: E712
        elif not include_hidden:
            query = query.filter_by(is_hidden=False)
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

        if adult_mode != "all":
            force_ids = force_adult_provider_ids or []
            # A channel is restricted if is_adult=True (provider-supplied flag) OR
            # detected_restricted=True (ingestion-computed XXX/ADULT/X-prefix naming
            # detection — catches the channels the provider flag misses, owner-reported
            # gap) OR its provider is force_adult.
            restricted_expr = or_(
                ChannelDB.is_adult == True,
                ChannelDB.detected_restricted == True,
            )
            if force_ids:
                restricted_expr = or_(
                    restricted_expr,
                    ChannelDB.provider_id.in_(force_ids),
                )

            if adult_mode == "hide":
                query = query.filter(~restricted_expr)
            elif adult_mode == "only":
                query = query.filter(restricted_expr)

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
            query = query.filter(_channel_text_search_predicate(search_query))

        # Strict genre filter — from details-pane genre chip clicks. No passthrough:
        # only movies/series matching the requested genre. Primary match is
        # ``detected_genres`` — the ingestion-computed canonical genre list
        # (same field ``discovery_engine.get_by_genre`` reads, see
        # ``update_detected_prefixes()``) — via the exact-match ``json_each``
        # pattern that function uses; falls back to a raw_data.genre LIKE for
        # rows ingested before detected_genres existed / not yet re-swept.
        if strict_genre_filter:
            from sqlalchemy import text as _text2
            _canon_genre = normalize_genre(strict_genre_filter)
            query = query.filter(
                ChannelDB.media_type.in_(["movie", "series"]),
                or_(
                    _text2(
                        "EXISTS (SELECT 1 FROM json_each(channels.detected_genres) AS dg_je "
                        "WHERE dg_je.value = :_strict_genre_exact)"
                    ).bindparams(_strict_genre_exact=_canon_genre),
                    _text2("json_extract(raw_data, '$.genre') LIKE :_strict_genre").bindparams(
                        _strict_genre=f"%{strict_genre_filter}%"
                    ),
                ),
            )

        # Person filter — from details-pane cast/director/crew chip clicks. The
        # details pane displays the ENRICHED MetadataDB.cast/director, so the
        # filter must match what's shown there first (via the shared
        # _metadata_person_exists EXISTS, also used by the free-text search
        # predicate) — otherwise an enriched-only row (e.g. a movie whose raw
        # provider feed carries no cast field, but MetadataDB.cast does) is
        # invisible to its own chip. Falls back to the raw_data.cast/director
        # LIKE match for un-enriched rows (most channels have no metadata_id).
        if person_filter:
            from sqlalchemy import text as _text3
            _person_pattern = f"%{person_filter}%"
            query = query.filter(
                or_(
                    _metadata_person_exists(_person_pattern),
                    _text3(
                        "json_extract(raw_data, '$.cast') LIKE :_person_cast"
                    ).bindparams(_person_cast=_person_pattern),
                    _text3(
                        "json_extract(raw_data, '$.director') LIKE :_person_dir"
                    ).bindparams(_person_dir=_person_pattern),
                )
            )

        # ── Tag facet filter: per-facet correlated EXISTS (AND across, OR within) ──
        # Each constrained facet gets one EXISTS subquery against content_tags JOIN tags.
        # No id-set materialisation — the subqueries are ANDed into the outer WHERE so
        # pagination (LIMIT/OFFSET) and row counts remain in SQL.
        if tag_includes:
            from sqlalchemy import exists as _exists, select as _sa_select
            from sqlalchemy.orm import aliased as _aliased
            from metatv.core.database import ContentTagDB as _ContentTagDB, TagDB as _TagDB

            for _ftype, _allowed in tag_includes.items():
                if not _allowed:
                    continue   # empty set = no constraint for this facet
                _ct = _aliased(_ContentTagDB, flat=True)
                _t  = _aliased(_TagDB, flat=True)
                _subq = (
                    _sa_select(_ct.channel_id)
                    .join(_t, _t.id == _ct.tag_id)
                    .where(
                        _ct.channel_id == ChannelDB.id,
                        _t.type == _ftype,
                        _t.value.in_(list(_allowed)),
                    )
                    .correlate(ChannelDB)
                )
                query = query.filter(_exists(_subq))

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

    def get_favorites(self, adult_mode: str = "all",
                      force_adult_provider_ids: Optional[List[str]] = None) -> List[ChannelDB]:
        """Get all favorite channels."""
        q = self.session.query(ChannelDB).filter_by(is_favorite=True, is_hidden=False)
        q = self._apply_adult_filter(q, adult_mode, force_adult_provider_ids)
        return q.order_by(ChannelDB.name).all()

    def get_favorites_dto(
        self,
        adult_mode: str = "all",
        force_adult_provider_ids: Optional[List[str]] = None,
        hidden_provider_ids: Optional[set] = None,
    ) -> "List[FavoriteDTO]":
        """Return favorite channels as plain DTOs — thread-safe, no live session required.

        get_favorites() intentionally keeps all favorited channels regardless of
        source state (engaged-content exception — CLAUDE.md). The ``available``
        field on each DTO annotates which entries are on a currently active source
        so the sidebar can dim them without altering the list ordering.

        Args:
            hidden_provider_ids: If supplied, channels whose ``provider_id`` is in
                this set are annotated with ``available=False``.
        """
        hidden: set = hidden_provider_ids or set()
        result = []
        for ch in self.get_favorites(adult_mode=adult_mode,
                                     force_adult_provider_ids=force_adult_provider_ids):
            pid = ch.provider_id
            result.append(FavoriteDTO(
                id=ch.id,
                name=ch.name,
                media_type=ch.media_type,
                last_played=ch.last_played,
                provider_id=pid,
                available=(not hidden or pid not in hidden),
                search_title=ch.detected_title or ch.name,
                detected_region=ch.detected_region or "",
                detected_quality=ch.detected_quality or "",
                detected_year=ch.detected_year or "",
                detected_prefix=ch.detected_prefix or "",
            ))
        return result

    def clear_unavailable_favorites(self, hidden_provider_ids: set) -> int:
        """Un-favorite channels whose provider is inactive/expired.

        Sets ``is_favorite=False`` (keeps the row; doesn't delete the channel)
        for every favorited, visible channel whose provider appears in
        ``hidden_provider_ids``.

        Args:
            hidden_provider_ids: Provider IDs to treat as unavailable.

        Returns:
            Number of channels un-favorited.
        """
        from datetime import datetime as _dt
        channels = (
            self.session.query(ChannelDB)
            .filter_by(is_favorite=True, is_hidden=False)
            .filter(ChannelDB.provider_id.in_(hidden_provider_ids))
            .all()
        )
        for ch in channels:
            ch.is_favorite = False
            ch.updated_at = _dt.now()
        return len(channels)

    def get_recent_history(self, limit: int = 30, adult_mode: str = "all",
                           force_adult_provider_ids: Optional[List[str]] = None) -> List[ChannelDB]:
        """Get recently played channels."""
        q = self.session.query(ChannelDB).filter(ChannelDB.last_played.isnot(None))
        q = self._apply_adult_filter(q, adult_mode, force_adult_provider_ids)
        return q.order_by(ChannelDB.last_played.desc()).limit(limit).all()
    
    def toggle_favorite(self, channel_id: str) -> bool:
        """Toggle favorite status and return new status"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_favorite = not channel.is_favorite
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} favorite status: {channel.is_favorite}")
            return channel.is_favorite
        return False
    
    def mark_played(self, channel_id: str):
        """Mark channel as played - updates last_played and increments play_count"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.last_played = datetime.now()
            channel.play_count = (channel.play_count or 0) + 1
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Marked channel as played: {channel.name} (count: {channel.play_count})")

    def mark_watched(self, channel_id: str, watched: bool = True) -> bool:
        """Mark a channel (movie/series) as watched/unwatched, setting all watch fields coherently.

        ChannelDB uses ``watch_completed`` as the "finished" flag (there is no
        ``is_watched`` column on channels — that is episode-only).  The field
        semantics parallel :meth:`EpisodeRepository.mark_watched` so the two
        paths never drift:

        watched=True  → watch_completed=True,  watch_percent=100,
                         last_played_via="manual"
                         (manual mark = deliberate → renders SOLID, not muted).
        watched=False → watch_completed=False, watch_percent=0,
                         watch_progress=0  (clear resume; item is truly unwatched).

        Returns True if the channel was found and updated, False if not found.
        """
        channel = self.get_by_id(channel_id)
        if channel is None:
            return False
        if watched:
            channel.watch_completed = True
            channel.watch_percent = 100
            channel.last_played_via = "manual"
        else:
            channel.watch_completed = False
            channel.watch_percent = 0
            channel.watch_progress = 0
        channel.updated_at = datetime.now()
        self.session.commit()
        logger.info(f"Marked channel {channel.name} as {'watched' if watched else 'unwatched'}")
        return True

    def mark_watched_bulk(self, channel_ids: "List[str]", watched: bool = True) -> int:
        """Mark multiple channels as watched/unwatched atomically.

        Same field semantics as :meth:`mark_watched`. Commits once for the batch.
        Returns the number of channels actually updated.
        """
        if not channel_ids:
            return 0
        updated = 0
        for channel_id in channel_ids:
            channel = self.get_by_id(channel_id)
            if channel is None:
                continue
            if watched:
                channel.watch_completed = True
                channel.watch_percent = 100
                channel.last_played_via = "manual"
            else:
                channel.watch_completed = False
                channel.watch_percent = 0
                channel.watch_progress = 0
            channel.updated_at = datetime.now()
            updated += 1
        if updated:
            self.session.commit()
        logger.info(f"Bulk marked {updated} channel(s) as {'watched' if watched else 'unwatched'}")
        return updated

    def record_watch_progress(
        self,
        channel_id: str,
        position_s: float,
        duration_s: float,
        threshold: float = 0.9,
        played_via: str = "manual",
    ) -> bool:
        """Record VOD watch progress: resume point + completion.

        Sets ``watch_progress`` (resume seconds), ``last_played``, and
        ``last_played_via``. When ``position_s / duration_s >= threshold`` the item
        is marked ``watch_completed`` and the resume point is cleared so a finished
        movie never resurfaces in "continue watching" at 99%. On a partial watch
        (below threshold), ``watch_completed`` is explicitly cleared so that
        re-watching a previously-finished title un-completes it — this restores the
        invariant ``watch_progress > 0 ⟺ not watch_completed``. ``play_count`` is
        owned by ``mark_played`` (at play start) — this method never touches it, so
        progress capture can't double-count a play.

        Returns True if this call marked the item complete.
        """
        channel = self.get_by_id(channel_id)
        if channel is None:
            return False
        completed = bool(duration_s and duration_s > 0 and (position_s / duration_s) >= threshold)
        pct = (
            min(100, max(0, round(position_s / duration_s * 100)))
            if duration_s and duration_s > 0
            else 0
        )
        channel.last_played = datetime.now()
        channel.last_played_via = played_via
        channel.watch_percent = 100 if completed else pct
        if completed:
            channel.watch_completed = True
            channel.watch_progress = 0
        else:
            channel.watch_completed = False  # re-watching a finished title un-completes it
            channel.watch_progress = max(0, int(position_s))
        channel.updated_at = datetime.now()
        self.session.commit()
        return completed

    def clear_history(self):
        """Clear all playback history"""
        count = self.session.query(ChannelDB).filter(
            ChannelDB.last_played.isnot(None)
        ).update({
            ChannelDB.last_played: None,
            ChannelDB.play_count: 0
        })
        self.session.commit()
        logger.info(f"Cleared history for {count} channels")
        return count
    
    def remove_from_history(self, channel_id: str) -> bool:
        """Remove single channel from history"""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.last_played = None
            channel.play_count = 0
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Removed {channel.name} from history")
            return True
        return False
    
    def set_hidden(self, channel_id: str, hidden: bool) -> None:
        """Set channel hidden status (removes from all views)."""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_hidden = hidden
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} hidden={hidden}")

    def set_rec_suppressed(self, channel_id: str, suppressed: bool) -> None:
        """Suppress/unsuppress channel from recommendations only."""
        channel = self.get_by_id(channel_id)
        if channel:
            channel.is_rec_suppressed = suppressed
            channel.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Channel {channel.name} rec_suppressed={suppressed}")

    def get_rec_suppressed(self) -> List[ChannelDB]:
        """Return all channels suppressed from recommendations, ordered by name."""
        return (
            self.session.query(ChannelDB)
            .filter(ChannelDB.is_rec_suppressed == True)  # noqa: E712
            .order_by(ChannelDB.name)
            .all()
        )

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
            _channel_text_search_predicate(query),
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
    
    def delete_by_provider(self, provider_id: str) -> int:
        """Delete all channels for a provider"""
        count = self.session.query(ChannelDB).filter_by(
            provider_id=provider_id
        ).delete()
        self.session.commit()
        logger.info(f"Deleted {count} channels for provider {provider_id}")
        return count
    
    def count(self, provider_id: Optional[str] = None,
              media_type: Optional[str] = None) -> int:
        """Count channels with optional filters"""
        query = self.session.query(ChannelDB).filter_by(is_hidden=False)

        if provider_id:
            query = query.filter_by(provider_id=provider_id)

        if media_type:
            query = query.filter_by(media_type=media_type)

        return query.count()

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

    def count_watched_matching(
        self,
        provider_id=None,
        media_types: Optional[List[str]] = None,
        excluded_provider_ids: Optional[List[str]] = None,
        search_query: Optional[str] = None,
        adult_mode: str = "all",
        force_adult_provider_ids: Optional[List[str]] = None,
        tag_includes: Optional[Dict[str, Set[str]]] = None,
        # DB-3 — the remaining get_all() filter axes.  These default to inactive so
        # existing callers keep compiling; when the caller forwards the same filters
        # it passed to get_all(), the count matches the visible set (no over-count).
        media_type: Optional[str] = None,
        language_prefixes: Optional[List[str]] = None,
        region_prefixes: Optional[List[str]] = None,
        quality_prefixes: Optional[List[str]] = None,
        platform_prefixes: Optional[List[str]] = None,
        genre_filters: Optional[List[str]] = None,
        invert_prefix_filters: bool = False,
        include_untagged: bool = True,
        include_untagged_quality: bool = True,
        source_categories: Optional[List[str]] = None,
        include_uncategorized_content_types: bool = True,
        strict_genre_filter: Optional[str] = None,
        person_filter: Optional[str] = None,
        context_tag_filter: Optional[Tuple[str, str]] = None,
        context_category_filter: Optional[str] = None,
    ) -> int:
        """Count visible channels with ``watch_completed=True`` matching the filters.

        Used to compute the "N hidden because watched" metric shown in the stats
        label when the "Hide watched" axis is ON.  Routes through the shared
        :meth:`_apply_channel_filters` chokepoint so it applies the SAME predicates
        as :meth:`get_all` (identity / quality / source-category / genre / context /
        …), then adds ``watch_completed == True`` and omits pagination — so the count
        matches the visible set exactly instead of over-counting when those axes are
        active.

        Note:
            The caller must forward the same filter arguments it passed to
            ``get_all``; any argument left at its default is treated as inactive.

        Args:
            provider_id: Same as ``get_all`` — str, list, or None.
            media_types: List of media types to include.
            excluded_provider_ids: Provider IDs to exclude.
            search_query: Optional search filter (LIKE on name).
            adult_mode: Adult content mode ("all", "hide", "only").
            force_adult_provider_ids: Provider IDs to treat as adult.
            tag_includes: Tier-1 tag-facet constraints (same as get_all).
            (remaining args): The other ``get_all`` filter axes — see that method.

        Returns:
            Count of matching visible channels with ``watch_completed=True``.
        """
        query = self.session.query(ChannelDB)
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
            include_hidden=False,
            hidden_only=False,
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
            context_tag_filter=context_tag_filter,
            context_category_filter=context_category_filter,
        )

        # Watched-only constraint — the whole point of this method.  (exclude_watched
        # is intentionally left at its default so this NARROWS to the watched rows.)
        query = query.filter(ChannelDB.watch_completed == True)  # noqa: E712

        return query.count()

    def update_detected_prefixes(
        self,
        provider_id: Optional[str] = None,
        separators: list[str] | None = None,
        progress_cb=None,
        is_cancelled=None,
        config=None,
    ):
        """Update detected_prefix, detected_quality, and detected_region for all channels.

        - detected_prefix: raw separator-delimited prefix token (e.g. "EN", "4K")
        - detected_quality: quality token found anywhere in the name (suffix or quality-prefix)
        - detected_region: parenthetical lang/region qualifier at end of name (e.g. "(US)"→"US")

        ``detected_region`` precedence (each step is **fill-empty-only** — a value
        set by an earlier step is never overwritten by a later one):

        1. **Name token** — bracket secondary / parenthetical lang-region suffix
           parsed from the channel name (highest priority, unchanged behavior).
        2. **Own provider-category code** — when the name yields no region, derive
           it from ``channel.category`` (e.g. ``"|FR|"`` → ``"FR"``) via
           :func:`~metatv.core.tag_decomposer.region_code_from_category` (the same
           extraction that produces the region tag facet — single source of truth).
        3. **content_key sibling** — a final cross-source pass copies a region onto
           any still-empty row from a sibling sharing the same (non-NULL)
           ``content_key``.  See :meth:`_propagate_region_from_siblings`.

        Args:
            provider_id: Only update channels for this provider, or None for all.
            separators: Ordered list of separator strings to try. Defaults to
                ``DEFAULT_PREFIX_SEPARATORS`` from filter_utils when None.
            progress_cb: Optional ``(done: int, total: int) -> None`` called after
                each batch commit.  ``done`` is non-decreasing and ends at
                ``total`` on full completion.  Pass ``None`` (default) to skip
                progress reporting (existing callers are unaffected).
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch iteration.  When it returns True the loop exits early;
                already-committed batches are durable but the task is not marked
                complete (version not bumped by the manager).  Pass ``None``
                (default) to run without cancellation support.
            config: Optional live ``Config`` instance — supplies the filter groups
                the category→region extraction consults.  Loaded lazily (default
                ``Config()``) when ``None`` so existing callers are unaffected.
        """
        _BATCH = 2000

        # The category→region fallback (step 2) needs the filter groups; load a
        # default Config once when the caller didn't pass one.
        if config is None:
            from metatv.core.config import Config
            config = Config()

        id_query = self.session.query(ChannelDB.id)
        if provider_id:
            id_query = id_query.filter(ChannelDB.provider_id == provider_id)
        all_ids = [row[0] for row in id_query.all()]
        total = len(all_ids)

        updated = 0
        processed = 0

        for batch_start in range(0, total, _BATCH):
            # Check for cancellation before starting each batch
            if is_cancelled is not None and is_cancelled():
                logger.info(
                    "update_detected_prefixes: cancelled at batch_start={}/{}",
                    batch_start,
                    total,
                )
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            batch_updated, batch_processed = self._commit_prefix_batch_with_retry(
                chunk_ids, separators, config,
            )
            updated += batch_updated
            processed += batch_processed

            # Expunge between batches to release ORM objects from memory before
            # loading the next chunk.  After the last batch there is nothing to
            # free, so we skip the expunge to leave any caller-held references
            # in a usable state (expunge_all would detach them).
            if batch_start + _BATCH < total:
                self.session.expunge_all()

            # Report progress after each committed batch
            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        # Step 3: cross-source sibling propagation — fill any still-empty
        # detected_region from a row sharing the same content_key. Skipped after a
        # cancellation (partial per-row state — don't propagate from it).
        sib_filled = 0
        tmdb_adopted = 0
        if not (is_cancelled is not None and is_cancelled()):
            # Both propagation phases below are bulk writers just like the batch
            # loop above and hit the identical lock-contention hazard (owner log
            # 2026-08-01 18:48: propagate_tmdb_from_title_siblings crashed on
            # `database is locked` at its bulk UPDATE, uncovered by #367's
            # batch-only retry). Both methods retry internally via the same
            # shared `_retry_on_lock` helper the batch loop uses, so every
            # write phase of this method gets identical lock-contention
            # coverage — including their OTHER caller, the standalone
            # tmdb_sibling_propagation migration task.
            sib_filled = self._propagate_region_from_siblings(provider_id)
            # Free (no-network) tmdb propagation: an idless row self-heals by adopting
            # a confident same-title sibling's detected_tmdb_id so new content collapses
            # without waiting for a background provider-detail fetch. Same shared helper
            # the one-time migration uses.
            tmdb_adopted = self.propagate_tmdb_from_title_siblings(provider_id)

        logger.info(
            f"Updated parsed name fields for {updated} of {processed} channels "
            f"(+{sib_filled} regions filled from content_key siblings, "
            f"+{tmdb_adopted} tmdb ids from title siblings)"
        )
        return updated

    def _retry_on_lock(self, label: str, fn, *args, **kwargs):
        """Call ``fn(*args, **kwargs)``, retrying on a transient SQLite lock.

        Shared by every write phase of :meth:`update_detected_prefixes` — the
        per-batch commit (:meth:`_commit_prefix_batch_with_retry`), region
        sibling propagation (:meth:`_propagate_region_from_siblings`), and tmdb
        sibling propagation (:meth:`propagate_tmdb_from_title_siblings`) — one
        helper instead of three copies (owner log 2026-08-01: the tmdb-sibling
        phase crashed on ``database is locked`` because only the batch commit
        had retry coverage before this).

        On ``OperationalError`` whose message contains "locked", rolls back the
        session and retries up to ``_LOCK_RETRY_ATTEMPTS`` times with a
        ``_LOCK_RETRY_DELAY_S`` sleep between attempts. A failed commit's
        rollback discards any pending in-memory changes, so ``fn`` must be safe
        to re-run from scratch — every current caller is a fill-empty-only bulk
        pass that re-queries on each call, so a retry simply re-scans and only
        re-applies whatever didn't make it into the last successful commit.
        Any other exception, or a lock error on the final attempt, re-raises
        immediately so the caller's crash-without-version-bump contract (#364)
        is unchanged — only lock contention retries.

        Args:
            label: Short phase name used in log messages only.
            fn: Callable to invoke (and retry from scratch on a lock error).
            *args: Positional arguments forwarded to ``fn``.
            **kwargs: Keyword arguments forwarded to ``fn``.

        Returns:
            ``fn``'s return value from the successful attempt.
        """
        for attempt in range(1, _LOCK_RETRY_ATTEMPTS + 1):
            try:
                return fn(*args, **kwargs)
            except OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                self.session.rollback()
                if attempt == _LOCK_RETRY_ATTEMPTS:
                    logger.error(
                        "{}: still locked after {} attempt(s), aborting run "
                        "(will retry next launch)",
                        label,
                        _LOCK_RETRY_ATTEMPTS,
                    )
                    raise
                logger.warning(
                    "{}: locked (attempt {}/{}); retrying in {}s",
                    label,
                    attempt,
                    _LOCK_RETRY_ATTEMPTS,
                    _LOCK_RETRY_DELAY_S,
                )
                time.sleep(_LOCK_RETRY_DELAY_S)
        raise AssertionError("unreachable")  # pragma: no cover

    def _commit_prefix_batch_with_retry(
        self,
        chunk_ids: list[str],
        separators: list[str] | None,
        config,
    ) -> tuple[int, int]:
        """Run one ``update_detected_prefixes`` batch, retrying on a transient lock.

        Delegates the actual query/compute/commit to :meth:`_process_prefix_batch`
        via the shared :meth:`_retry_on_lock` helper, which retries the *whole*
        batch (query included) — a failed commit leaves the session's in-memory
        changes expired after rollback, so re-running just ``session.commit()``
        would flush nothing; the batch must be recomputed from a fresh query.

        Args:
            chunk_ids: Channel ids in this batch.
            separators: Prefix separators passed through to per-channel parsing.
            config: Live ``Config`` instance for the category→region fallback.

        Returns:
            ``(batch_updated, batch_processed)`` from the successful attempt.
        """
        return self._retry_on_lock(
            "update_detected_prefixes: batch",
            self._process_prefix_batch,
            chunk_ids,
            separators,
            config,
        )

    def _process_prefix_batch(
        self,
        chunk_ids: list[str],
        separators: list[str] | None,
        config,
    ) -> tuple[int, int]:
        """Query, parse, and commit one ``update_detected_prefixes`` batch.

        Extracted from ``update_detected_prefixes`` so a lock retry
        (:meth:`_commit_prefix_batch_with_retry`) can re-run the whole batch —
        query, per-channel parse, and commit — from scratch, since a failed
        commit's rollback expires the session's pending in-memory changes and a
        bare retried ``commit()`` would have nothing left to flush.

        Args:
            chunk_ids: Channel ids in this batch.
            separators: Prefix separators passed through to per-channel parsing.
            config: Live ``Config`` instance for the category→region fallback.

        Returns:
            ``(batch_updated, batch_processed)`` — channels actually changed vs.
            total channels queried in this batch.
        """
        channels = self.session.query(ChannelDB).filter(
            ChannelDB.id.in_(chunk_ids)
        ).all()

        batch_updated = 0
        for channel in channels:
            raw_prefix = extract_prefix(channel.name, separators=separators)
            # Normalize full country/language names to standard codes:
            # "NIGERIA" → "NGA", "ENGLISH" → "EN", "TELUGU" → "TE", etc.
            prefix = normalize_region_code(raw_prefix) if raw_prefix else raw_prefix
            # Reject digit-only codes — these are provider-internal category numbers
            # (e.g. "300" from "300  - 2007"), not valid display prefixes.
            if prefix and re.match(r'^\d+$', prefix):
                prefix = None
                raw_prefix = None

            parsed = parse_channel_name(channel.name)

            # ── Compound prefix decomposition ────────────────────────────────── #
            # Handles "4K-DE - Title" (quality+lang), "SE-4K - Title" (lang+quality),
            # "PL 4K - Title" (lang+space+quality), and "[US] 4K-DE - Title" (bracket
            # before compound). When a compound is found the lang part overrides the
            # extracted prefix and the bracket (if any) moves to detected_region.
            compound_quality: str | None = None
            bracket_as_region: str | None = None

            cm = _COMPOUND_PREFIX_RE.match(channel.name)
            if cm:
                bracket    = cm.group("bracket")
                compound_lang = (
                    cm.group("lang_a") or cm.group("lang_b") or cm.group("lang_c") or ""
                ).upper()
                compound_q = (
                    cm.group("qual_a") or cm.group("qual_b") or cm.group("qual_c") or ""
                ).upper()

                # Guard: skip if the "lang" slot is itself a quality token (e.g. 4K-HD)
                if compound_lang and compound_lang not in QUALITY_TOKENS:
                    prefix = normalize_region_code(compound_lang)
                    compound_quality = compound_q or None
                    if bracket:
                        bracket_as_region = normalize_region_code(bracket)

            # Paren prefix: (QFR) Title — parenthetical code at start, not caught by extract_prefix
            if not cm:
                pm = _PAREN_PREFIX_RE.match(channel.name)
                if pm:
                    paren_code = pm.group(1).upper()
                    if paren_code not in QUALITY_TOKENS:
                        prefix = normalize_region_code(paren_code)

            # detected_quality priority:
            #   1. Name suffix  ("CNN HD" → "HD")
            #   2. Compound prefix quality  ("4K" from "4K-DE - Title")
            #   3. Quality-as-prefix  ("HD - Movie" → "HD")
            #   4. API quality field  (channel.quality = "hd" → "HD")
            quality: str | None = None
            if parsed.quality:
                quality = parsed.quality[0].upper()
            elif compound_quality:
                quality = compound_quality
            elif prefix and prefix.upper() in QUALITY_TOKENS:
                quality = prefix.upper()
                prefix = None  # quality token must not display as a category prefix
            elif channel.quality and channel.quality.upper() not in ("UNKNOWN", ""):
                api_q = channel.quality.upper()
                if api_q in QUALITY_TOKENS:
                    quality = api_q

            # Safety net: Guard #3 only fires when Guards 1 and 2 didn't. If Guard 1
            # (parsed.quality) fired first, prefix is still "4K". Clear it here regardless.
            if prefix and prefix.upper() in QUALITY_TOKENS:
                prefix = None

            # If prefix was cleared (quality token) or rejected (numeric guard), fall back to
            # what parse_channel_name extracted in step 1. This lets "[4K] [US] Title" store
            # detected_prefix = "US" rather than None after Guard #3 cleared "4K".
            if prefix is None and parsed.region:
                prefix = parsed.region

            # detected_region: bracket secondary (from compound decomposition) takes
            # priority, then parenthetical lang/region suffix (e.g. "(US)" → "US")
            region: str | None = bracket_as_region or parsed.lang or None

            # AI-provenance marker (single source of truth: detect_ai_provenance).
            # A trailing "(AI)" voiceover marker is TWO uppercase letters, so
            # parse_channel_name reads it as a bogus lang/region qualifier ("AI",
            # which is also the ISO code for Anguilla) and leaks it into region.
            # Clear it here — the marker is an AI dub, not a locale — so the
            # category/sibling fallbacks below can still fill a real region and no
            # bogus region facet is ever produced.  The content_type:ai_voiceover
            # tag carries the real signal.
            _ai_raw = detect_ai_provenance(channel.name)
            if (_ai_raw is not None and _ai_raw.value == AI_VOICEOVER_VALUE
                    and region and region.upper() == "AI"):
                region = None

            # Fill-empty fallback (step 2): when the NAME carries no region,
            # derive it from the provider category (e.g. "|FR|" → "FR") via the
            # shared tag_decomposer extraction. Never overwrites a name-derived
            # region; only explicit region codes qualify (free text → None).
            if not region and channel.category:
                region = region_code_from_category(channel.category, config=config)

            new_title = parsed.bare_name or None
            new_year  = parsed.year or None

            # If extract_prefix set a prefix that parse_channel_name couldn't strip
            # (_SEPARATOR_RE requires [A-Z] first char, so digit-starting codes like "24/7"
            # are not handled), do the strip manually now.
            if prefix and raw_prefix and new_title:
                _strip_m = re.match(
                    rf'^{re.escape(raw_prefix)}\s*(?:[★|]|-\s+)\s*(.+)$',
                    new_title,
                    re.IGNORECASE,
                )
                if _strip_m:
                    new_title = _strip_m.group(1).strip()

            # AI VOICEOVER title cleanup (safety net).  parse_channel_name almost
            # always strips a trailing "(AI)" already (it reads the two letters as
            # a lang qualifier), but if any voiceover marker survives into the
            # title, strip it here so the display title is clean and collapses onto
            # the base production — the content_type:ai_voiceover tag preserves the
            # distinction.  An "(AI Generated)" content marker is DELIBERATELY LEFT
            # in new_title: it flows into content_key below so a fabricated work
            # never shares a content_key with a real same-title production (keeping
            # content_key_for a single, consistent read of the stored detected_title
            # — no new identity machinery).  Only the recognized marker is touched.
            if new_title:
                _ai_title = detect_ai_provenance(new_title)
                if _ai_title is not None and _ai_title.value == AI_VOICEOVER_VALUE:
                    new_title = _ai_title.cleaned_name or None

            # Compute detected_audio from parsed audio fields.
            # Store None when there is no audio annotation so the column is cheap
            # (no JSON blob for the vast majority of channels with no sub/dub tag).
            new_detected_audio = None
            if parsed.audio_langs or parsed.dub_langs or parsed.sub_langs or parsed.audio:
                new_detected_audio = {
                    "form":  parsed.audio or "",
                    "audio": list(parsed.audio_langs),
                    "dub":   list(parsed.dub_langs),
                    "sub":   list(parsed.sub_langs),
                }
                # Normalize: drop all-empty dict to None
                if (not new_detected_audio["form"]
                        and not new_detected_audio["audio"]
                        and not new_detected_audio["dub"]
                        and not new_detected_audio["sub"]):
                    new_detected_audio = None

            # Compute canonical genre(s) from raw_data["genre"] (#genre-perf).
            # genres_from_raw() canonicalises each '/'/',' segment (cross-language
            # alias collapse + HTML-entity unescape). detected_genre = first
            # segment (display); detected_genres = every segment (shelf
            # membership via json_each in get_by_genre).
            _raw_genre_str = (channel.raw_data or {}).get("genre") if channel.raw_data else None
            _genre_list = genres_from_raw(_raw_genre_str)
            new_detected_genre  = _genre_list[0] if _genre_list else None
            new_detected_genres = _genre_list or None

            # Restricted-content detection (owner-reported gap): the provider's
            # is_adult flag is unreliable, so this catches XXX/ADULT/X-prefix naming
            # conventions it misses. Reads the UPDATED prefix (this batch's computed
            # value, not the old ORM one) so a channel whose prefix changes in this
            # same pass is judged on its new prefix. Separate provenance from
            # is_adult — never overwrites it. Detection is the user own "Adult" prefix
            # group + their (empty by default) restricted_keywords list.
            new_restricted = is_restricted(prefix, channel.name, config)

            # Compute the content_key from the UPDATED fields (not the old ORM values)
            # so the key is always in sync with detected_title/year/media_type.
            # Build a lightweight proxy that reflects the new field values without
            # mutating the channel yet — this lets us include content_key in the
            # changed comparison atomically.
            # detected_tmdb_id is a provider fact captured at ingestion (not
            # recomputed here) — read the already-stored value so the recomputed
            # content_key stays tmdb-first when the provider shipped an id.
            class _NewFields:
                __slots__ = (
                    "detected_title", "media_type", "detected_year",
                    "detected_tmdb_id", "id",
                )
                def __init__(self, title, mt, year, tmdb_id, ch_id):
                    self.detected_title = title
                    self.media_type = mt
                    self.detected_year = year
                    self.detected_tmdb_id = tmdb_id
                    self.id = ch_id
            new_content_key = content_key_for(
                _NewFields(
                    new_title, channel.media_type, new_year,
                    channel.detected_tmdb_id, channel.id,
                )
            )

            changed = (
                prefix != channel.detected_prefix
                or quality != channel.detected_quality
                or region != channel.detected_region
                or new_title != channel.detected_title
                or new_year  != channel.detected_year
                or new_content_key != channel.content_key
                or new_detected_audio != channel.detected_audio
                or new_detected_genre != channel.detected_genre
                or new_detected_genres != channel.detected_genres
                or new_restricted != bool(channel.detected_restricted)
            )
            if changed:
                channel.detected_prefix = prefix
                channel.detected_quality = quality
                channel.detected_region = region
                channel.detected_title  = new_title
                channel.detected_year   = new_year
                channel.content_key     = new_content_key
                channel.detected_audio  = new_detected_audio
                channel.detected_genre  = new_detected_genre
                channel.detected_genres = new_detected_genres
                channel.detected_restricted = new_restricted
                channel.updated_at = datetime.now()
                batch_updated += 1

        self.session.commit()
        return batch_updated, len(channels)

    def _propagate_region_from_siblings(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Fill empty ``detected_region`` from a same-``content_key`` sibling.

        Retries the whole pass on a transient lock via the shared
        :meth:`_retry_on_lock` helper — see :meth:`_propagate_region_from_siblings_impl`
        for the actual logic and docstring.
        """
        return self._retry_on_lock(
            "update_detected_prefixes: region-sibling propagation",
            self._propagate_region_from_siblings_impl,
            provider_id,
        )

    def _propagate_region_from_siblings_impl(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Fill empty ``detected_region`` from a same-``content_key`` sibling.

        Final fill-empty-only pass of :meth:`update_detected_prefixes`.  A row
        whose name AND provider-category yielded no region inherits one from a
        sibling sharing its (non-NULL) ``content_key`` — the cross-source content
        identity (DR-0009).  Synthetic ``id:``-keyed singletons (NULL
        ``content_key``) have no siblings and are skipped.

        Winner selection when siblings disagree: the **most common** region code
        across all siblings; ties broken by the **alphabetically-first** code — a
        stable, deterministic order independent of row/scan order.

        Never overwrites a row that already has a region.  Sibling regions are
        read across **all** providers (content identity is source-independent);
        when *provider_id* is given, only that provider's rows are filled.

        Idempotent / retry-safe: only fills rows that are still empty, so a
        retried run after a partial commit simply re-scans and re-applies
        whatever the last successful commit didn't cover — see
        :meth:`_propagate_region_from_siblings` (the public entry point, which
        wraps this in the shared lock-retry helper).

        Args:
            provider_id: Restrict the rows that get filled to this provider, or
                None to fill across the whole library.

        Returns:
            Number of rows that had ``detected_region`` written.
        """
        from collections import Counter, defaultdict

        _BATCH = 2000

        # NB: do NOT expunge_all() here — update_detected_prefixes intentionally
        # leaves the last batch's ORM objects attached so callers can refresh/read
        # them afterward.  The queries below use column projections and the fills
        # use bulk UPDATEs, neither of which needs a clean identity map.

        # 1. Winner map: content_key -> region. Built from a GROUP BY (one row per
        #    distinct key+region) so memory is bounded by distinct keyed regions.
        counters: dict[str, Counter] = defaultdict(Counter)
        grouped = (
            self.session.query(
                ChannelDB.content_key,
                ChannelDB.detected_region,
                func.count().label("n"),
            )
            .filter(ChannelDB.content_key.isnot(None))
            .filter(ChannelDB.detected_region.isnot(None))
            .filter(ChannelDB.detected_region != "")
            .group_by(ChannelDB.content_key, ChannelDB.detected_region)
            .all()
        )
        for key, region, n in grouped:
            counters[key][region] += n

        winner: dict[str, str] = {}
        for key, counter in counters.items():
            # (-count, region): most common first, alphabetical tie-break.
            winner[key] = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

        if not winner:
            return 0

        # 2. Fill empty rows whose content_key has a winner (scoped if asked).
        empty_q = (
            self.session.query(ChannelDB.id, ChannelDB.content_key)
            .filter(ChannelDB.content_key.isnot(None))
            .filter(
                or_(
                    ChannelDB.detected_region.is_(None),
                    ChannelDB.detected_region == "",
                )
            )
        )
        if provider_id:
            empty_q = empty_q.filter(ChannelDB.provider_id == provider_id)
        empty_rows = empty_q.all()

        filled = 0
        for ch_id, key in empty_rows:
            region = winner.get(key)
            if not region:
                continue
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == ch_id)
                .values(detected_region=region, updated_at=datetime.now())
            )
            filled += 1
            if filled % _BATCH == 0:
                self.session.commit()

        self.session.commit()
        return filled

    def propagate_tmdb_from_title_siblings(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Adopt a confident same-title sibling's ``detected_tmdb_id`` onto idless rows.

        Retries the whole pass on a transient lock via the shared
        :meth:`_retry_on_lock` helper — this is the site that crashed
        uncovered on 2026-08-01 (owner log: ``database is locked`` inside this
        method's bulk ``UPDATE``, which #367's batch-only retry didn't reach).
        See :meth:`_propagate_tmdb_from_title_siblings_impl` for the actual
        logic and full docstring.
        """
        return self._retry_on_lock(
            "propagate_tmdb_from_title_siblings",
            self._propagate_tmdb_from_title_siblings_impl,
            provider_id,
        )

    def _propagate_tmdb_from_title_siblings_impl(
        self, provider_id: Optional[str] = None
    ) -> int:
        """Adopt a confident same-title sibling's ``detected_tmdb_id`` onto idless rows.

        Free (no-network) Phase-2 pass.  For each idless VOD row
        (``detected_tmdb_id IS NULL``), if a sibling shares the **same normalized
        ``detected_title``** (via :func:`content_dedup.normalize_title`) **and the
        same ``media_type``** and is **year-compatible**, adopt that sibling's id:
        store ``detected_tmdb_id``, recompute ``content_key`` through the
        :func:`~metatv.core.content_identity.content_key_for` chokepoint (tmdb-first
        → ``"tmdb:{id}|{media_type}"``), and mark ``tmdb_enrich_state='propagated'``.

        Year-compat / remake guard: a sibling is *year-compatible* when either row
        lacks a ``detected_year`` or their start years differ by ≤ 1.  Among the
        year-compatible id-bearing siblings a row adopts an id **only when exactly
        one distinct id remains** — multiple distinct ids (a genuine remake split)
        are ambiguous and skipped (never guess between remakes).

        Sibling ids are read across **all** providers (content identity is
        source-independent); when *provider_id* is given only that provider's idless
        rows are filled (the ingestion-hook path — new content self-heals against the
        whole library).  Only the generated ``detected_tmdb_id`` / ``content_key`` /
        ``tmdb_enrich_state`` columns are written — user tags/ratings/favorites are
        never touched (mirror-not-cage).  Shared by the one-time migration
        (``tmdb_sibling_propagation``) and ``update_detected_prefixes`` so both paths
        use one definition.

        Idempotent / retry-safe: only touches rows still idless
        (``detected_tmdb_id IS NULL``), so a retried run after a partial commit
        (see :meth:`propagate_tmdb_from_title_siblings`, the public entry point
        wrapping this in the shared lock-retry helper) simply re-scans and
        adopts only what the last successful commit didn't cover.

        Args:
            provider_id: Restrict the idless rows filled to this provider, or None
                to fill across the whole library (the migration path).

        Returns:
            Number of idless rows that adopted a sibling id.
        """
        from metatv.core.content_dedup import normalize_title

        _BATCH = 2000
        _VOD = ("movie", "series")

        # 1. Winner map from id-bearing VOD rows: (norm_title, media_type) ->
        #    {tmdb_id: start_year_or_None}.  Dedup collapses variants; >1 distinct
        #    id in a group flags a remake split resolved per-row (year-compat) below.
        groups: Dict[Tuple[str, str], Dict[str, Optional[int]]] = {}
        id_rows = (
            self.session.query(
                ChannelDB.detected_title,
                ChannelDB.media_type,
                ChannelDB.detected_year,
                ChannelDB.detected_tmdb_id,
            )
            .filter(ChannelDB.detected_tmdb_id.isnot(None))
            .filter(ChannelDB.media_type.in_(_VOD))
            .yield_per(_BATCH)
        )
        for det_title, mt, det_year, det_tmdb in id_rows:
            tmdb = valid_tmdb_id(det_tmdb)
            if not tmdb:
                continue
            norm = normalize_title(det_title or "")
            if not norm:
                continue
            year = _start_year_int(det_year)
            bucket = groups.setdefault((norm, mt or ""), {})
            # Keep the first year seen for an id, upgrading None → a real year when
            # a later row for the same id carries one (helps the compat check).
            if tmdb not in bucket or (bucket[tmdb] is None and year is not None):
                bucket[tmdb] = year

        if not groups:
            return 0

        # 2. Scan idless rows (scoped) and adopt where a single year-compatible id wins.
        idless_q = (
            self.session.query(
                ChannelDB.id,
                ChannelDB.detected_title,
                ChannelDB.media_type,
                ChannelDB.detected_year,
            )
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(_VOD))
        )
        if provider_id:
            idless_q = idless_q.filter(ChannelDB.provider_id == provider_id)

        adopted = 0
        pending = 0
        for cid, det_title, mt, det_year in idless_q.yield_per(_BATCH):
            norm = normalize_title(det_title or "")
            if not norm:
                continue
            bucket = groups.get((norm, mt or ""))
            if not bucket:
                continue
            my_year = _start_year_int(det_year)
            compat_ids = {
                tid
                for tid, syear in bucket.items()
                if my_year is None or syear is None or abs(my_year - syear) <= 1
            }
            if len(compat_ids) != 1:
                continue  # no candidate, or ambiguous remake split → don't guess
            tmdb = next(iter(compat_ids))
            proxy = _TmdbKeyProxy(detected_tmdb_id=tmdb, media_type=mt or "", id=cid)
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == cid)
                .values(
                    detected_tmdb_id=tmdb,
                    content_key=content_key_for(proxy),
                    tmdb_enrich_state="propagated",
                )
            )
            adopted += 1
            pending += 1
            if pending >= _BATCH:
                self.session.commit()
                pending = 0

        self.session.commit()
        if adopted:
            logger.info(
                "tmdb_sibling_propagation: adopted {} idless row(s) from title siblings",
                adopted,
            )
        return adopted

    def backfill_tmdb_ids(
        self,
        progress_cb=None,
        is_cancelled=None,
    ) -> int:
        """Populate ``detected_tmdb_id`` from each row's ``raw_data["tmdb"]``.

        Content-identity Slice 3.  Existing rows were ingested before the raw
        provider tmdb id was captured, so their ``detected_tmdb_id`` is NULL.
        This one-time pass reads the ``raw_data`` blob, validates the id via the
        shared :func:`~metatv.core.content_identity.valid_tmdb_id`, and stores it.

        **Ordering:** must run BEFORE the content_key recompute (version 4) so
        that recompute reads a populated ``detected_tmdb_id`` and can emit the
        tmdb-first key.  See the registration order in ``gui/main_window.py``.

        Only ``detected_tmdb_id`` (a generated field derived purely from the
        provider blob) is written — user tags/ratings/favorites are never
        touched (mirror-not-cage).  Rows with no real tmdb id keep NULL.

        Processes rows in 2000-row batches, loading ``raw_data`` for at most one
        batch at a time (then commit + ``expunge_all``) to stay memory-safe on
        large tables.  Idempotent: only rows whose ``detected_tmdb_id`` is still
        NULL are scanned, so an interrupted run resumes cheaply.

        Args:
            progress_cb: Optional ``(done: int, total: int) -> None`` called
                after each batch commit.
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch.  Early exit leaves committed batches durable; the task
                version is not bumped so it restarts next launch.

        Returns:
            Number of rows that had a non-NULL ``detected_tmdb_id`` written.
        """
        _BATCH = 2000

        # Only rows that don't yet have an id — NULL covers both "never scanned"
        # and "scanned, no id".  We narrow to VOD media types because live
        # channels never carry a tmdb id; this skips the bulk of most libraries.
        q = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
        )
        all_ids = [row[0] for row in q.all()]
        total = len(all_ids)

        if total == 0:
            logger.debug("backfill_tmdb_ids: nothing to do (no NULL-id VOD rows)")
            return 0

        logger.info("backfill_tmdb_ids: scanning {} VOD rows for provider tmdb ids", total)
        filled = 0

        for batch_start in range(0, total, _BATCH):
            if is_cancelled is not None and is_cancelled():
                logger.info("backfill_tmdb_ids: cancelled at {}/{}", batch_start, total)
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            # raw_data IS needed here (that's where tmdb lives), so load it for
            # this batch only, then expunge below.
            rows = (
                self.session.query(ChannelDB.id, ChannelDB.raw_data)
                .filter(ChannelDB.id.in_(chunk_ids))
                .all()
            )

            for (ch_id, raw) in rows:
                tmdb = valid_tmdb_id((raw or {}).get("tmdb")) if raw else None
                if tmdb is None:
                    continue  # leave NULL — no real id shipped for this row
                self.session.execute(
                    update(ChannelDB)
                    .where(ChannelDB.id == ch_id)
                    .values(detected_tmdb_id=tmdb)
                )
                filled += 1

            self.session.commit()
            self.session.expunge_all()

            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        logger.info("backfill_tmdb_ids: wrote {} tmdb ids across {} scanned rows", filled, total)
        return filled

    def backfill_content_keys(
        self,
        progress_cb=None,
        is_cancelled=None,
        recompute_all: bool = False,
    ) -> int:
        """Compute and store ``content_key`` for channel rows.

        Reads only ``detected_title``, ``media_type``, ``detected_year``, and
        ``id`` — no raw name re-parsing.  Processes rows in 2000-row batches
        with a commit + expunge_all between batches to stay memory-safe on
        million-row tables.

        Args:
            progress_cb: Optional ``(done: int, total: int) -> None`` called
                after each batch commit.
            is_cancelled: Optional ``() -> bool`` checked at the top of each
                batch.  Early exit leaves all previously committed batches
                durable; the task version is not bumped so it restarts next
                launch.
            recompute_all: When ``False`` (default), only rows with a NULL
                ``content_key`` are processed (the initial-population path,
                idempotent: a no-op once all rows are filled).  When ``True``,
                EVERY row is recomputed — used when the key formula changes so
                that existing non-NULL keys are updated to the new formula.

        Returns:
            Number of rows that had their ``content_key`` written.
        """
        _BATCH = 2000

        # Fetch row ids to process: NULL-only by default, all rows on formula change.
        q = self.session.query(ChannelDB.id)
        if not recompute_all:
            q = q.filter(ChannelDB.content_key.is_(None))
        all_ids = [row[0] for row in q.all()]
        total = len(all_ids)

        if total == 0:
            logger.debug(
                "backfill_content_keys: nothing to do "
                "(recompute_all={}, all rows already keyed)", recompute_all
            )
            return 0

        logger.info(
            "backfill_content_keys: processing {} rows (recompute_all={})",
            total, recompute_all,
        )
        filled = 0

        for batch_start in range(0, total, _BATCH):
            if is_cancelled is not None and is_cancelled():
                logger.info(
                    "backfill_content_keys: cancelled at {}/{}", batch_start, total
                )
                break

            chunk_ids = all_ids[batch_start : batch_start + _BATCH]
            # Project only the columns we need to stay memory-safe.  detected_tmdb_id
            # is included so content_key_for can pick the tmdb-first key on recompute
            # (else it would fall back to the title/year key and never key on tmdb).
            rows = (
                self.session.query(
                    ChannelDB.id,
                    ChannelDB.detected_title,
                    ChannelDB.media_type,
                    ChannelDB.detected_year,
                    ChannelDB.detected_tmdb_id,
                )
                .filter(ChannelDB.id.in_(chunk_ids))
                .all()
            )

            for (ch_id, det_title, media_type, det_year, det_tmdb_id) in rows:
                class _Proxy:
                    __slots__ = (
                        "detected_title", "media_type", "detected_year",
                        "detected_tmdb_id", "id",
                    )
                    def __init__(self, t, m, y, tmdb, i):
                        self.detected_title = t
                        self.media_type = m
                        self.detected_year = y
                        self.detected_tmdb_id = tmdb
                        self.id = i
                key = content_key_for(_Proxy(det_title, media_type, det_year, det_tmdb_id, ch_id))
                # Update via bulk UPDATE to avoid loading the full ORM object (raw_data JSON blob).
                self.session.execute(
                    update(ChannelDB)
                    .where(ChannelDB.id == ch_id)
                    .values(content_key=key)
                )
                filled += 1

            self.session.commit()
            self.session.expunge_all()

            if progress_cb is not None:
                progress_cb(min(batch_start + _BATCH, total), total)

        logger.info(f"backfill_content_keys: filled {filled} of {total} rows")
        return filled

    # ── Provider-native tmdb enrichment (Phase 2) ─────────────────────────────

    def _tmdb_candidate_filter(self, query, excluded_provider_ids, provider_id):
        """Apply the shared idless-VOD-candidate predicate to *query*.

        A candidate is a movie/series row that is visible (``is_hidden`` False),
        belongs to a non-excluded provider, carries **no** ``detected_tmdb_id``
        (its list row shipped no id), and has **not** been attempted yet
        (``tmdb_enrich_state IS NULL``) — the persistent marker that makes the
        pass resumable and hits each row at most once.  Single definition so the
        candidate query and the has-candidates probe never drift.
        """
        query = (
            query
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.tmdb_enrich_state.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            query = query.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        if provider_id is not None:
            query = query.filter(ChannelDB.provider_id == provider_id)
        return query

    def provider_ids_with_tmdb_candidates(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[str]:
        """Return the distinct providers that still have idless VOD rows to attempt.

        Lets the caller split its per-session cap fairly across sources rather than
        exhausting the largest provider first (which would starve the others for
        hundreds of launches).

        Args:
            excluded_provider_ids: Hidden providers — never enriched.

        Returns:
            Distinct ``provider_id`` values with at least one candidate.
        """
        q = self._tmdb_candidate_filter(
            self.session.query(ChannelDB.provider_id).distinct(),
            excluded_provider_ids,
            provider_id=None,
        )
        return [row[0] for row in q.all()]

    def select_tmdb_enrichment_candidates(
        self,
        limit: int,
        excluded_provider_ids: Optional[Set[str]] = None,
        provider_id: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Return idless VOD rows that still need a provider-detail tmdb lookup.

        See :meth:`_tmdb_candidate_filter` for the candidate predicate.  Returns
        plain dicts (safe to cross the worker → write-session boundary — no ORM
        objects escape).

        Args:
            limit: Hard cap on rows returned.
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.
            provider_id: When given, restrict to this one provider (used to draw a
                fair per-provider slice of the session cap).

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts.
        """
        q = self._tmdb_candidate_filter(
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            ),
            excluded_provider_ids,
            provider_id,
        )
        q = q.order_by(ChannelDB.provider_id).limit(limit)

        return [
            {
                "id": cid,
                "provider_id": pid,
                "source_id": sid,
                "media_type": mt,
            }
            for (cid, pid, sid, mt) in q.all()
        ]

    def select_tmdb_candidates_by_ids(
        self,
        channel_ids,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, str]]:
        """Narrow *channel_ids* to the rows that still need a provider-detail lookup.

        The lazy enrichment (``TmdbEnrichmentManager.enqueue``) is fed **bare ids**
        from the result surfaces (Discover / Recipe / channel list / search / details)
        — none of whose DTOs carry ``detected_tmdb_id`` / ``tmdb_enrich_state``.  This
        applies the shared candidate predicate (:meth:`_tmdb_candidate_filter`:
        idless, unattempted, visible, non-excluded VOD) to the queued ids off the UI
        thread, so a row is fetched at most once and only when it really needs it.

        Args:
            channel_ids: The ids a surface just loaded (a bounded drain batch).
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts for the
            subset that are still candidates (plain dicts — no ORM objects escape).
        """
        ids = list(channel_ids)
        if not ids:
            return []
        q = self._tmdb_candidate_filter(
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            ),
            excluded_provider_ids,
            provider_id=None,
        ).filter(ChannelDB.id.in_(ids))
        return [
            {"id": cid, "provider_id": pid, "source_id": sid, "media_type": mt}
            for (cid, pid, sid, mt) in q.all()
        ]

    def tmdb_enrichment_funnel(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> TmdbFunnelDTO:
        """Return the enrichment funnel across visible VOD rows (analytics).

        Buckets every movie/series row on a visible, non-excluded provider by how
        its tmdb id was resolved (provenance in ``tmdb_enrich_state``), so the
        "Missing TMDb data" view can present provider-native coverage vs. the
        residual gap that only the external TMDb API could close.  One GROUP BY —
        no per-row scan.

        Args:
            excluded_provider_ids: Hidden providers (inactive ∪ expired) to exclude.

        Returns:
            A :class:`TmdbFunnelDTO` (safe to cross the worker boundary).
        """
        q = (
            self.session.query(
                ChannelDB.detected_tmdb_id.isnot(None),
                ChannelDB.tmdb_enrich_state,
                func.count(),
            )
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            q = q.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        q = q.group_by(
            ChannelDB.detected_tmdb_id.isnot(None), ChannelDB.tmdb_enrich_state
        )

        from_list = propagated = fetched = unattempted = residual = 0
        for has_id, state, n in q.all():
            if has_id:
                if state == "propagated":
                    propagated += n
                elif state == "fetched":
                    fetched += n
                else:
                    # 'list' / NULL / anything else with an id → harvested-from-list.
                    from_list += n
            else:
                if state == "none":
                    residual += n
                else:
                    unattempted += n  # NULL marker → still a lazy-fetch candidate

        total = from_list + propagated + fetched + unattempted + residual
        return TmdbFunnelDTO(
            total_vod=total,
            from_list=from_list,
            propagated=propagated,
            fetched=fetched,
            unattempted=unattempted,
            residual=residual,
        )

    def missing_tmdb_by_source(
        self,
        excluded_provider_ids: Optional[Set[str]] = None,
        sample_per_source: int = 8,
        max_sources: int = 50,
    ) -> List[MissingTmdbSourceDTO]:
        """Return idless-VOD counts + a sample per source for the diagnostic view.

        A row is *idless* when ``detected_tmdb_id IS NULL`` (visible VOD only); of
        those, the ``'none'``-marked subset is the residual only the TMDb API could
        resolve.  The view feeds each returned row's ``channel_id`` back through the
        enqueue chokepoint, so opening it drives enrichment (the list shrinks as ids
        land).  Returns frozen DTOs — no ORM objects escape.

        Args:
            excluded_provider_ids: Hidden providers to exclude.
            sample_per_source: Max example rows per source (for the drill-down).
            max_sources: Cap on the number of sources returned (largest gaps first).

        Returns:
            List of :class:`MissingTmdbSourceDTO`, sorted by ``missing_count`` desc.
        """
        from sqlalchemy import case

        base = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.detected_tmdb_id.is_(None))
            .filter(ChannelDB.media_type.in_(("movie", "series")))
            .filter(ChannelDB.is_hidden.is_(False))
        )
        if excluded_provider_ids:
            base = base.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))

        counts = (
            base.with_entities(
                ChannelDB.provider_id,
                func.count(),
                func.sum(case((ChannelDB.tmdb_enrich_state == "none", 1), else_=0)),
            )
            .group_by(ChannelDB.provider_id)
            .order_by(func.count().desc())
            .limit(max_sources)
            .all()
        )
        if not counts:
            return []

        # Provider names (single lookup — the DTO carries the human-readable name).
        names = {p.id: p.name for p in self.session.query(ProviderDB.id, ProviderDB.name).all()}

        out: List[MissingTmdbSourceDTO] = []
        for pid, missing_count, residual_count in counts:
            sample_rows = (
                base.with_entities(
                    ChannelDB.id,
                    ChannelDB.name,
                    ChannelDB.detected_title,
                    ChannelDB.detected_year,
                    ChannelDB.media_type,
                )
                .filter(ChannelDB.provider_id == pid)
                .order_by(ChannelDB.name)
                .limit(sample_per_source)
                .all()
            )
            sample = [
                MissingTmdbRowDTO(
                    channel_id=cid,
                    name=name,
                    detected_title=dt,
                    detected_year=dy,
                    media_type=mt,
                    tmdb_addressable=_looks_tmdb_addressable(dt, mt, dy),
                )
                for (cid, name, dt, mt, dy) in (
                    (r[0], r[1], r[2], r[4], r[3]) for r in sample_rows
                )
            ]
            out.append(
                MissingTmdbSourceDTO(
                    provider_id=pid,
                    provider_name=names.get(pid, pid),
                    missing_count=int(missing_count or 0),
                    residual_count=int(residual_count or 0),
                    sample=sample,
                )
            )
        return out

    def apply_tmdb_enrichment(
        self,
        hits: Dict[str, str],
        misses,
    ) -> int:
        """Persist a provider-native enrichment batch and report new collapses.

        For each **hit** (``channel_id → tmdb_id`` discovered via the detail
        endpoint): store ``detected_tmdb_id``, recompute ``content_key`` through
        the SAME chokepoint the migration uses
        (:func:`~metatv.core.content_identity.content_key_for`, which is
        tmdb-first, so the recomputed key is ``"tmdb:{id}|{media_type}"``), and
        mark ``tmdb_enrich_state='fetched'``.  For each **miss** (attempted but the
        detail endpoint carried no id): mark ``tmdb_enrich_state='none'`` so the
        row is never re-fetched (until a content refresh resets it) — the residual
        ``NULL id + 'none'`` is the only-TMDb-API-addressable gap the analytics
        surface reports.

        Only these three generated fields are written — user tags / ratings /
        favorites are never touched (mirror-not-cage).

        Args:
            hits: ``{channel_id: tmdb_id}`` — validated digit-string ids.
            misses: Iterable of channel ids that were attempted but yielded no id.

        Returns:
            The number of *hit* rows whose recomputed ``content_key`` now appears
            on ≥ 2 rows — i.e. rows that landed in a shared collapse group this
            batch.  A positive count is the host's cue to refresh the views.
        """
        miss_ids = list(misses)
        if miss_ids:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(miss_ids))
                .values(tmdb_enrich_state="none")
            )

        if not hits:
            self.session.commit()
            return 0

        hit_ids = list(hits.keys())
        # media_type is needed to namespace the tmdb key (movie vs series live in
        # separate TMDb id spaces) — project just that column, no raw_data blob.
        mt_by_id = {
            cid: mt
            for (cid, mt) in self.session.query(ChannelDB.id, ChannelDB.media_type)
            .filter(ChannelDB.id.in_(hit_ids))
            .all()
        }

        new_keys: Dict[str, str] = {}
        for cid, tmdb in hits.items():
            media_type = mt_by_id.get(cid) or ""
            # Read a proxy through content_key_for so identity has ONE definition;
            # a valid tmdb short-circuits to "tmdb:{id}|{media_type}".
            proxy = _TmdbKeyProxy(detected_tmdb_id=tmdb, media_type=media_type, id=cid)
            key = content_key_for(proxy)
            new_keys[cid] = key
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id == cid)
                .values(
                    detected_tmdb_id=tmdb,
                    content_key=key,
                    tmdb_enrich_state="fetched",
                )
            )

        self.session.commit()

        # New collapses: of the keys we just wrote, how many enriched rows now
        # share a key with at least one other row (a real fold, not a lone id).
        distinct_keys = set(new_keys.values())
        key_counts = dict(
            self.session.query(ChannelDB.content_key, func.count())
            .filter(ChannelDB.content_key.in_(distinct_keys))
            .group_by(ChannelDB.content_key)
            .all()
        )
        return sum(1 for key in new_keys.values() if key_counts.get(key, 0) >= 2)

    def select_genre_backfill_candidates(
        self,
        limit: int,
        excluded_provider_ids: Optional[Set[str]] = None,
    ) -> List[Dict[str, str]]:
        """Return MOVIE rows whose linked metadata row has **empty genres**.

        The list ``raw_data`` for movies is sparse (no genre), so a movie that has
        already been given a MetadataDB row (viewed at least once) still shows empty
        ``genres`` — which makes it invisible to the genre-driven recommendation
        scorer.  This selects those movies so the enrichment sweep can fetch their
        ``get_vod_info`` detail blob and harvest the real genres.

        Candidate predicate: ``media_type == 'movie'``, has a linked ``MetadataDB``
        row whose ``genres`` is NULL or ``[]``, is visible, on a non-excluded
        provider, and has **not** been attempted (``genre_enrich_state IS NULL``) —
        the persistent marker that makes the pass resumable and hits each row once.

        Args:
            limit: Hard cap on rows returned (a bounded drain batch).
            excluded_provider_ids: Hidden providers (inactive ∪ expired) from
                ``ProviderRepository.get_hidden_provider_ids()`` — never enriched.

        Returns:
            List of ``{"id", "provider_id", "source_id", "media_type"}`` dicts (plain
            dicts — no ORM objects escape the session).
        """
        # ``MetadataDB.genres == []`` binds through JSONEncoded to the stored TEXT
        # '[]' (the empty-list form), matching how empty genres are persisted.
        q = (
            self.session.query(
                ChannelDB.id,
                ChannelDB.provider_id,
                ChannelDB.source_id,
                ChannelDB.media_type,
            )
            .join(MetadataDB, ChannelDB.metadata_id == MetadataDB.id)
            .filter(ChannelDB.media_type == "movie")
            .filter(ChannelDB.is_hidden.is_(False))
            .filter(ChannelDB.genre_enrich_state.is_(None))
            .filter(or_(MetadataDB.genres.is_(None), MetadataDB.genres == []))
        )
        if excluded_provider_ids:
            q = q.filter(ChannelDB.provider_id.notin_(excluded_provider_ids))
        q = q.order_by(ChannelDB.provider_id).limit(limit)
        return [
            {"id": cid, "provider_id": pid, "source_id": sid, "media_type": mt}
            for (cid, pid, sid, mt) in q.all()
        ]

    def apply_metadata_harvest(self, harvest: Dict[str, dict]) -> int:
        """Fill EMPTY metadata fields for fetched titles from their detail blob.

        ``harvest`` maps ``channel_id → {genres, plot, cast, director}`` parsed from
        the channel's ``get_vod_info`` / ``get_series_info`` response (see
        :func:`metatv.metadata_providers.raw_parse.harvest_detail_metadata`).  For
        each channel that HAS a linked ``MetadataDB`` row, only fields that are
        currently empty (generated data) are filled — a populated field (a better
        provider's value, or a user edit) is never overwritten (mirror-not-cage).

        For **movie** rows it also stamps the ``genre_enrich_state`` fetch-once
        marker: ``'fetched'`` when the detail blob carried a genre, ``'none'`` when
        it did not — so the one-time genre backfill never re-fetches the same title.
        Rows that errored during fetch are simply absent from *harvest*, so they are
        left unmarked and retried on a later pass (defer-on-error).

        Args:
            harvest: ``{channel_id: {genres, plot, cast, director}}``.

        Returns:
            The number of metadata rows whose ``genres`` were populated this call.
        """
        cids = list(harvest.keys())
        if not cids:
            return 0

        # channel_id → (metadata_id, media_type) for the fetched rows.
        chan_rows = (
            self.session.query(
                ChannelDB.id, ChannelDB.metadata_id, ChannelDB.media_type
            )
            .filter(ChannelDB.id.in_(cids))
            .all()
        )
        meta_id_by_cid = {cid: mid for (cid, mid, _mt) in chan_rows if mid}
        media_by_cid = {cid: mt for (cid, _mid, mt) in chan_rows}

        meta_ids = list(set(meta_id_by_cid.values()))
        meta_by_id: Dict[str, MetadataDB] = {}
        if meta_ids:
            for meta in (
                self.session.query(MetadataDB)
                .filter(MetadataDB.id.in_(meta_ids))
                .all()
            ):
                meta_by_id[meta.id] = meta

        filled = 0
        movie_fetched: List[str] = []  # got a genre → mark 'fetched'
        movie_none: List[str] = []     # attempted, no genre → mark 'none'

        for cid, h in harvest.items():
            has_genre = bool(h.get("genres"))
            if media_by_cid.get(cid) == "movie":
                (movie_fetched if has_genre else movie_none).append(cid)

            meta = meta_by_id.get(meta_id_by_cid.get(cid))
            if meta is None:
                continue  # no metadata row to fill (not a scoring candidate anyway)

            if not meta.genres and h.get("genres"):
                meta.genres = h["genres"]
                filled += 1
            if not meta.plot and h.get("plot"):
                meta.plot = h["plot"]
            if not meta.cast and h.get("cast"):
                meta.cast = h["cast"]
            if not meta.director and h.get("director"):
                meta.director = h["director"]

        if movie_fetched:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(movie_fetched))
                .values(genre_enrich_state="fetched")
            )
        if movie_none:
            self.session.execute(
                update(ChannelDB)
                .where(ChannelDB.id.in_(movie_none))
                .values(genre_enrich_state="none")
            )
        self.session.commit()
        return filled

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
        - Collapses same-production variants by ``content_key or normalized_title``,
          keeping the best-scored variant per group
          (``preference_engine.version_score`` — requires *config*; without it the
          first variant encountered per group wins).
        - Drops any candidate whose ``build_dedup_key`` equals the origin's current
          key (its own other-source variants belong in "Other Versions", not here).

        Visibility — the absolute gate (DR-0007 active-source scoping):
        - ``is_hidden == False`` (per-channel hide), **and**
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
        from metatv.core.preference_engine import version_score as _version_score

        channel = self.session.get(ChannelDB, channel_id)
        if not channel:
            return []

        norm = normalize_title(channel.name, channel.detected_prefix)
        words = [w for w in norm.split() if len(w) >= 4]
        if not words:
            return []

        excluded = list(excluded_provider_ids or [])
        q = (
            self.session.query(ChannelDB)
            .filter(
                ChannelDB.media_type == channel.media_type,
                ChannelDB.id != channel_id,
                ChannelDB.is_hidden == False,  # noqa: E712 — per-channel hide gate
                _channel_text_search_predicate(words[0]),
            )
        )
        if excluded:
            # Absolute gate: inactive/expired/orphaned sources never surface here.
            q = q.filter(~ChannelDB.provider_id.in_(excluded))
        # Global Filter (Exclusions): the same language/category blacklist Discover
        # applies, so a globally-excluded language never leaks into any of the three
        # Similar surfaces.  The excluded set comes from the shared filter_utils
        # resolvers (single source of truth for the DATA); the SQL is applied with the
        # canonical _apply_prefix_filter predicate.  config=None or paused → no-op.
        if config is not None and not getattr(config, "global_filter_paused", False):
            from metatv.core.filter_utils import (
                get_active_category_filter, get_excluded_prefixes,
            )
            from metatv.core.discovery_engine import _apply_prefix_filter

            cat_excluded, include_uncategorized = get_active_category_filter(config)
            excluded_prefixes = set(cat_excluded or []) | get_excluded_prefixes(config)
            q = _apply_prefix_filter(
                q, list(excluded_prefixes) or None, include_uncategorized
            )
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
        best_per_group: "dict[str, tuple[ChannelDB, int]]" = {}
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
            group_key = (ch.content_key or None) or ch_norm
            score = _version_score(ch, config) if config is not None else 0
            existing = best_per_group.get(group_key)
            if existing is None or score > existing[1]:
                best_per_group[group_key] = (ch, score)

        return [ch for ch, _ in list(best_per_group.values())[:limit]]

    # ── User category methods ──────────────────────────────────────────────────

    def get_all_user_categories(self) -> list[dict]:
        """Return all user-defined categories with channel counts and mood.

        Returns list of dicts sorted by channel count descending:
            [{"name": str, "count": int, "mood": str | None}, ...]
        """
        rows = (
            self.session.query(
                ChannelDB.user_category,
                ChannelDB.category_mood,
                func.count().label("cnt"),
            )
            .filter(ChannelDB.user_category.isnot(None))
            .group_by(ChannelDB.user_category, ChannelDB.category_mood)
            .order_by(func.count().desc())
            .all()
        )
        seen: dict[str, dict] = {}
        for name, mood, cnt in rows:
            if name not in seen:
                seen[name] = {"name": name, "count": cnt, "mood": mood}
            else:
                seen[name]["count"] += cnt
        return sorted(seen.values(), key=lambda x: -x["count"])

    def assign_user_category(
        self,
        channel_ids: list[str],
        category: str,
        mood: str | None = None,
    ) -> int:
        """Assign user_category (and optional mood) to a list of channels.

        Returns the number of channels updated.
        """
        if not channel_ids:
            return 0
        updated = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(channel_ids))
            .update(
                {"user_category": category, "category_mood": mood,
                 "updated_at": datetime.now()},
                synchronize_session="fetch",
            )
        )
        self.session.commit()
        logger.info(
            f"Assigned {updated} channels to user category {category!r} (mood={mood!r})"
        )
        return updated

    def remove_user_category(self, channel_ids: list[str]) -> int:
        """Clear user_category and category_mood from a list of channels."""
        if not channel_ids:
            return 0
        updated = (
            self.session.query(ChannelDB)
            .filter(ChannelDB.id.in_(channel_ids))
            .update(
                {"user_category": None, "category_mood": None,
                 "updated_at": datetime.now()},
                synchronize_session="fetch",
            )
        )
        self.session.commit()
        return updated

    def get_by_user_category(self, category: str) -> list[ChannelDB]:
        """Return all channels assigned to a user category, sorted by name."""
        return (
            self.session.query(ChannelDB)
            .filter(ChannelDB.user_category == category)
            .order_by(ChannelDB.name)
            .all()
        )

    def get_hidden_channels(
        self,
        excluded_user_categories: set[str] | None = None,
        search_query: str | None = None,
        provider_id=None,
        excluded_provider_ids: list[str] | None = None,
    ) -> list[ChannelDB]:
        """Return is_hidden=True channels and channels in excluded user categories."""
        if excluded_user_categories:
            q = self.session.query(ChannelDB).filter(
                or_(
                    ChannelDB.is_hidden == True,  # noqa: E712
                    ChannelDB.user_category.in_(excluded_user_categories),
                )
            )
        else:
            q = self.session.query(ChannelDB).filter(ChannelDB.is_hidden == True)  # noqa: E712

        if isinstance(provider_id, list):
            if provider_id:
                q = q.filter(ChannelDB.provider_id.in_(provider_id))
        elif provider_id:
            q = q.filter(ChannelDB.provider_id == provider_id)

        if excluded_provider_ids:
            q = q.filter(~ChannelDB.provider_id.in_(excluded_provider_ids))

        if search_query:
            q = q.filter(_channel_text_search_predicate(search_query))

        return q.order_by(ChannelDB.name).all()

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

    def _engaged_channel_predicate(self):
        """Return the SQL predicate for an *engaged* channel (kept on provider delete).

        A channel is engaged — and therefore preserved even when its provider is
        removed — when it is favorited, has been played (``last_played`` set or
        ``play_count > 0``), or is currently queued.  This is the single
        "flag engaged-unavailable, don't delete" gate reused by every doomed-set
        delete below so the exclusion can never drift between statements.
        """
        return or_(
            ChannelDB.is_favorite == True,           # noqa: E712
            ChannelDB.last_played.isnot(None),
            ChannelDB.play_count > 0,
            ChannelDB.id.in_(self.session.query(WatchQueueDB.channel_id)),
        )

    def prune_provider_content(
        self,
        provider_ids: list[str],
    ) -> dict[str, int]:
        """Delete non-engaged channels (and their dependents) for a set of providers.

        "Engaged" means the channel was favorited, played, or queued.  Engaged
        channels are KEPT even when their provider is removed — they remain
        accessible in History / Favorites / Watch Queue and are hidden from
        forward-looking views via ``get_hidden_provider_ids()``.

        Set-based, provider-scoped deletes (not id-batched):  every child delete
        targets ``... WHERE <fk> IN (SELECT id FROM channels WHERE provider_id IN
        (:pids) AND NOT <engaged>)`` and the channels themselves are removed with a
        single ``DELETE ... WHERE provider_id IN (:pids) AND NOT <engaged>`` — the
        doomed set is resolved by SQLite via the indexed ``provider_id`` instead of
        shipping every id to Python and issuing ~150 batches of ~7 ``IN(...)``
        deletes.  The channels row is deleted LAST so the correlated subquery still
        resolves the doomed set for the child deletes, and each step group commits
        once (a few large transactions, not ~150 per-batch commits) — collapsing the
        SQLite single-writer lock-contention points that turned a ~13s purge into a
        2-minute UI freeze.

        ``content_tags`` is pruned here too: it has no FK cascade (SQLite FKs are
        off), so before this fix a deleted channel's ``content_tags`` rows were
        orphaned forever.  Engaged channels' tags are spared by the same doomed-set
        subquery.

        Args:
            provider_ids: Provider IDs whose non-engaged content should be
                purged.  May be an empty list (returns zero counts immediately).

        Returns:
            Dict with counts: ``channels``, ``metadata``, ``content_tags``,
            ``epg_by_channel``, ``epg_by_provider``, ``seasons``, ``episodes``,
            ``ratings``, ``alerts``.
        """
        if not provider_ids:
            return {
                "channels": 0, "metadata": 0, "content_tags": 0,
                "epg_by_channel": 0, "epg_by_provider": 0, "seasons": 0,
                "episodes": 0, "ratings": 0, "alerts": 0,
            }

        counts: dict[str, int] = {
            "channels": 0, "metadata": 0, "content_tags": 0,
            "epg_by_channel": 0, "epg_by_provider": 0, "seasons": 0,
            "episodes": 0, "ratings": 0, "alerts": 0,
        }

        engaged = self._engaged_channel_predicate()

        # The doomed channel set as a reusable correlated subquery.  Because the
        # channels row is deleted LAST, this subquery resolves the same non-engaged
        # set for every child delete below.  ``provider_id`` is indexed, so the
        # planner never materialises the full id list.
        doomed_channel_ids = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.provider_id.in_(provider_ids))
            .filter(~engaged)
        )
        doomed_meta_ids = (
            self.session.query(ChannelDB.metadata_id)
            .filter(ChannelDB.provider_id.in_(provider_ids))
            .filter(~engaged)
            .filter(ChannelDB.metadata_id.isnot(None))
        )

        logger.info(
            f"prune_provider_content: pruning non-engaged channels from "
            f"{len(provider_ids)} provider(s) via set-based provider-scoped deletes"
        )

        # Step 2 — set-based deletes of channel-level dependents (child → parent).
        # content_tags first (no FK cascade — the leak this also fixes).
        counts["content_tags"] += (
            self.session.query(ContentTagDB)
            .filter(ContentTagDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["epg_by_channel"] += (
            self.session.query(EpgProgramDB)
            .filter(EpgProgramDB.channel_db_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["episodes"] += (
            self.session.query(EpisodeDB)
            .filter(EpisodeDB.series_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["seasons"] += (
            self.session.query(SeasonDB)
            .filter(SeasonDB.series_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["ratings"] += (
            self.session.query(UserRatingDB)
            .filter(UserRatingDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        counts["alerts"] += (
            self.session.query(AlertMatchDB)
            .filter(AlertMatchDB.channel_id.in_(doomed_channel_ids))
            .delete(synchronize_session=False)
        )
        # MetadataDB rows referenced by the doomed channels (subquery reads
        # channels.metadata_id — must run before the channels row is deleted).
        counts["metadata"] += (
            self.session.query(MetadataDB)
            .filter(MetadataDB.id.in_(doomed_meta_ids))
            .delete(synchronize_session=False)
        )
        # Finally, the channels themselves — deleted LAST so the correlated
        # doomed-set subquery above still resolved while the child deletes ran.
        counts["channels"] += (
            self.session.query(ChannelDB)
            .filter(ChannelDB.provider_id.in_(provider_ids))
            .filter(~engaged)
            .delete(synchronize_session=False)
        )
        self.session.commit()

        # Step 3 — feed-side EPG: programmes whose provider_id is one of the removed
        # providers (these are EPG feed entries, not channel matches).
        counts["epg_by_provider"] += (
            self.session.query(EpgProgramDB)
            .filter(EpgProgramDB.provider_id.in_(provider_ids))
            .delete(synchronize_session=False)
        )
        self.session.commit()

        # Step 4 — orphaned SeasonDB / EpisodeDB whose provider_id is in the removed
        # set but whose series channel is NOT one of the KEPT (engaged) channels.
        # After Step 2 the only ChannelDB rows still present for these providers are
        # the engaged (favorited/played/queued) series we deliberately preserve, so a
        # season/episode whose series_id still resolves to an existing channel belongs
        # to a kept series — leave it intact so per-episode resume/watched history
        # survives a provider delete (history is sacrosanct).  Only truly orphaned
        # catalog rows (series channel already gone) are pruned, and even those are
        # spared when the episode itself still carries user watch-state.
        kept_series_subq = (
            self.session.query(ChannelDB.id)
            .filter(ChannelDB.provider_id.in_(provider_ids))
        )
        counts["episodes"] += (
            self.session.query(EpisodeDB)
            .filter(EpisodeDB.provider_id.in_(provider_ids))
            .filter(~EpisodeDB.series_id.in_(kept_series_subq))
            # Floor: never delete an episode carrying user watch-state, even if its
            # series channel is already gone (pre-fix orphans).
            .filter(
                ~or_(
                    EpisodeDB.is_watched == True,       # noqa: E712
                    EpisodeDB.watch_completed == True,  # noqa: E712
                    EpisodeDB.watch_progress > 0,
                    EpisodeDB.last_played.isnot(None),
                    EpisodeDB.play_count > 0,
                )
            )
            .delete(synchronize_session=False)
        )
        counts["seasons"] += (
            self.session.query(SeasonDB)
            .filter(SeasonDB.provider_id.in_(provider_ids))
            .filter(~SeasonDB.series_id.in_(kept_series_subq))
            .delete(synchronize_session=False)
        )
        self.session.commit()

        logger.info(
            f"prune_provider_content complete: {counts['channels']} channels, "
            f"{counts['metadata']} metadata, {counts['content_tags']} content_tags, "
            f"{counts['epg_by_channel'] + counts['epg_by_provider']} EPG rows, "
            f"{counts['seasons']} seasons, {counts['episodes']} episodes pruned; "
            f"engaged channels preserved."
        )
        return counts

