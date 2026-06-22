"""Channel repository for data access"""

import re
from typing import Optional, List, Dict, Set
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
    _COMPOUND_PREFIX_RE, _PAREN_PREFIX_RE,
)
from metatv.core.repositories.dtos import FavoriteDTO, LiveEventDTO
from metatv.core.repositories.channel_stats import _ChannelStatsMixin


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
        )

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

        Returns:
            List of channels matching all filters.

        Filter logic:
            identity_pool = (language_prefixes OR region_prefixes OR platform_prefixes)
            result        = identity_pool AND quality_prefixes
            Language, Region, Platform all OR together — selecting more always grows the
            result set. Quality is the only restrictive axis (AND).
        """
        query = self.session.query(ChannelDB)

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

        query = query.order_by(ChannelDB.name)

        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            return query.limit(limit).all()
        return query.all()
    
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
        """Bulk create or update channels"""
        for channel in channels:
            existing = self.get_by_id(channel.id)
            if existing:
                # Update existing
                for key, value in channel.__dict__.items():
                    if not key.startswith('_'):
                        setattr(existing, key, value)
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
    
    def update_detected_prefixes(
        self,
        provider_id: Optional[str] = None,
        separators: list[str] | None = None,
        progress_cb=None,
        is_cancelled=None,
    ):
        """Update detected_prefix, detected_quality, and detected_region for all channels.

        - detected_prefix: raw separator-delimited prefix token (e.g. "EN", "4K")
        - detected_quality: quality token found anywhere in the name (suffix or quality-prefix)
        - detected_region: parenthetical lang/region qualifier at end of name (e.g. "(US)"→"US")

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
        """
        _BATCH = 2000

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

                changed = (
                    prefix != channel.detected_prefix
                    or quality != channel.detected_quality
                    or region != channel.detected_region
                    or new_title != channel.detected_title
                    or new_year  != channel.detected_year
                )
                if changed:
                    channel.detected_prefix = prefix
                    channel.detected_quality = quality
                    channel.detected_region = region
                    channel.detected_title  = new_title
                    channel.detected_year   = new_year
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

        logger.info(f"Updated parsed name fields for {updated} of {processed} channels")
        return updated

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

        # Step 4 — SeasonDB / EpisodeDB whose provider_id is in the removed set
        # (these belong to the provider even if series_id wasn't in the doomed batch
        # e.g. engaged series channels whose seasons/episodes should still be pruned).
        for pid_start in range(0, len(provider_ids), pid_batch_size):
            pid_batch = provider_ids[pid_start : pid_start + pid_batch_size]
            n = (
                self.session.query(EpisodeDB)
                .filter(EpisodeDB.provider_id.in_(pid_batch))
                .delete(synchronize_session=False)
            )
            counts["episodes"] += n
            n = (
                self.session.query(SeasonDB)
                .filter(SeasonDB.provider_id.in_(pid_batch))
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

