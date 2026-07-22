"""Channel repository for data access"""

import re
from typing import Optional, List, Dict, Set, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import and_, func, or_, update
from loguru import logger

from metatv.core.database import (
    ChannelDB, MetadataDB, SeasonDB, EpisodeDB,
    EpgProgramDB, UserRatingDB, AlertMatchDB, WatchQueueDB,
)
from metatv.core.filter_utils import extract_prefix, categorize_prefix, normalize_genre, _GENRE_NORM
from metatv.core.channel_name_utils import (
    parse_channel_name, normalize_region_code, QUALITY_TOKENS,
    _COMPOUND_PREFIX_RE, _PAREN_PREFIX_RE, detect_ai_provenance,
    AI_VOICEOVER_VALUE,
)
from metatv.core.repositories.dtos import FavoriteDTO, LiveEventDTO
from metatv.core.repositories.channel_stats import _ChannelStatsMixin
from metatv.core.content_identity import content_key_for
from metatv.core.tag_decomposer import region_code_from_category


# _GENRE_NORM and normalize_genre now live in metatv.core.filter_utils (a dependency-free
# leaf) — single source of truth, re-imported above so existing `channel._GENRE_NORM` /
# `channel.normalize_genre` references keep working. See filter_utils for the table.


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
        )

        query = query.order_by(ChannelDB.name)

        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            return query.limit(limit).all()
        return query.all()

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

        # Exclude provider category-header rows (e.g. "##### BEIN SPORTS #####").
        # These are label-only separators injected by some providers — not playable
        # streams.  The SQL pattern "##%" matches any name starting with ≥2 '#'.
        query = query.filter(ChannelDB.name.notlike("##%"))

        # Exclude PPV/event placeholder rows (e.g.
        # "- NO EVENT STREAMING - | 8K EXCLUSIVE | DE: DYN PPV 13 ...").
        # These slots have no actual event scheduled — they are not playable.
        # The "NO EVENT STREAMING" substring is the universal provider marker.
        query = query.filter(ChannelDB.name.notlike("%NO EVENT STREAMING%"))

        if adult_mode != "all":
            force_ids = force_adult_provider_ids or []
            # A channel is "adult" if is_adult=True OR its provider is force_adult
            if force_ids:
                is_adult_expr = or_(
                    ChannelDB.is_adult == True,
                    ChannelDB.provider_id.in_(force_ids),
                )
            else:
                is_adult_expr = (ChannelDB.is_adult == True)

            if adult_mode == "hide":
                query = query.filter(~is_adult_expr)
            elif adult_mode == "only":
                query = query.filter(is_adult_expr)

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

        # SQL text search pushdown (case-insensitive LIKE on channel name)
        if search_query:
            query = query.filter(ChannelDB.name.ilike(f"%{search_query}%"))

        # Strict genre filter — from details-pane genre chip clicks. No passthrough:
        # only movies/series whose raw_data genre field contains the requested genre.
        if strict_genre_filter:
            from sqlalchemy import text as _text2
            query = query.filter(
                ChannelDB.media_type.in_(["movie", "series"]),
                _text2("json_extract(raw_data, '$.genre') LIKE :_strict_genre").bindparams(
                    _strict_genre=f"%{strict_genre_filter}%"
                ),
            )

        # Person filter — from details-pane cast/director/crew clicks.
        # Searches raw_data.cast (comma-separated string) and raw_data.director.
        # MetadataDB is not used because raw_data covers ~70k channels while only
        # ~763 channels have metadata_id set; most metadata comes from raw_data directly.
        if person_filter:
            from sqlalchemy import text as _text3
            query = query.filter(
                or_(
                    _text3(
                        "json_extract(raw_data, '$.cast') LIKE :_person_cast"
                    ).bindparams(_person_cast=f"%{person_filter}%"),
                    _text3(
                        "json_extract(raw_data, '$.director') LIKE :_person_dir"
                    ).bindparams(_person_dir=f"%{person_filter}%"),
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
            ChannelDB.name.ilike(f"%{query}%"),
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
            channels = self.session.query(ChannelDB).filter(
                ChannelDB.id.in_(chunk_ids)
            ).all()

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

                # Compute the content_key from the UPDATED fields (not the old ORM values)
                # so the key is always in sync with detected_title/year/media_type.
                # Build a lightweight proxy that reflects the new field values without
                # mutating the channel yet — this lets us include content_key in the
                # changed comparison atomically.
                class _NewFields:
                    __slots__ = ("detected_title", "media_type", "detected_year", "id")
                    def __init__(self, title, mt, year, ch_id):
                        self.detected_title = title
                        self.media_type = mt
                        self.detected_year = year
                        self.id = ch_id
                new_content_key = content_key_for(
                    _NewFields(new_title, channel.media_type, new_year, channel.id)
                )

                changed = (
                    prefix != channel.detected_prefix
                    or quality != channel.detected_quality
                    or region != channel.detected_region
                    or new_title != channel.detected_title
                    or new_year  != channel.detected_year
                    or new_content_key != channel.content_key
                    or new_detected_audio != channel.detected_audio
                )
                if changed:
                    channel.detected_prefix = prefix
                    channel.detected_quality = quality
                    channel.detected_region = region
                    channel.detected_title  = new_title
                    channel.detected_year   = new_year
                    channel.content_key     = new_content_key
                    channel.detected_audio  = new_detected_audio
                    channel.updated_at = datetime.now()
                    updated += 1

            processed += len(channels)
            self.session.commit()
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
        if not (is_cancelled is not None and is_cancelled()):
            sib_filled = self._propagate_region_from_siblings(provider_id)

        logger.info(
            f"Updated parsed name fields for {updated} of {processed} channels "
            f"(+{sib_filled} regions filled from content_key siblings)"
        )
        return updated

    def _propagate_region_from_siblings(
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
            # Project only the columns we need to stay memory-safe.
            rows = (
                self.session.query(
                    ChannelDB.id,
                    ChannelDB.detected_title,
                    ChannelDB.media_type,
                    ChannelDB.detected_year,
                )
                .filter(ChannelDB.id.in_(chunk_ids))
                .all()
            )

            for (ch_id, det_title, media_type, det_year) in rows:
                class _Proxy:
                    __slots__ = ("detected_title", "media_type", "detected_year", "id")
                    def __init__(self, t, m, y, i):
                        self.detected_title = t
                        self.media_type = m
                        self.detected_year = y
                        self.id = i
                key = content_key_for(_Proxy(det_title, media_type, det_year, ch_id))
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

    # ── Cross-source sibling lookup (content_key-based failover) ───────────────

    def get_content_key_siblings(
        self,
        content_key: str,
        exclude_channel_id: str,
    ) -> list[dict]:
        """Return sibling channels that share *content_key* but differ from the given channel.

        Used by the cross-source playback failover path: when a stream fails, the
        caller can try these sibling channels in order.

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

        Returns:
            List of plain dicts — safe to cross the Qt thread boundary:
            ``{id, name, stream_url, provider_id, detected_quality,
               detected_region, detected_prefix, is_active}``
            (``is_active`` comes from the joined ``ProviderDB.is_active`` flag).
        """
        from metatv.core.database import ProviderDB  # local import avoids circular

        if not content_key:
            return []

        _QUALITY_ORDER: dict[str, int] = {
            "4K": 0, "UHD": 0, "FHD": 1, "FHD+": 1, "HD": 2, "SD": 3,
        }

        rows = (
            self.session.query(ChannelDB, ProviderDB.is_active)
            .join(ProviderDB, ChannelDB.provider_id == ProviderDB.id, isouter=True)
            .filter(
                ChannelDB.content_key == content_key,
                ChannelDB.id != exclude_channel_id,
            )
            .all()
        )

        result: list[dict] = []
        for ch, is_active in rows:
            quality_rank = _QUALITY_ORDER.get(ch.detected_quality or "", 4)
            result.append({
                "id": ch.id,
                "name": ch.name,
                "stream_url": ch.stream_url,
                "provider_id": ch.provider_id,
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
            q = q.filter(ChannelDB.name.ilike(f"%{search_query}%"))

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

    _PRUNE_BATCH_SIZE = 2000

    def prune_provider_content(
        self,
        provider_ids: list[str],
    ) -> dict[str, int]:
        """Delete non-engaged channels (and their dependents) for a set of providers.

        "Engaged" means the channel was favorited, played, or queued.  Engaged
        channels are KEPT even when their provider is removed — they remain
        accessible in History / Favorites / Watch Queue and are hidden from
        forward-looking views via ``get_hidden_provider_ids()``.

        The delete is chunked (``_PRUNE_BATCH_SIZE`` ids per batch) with a
        ``session.commit()`` between batches so the transaction window stays
        small and SQLite's ``auto_vacuum=FULL`` reclaims pages incrementally.

        Args:
            provider_ids: Provider IDs whose non-engaged content should be
                purged.  May be an empty list (returns zero counts immediately).

        Returns:
            Dict with counts: ``channels``, ``metadata``, ``epg_by_channel``,
            ``epg_by_provider``, ``seasons``, ``episodes``, ``ratings``,
            ``alerts``.
        """
        if not provider_ids:
            return {
                "channels": 0, "metadata": 0, "epg_by_channel": 0,
                "epg_by_provider": 0, "seasons": 0, "episodes": 0,
                "ratings": 0, "alerts": 0,
            }

        counts: dict[str, int] = {
            "channels": 0, "metadata": 0, "epg_by_channel": 0,
            "epg_by_provider": 0, "seasons": 0, "episodes": 0,
            "ratings": 0, "alerts": 0,
        }

        # Step 1 — collect doomed channel ids (id-only: memory-safe even for 335k+)
        # A channel is engaged when it is favorited, has been played, or is queued.
        queued_subq = self.session.query(WatchQueueDB.channel_id)
        doomed_rows = (
            self.session.query(ChannelDB.id, ChannelDB.metadata_id)
            .filter(ChannelDB.provider_id.in_(provider_ids))
            .filter(
                ~or_(
                    ChannelDB.is_favorite == True,           # noqa: E712
                    ChannelDB.last_played.isnot(None),
                    ChannelDB.play_count > 0,
                    ChannelDB.id.in_(queued_subq),
                )
            )
            .all()
        )

        doomed_ids   = [r[0] for r in doomed_rows]
        doomed_meta  = [r[1] for r in doomed_rows if r[1] is not None]
        total_doomed = len(doomed_ids)

        logger.info(
            f"prune_provider_content: {total_doomed} non-engaged channels from "
            f"{len(provider_ids)} provider(s) — pruning in batches of "
            f"{self._PRUNE_BATCH_SIZE}"
        )

        # Step 2 — chunked deletes of channel-level dependents
        batch_size = self._PRUNE_BATCH_SIZE
        for batch_start in range(0, len(doomed_ids), batch_size):
            batch_ids  = doomed_ids [batch_start : batch_start + batch_size]
            batch_meta = doomed_meta[batch_start : batch_start + batch_size]

            # EpgProgramDB entries matched to these channels
            n = (
                self.session.query(EpgProgramDB)
                .filter(EpgProgramDB.channel_db_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["epg_by_channel"] += n

            # SeasonDB and EpisodeDB whose series_id is one of the doomed channels
            n = (
                self.session.query(EpisodeDB)
                .filter(EpisodeDB.series_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["episodes"] += n

            n = (
                self.session.query(SeasonDB)
                .filter(SeasonDB.series_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["seasons"] += n

            # UserRatingDB and AlertMatchDB tied to these channel ids
            n = (
                self.session.query(UserRatingDB)
                .filter(UserRatingDB.channel_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["ratings"] += n

            n = (
                self.session.query(AlertMatchDB)
                .filter(AlertMatchDB.channel_id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["alerts"] += n

            # MetadataDB rows referenced by these channels
            if batch_meta:
                n = (
                    self.session.query(MetadataDB)
                    .filter(MetadataDB.id.in_(batch_meta))
                    .delete(synchronize_session=False)
                )
                counts["metadata"] += n

            # Finally, the channels themselves
            n = (
                self.session.query(ChannelDB)
                .filter(ChannelDB.id.in_(batch_ids))
                .delete(synchronize_session=False)
            )
            counts["channels"] += n

            self.session.commit()

        # Step 3 — feed-side EPG: programmes whose provider_id is one of the
        # removed providers (these are EPG feed entries, not channel matches).
        # Chunk provider_ids only if unusually large; in practice < 10.
        pid_batch_size = 500
        for pid_start in range(0, len(provider_ids), pid_batch_size):
            pid_batch = provider_ids[pid_start : pid_start + pid_batch_size]
            n = (
                self.session.query(EpgProgramDB)
                .filter(EpgProgramDB.provider_id.in_(pid_batch))
                .delete(synchronize_session=False)
            )
            counts["epg_by_provider"] += n
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
        for pid_start in range(0, len(provider_ids), pid_batch_size):
            pid_batch = provider_ids[pid_start : pid_start + pid_batch_size]

            # Series channels that survived Step 2 for this batch == the engaged/kept
            # series whose seasons & episodes must be preserved.
            kept_series_subq = (
                self.session.query(ChannelDB.id)
                .filter(ChannelDB.provider_id.in_(pid_batch))
            )

            n = (
                self.session.query(EpisodeDB)
                .filter(EpisodeDB.provider_id.in_(pid_batch))
                .filter(~EpisodeDB.series_id.in_(kept_series_subq))
                # Floor: never delete an episode carrying user watch-state, even if
                # its series channel is already gone (pre-fix orphans).
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
            counts["episodes"] += n
            n = (
                self.session.query(SeasonDB)
                .filter(SeasonDB.provider_id.in_(pid_batch))
                .filter(~SeasonDB.series_id.in_(kept_series_subq))
                .delete(synchronize_session=False)
            )
            counts["seasons"] += n
            self.session.commit()

        logger.info(
            f"prune_provider_content complete: {counts['channels']} channels, "
            f"{counts['metadata']} metadata, "
            f"{counts['epg_by_channel'] + counts['epg_by_provider']} EPG rows, "
            f"{counts['seasons']} seasons, {counts['episodes']} episodes pruned; "
            f"engaged channels preserved."
        )
        return counts

