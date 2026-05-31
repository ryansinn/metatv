"""Channel repository for data access"""

from typing import Optional, List, Dict, Set
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, update
from loguru import logger

from metatv.core.database import ChannelDB
from metatv.core.filter_utils import extract_prefix, categorize_prefix
from metatv.core.channel_name_utils import parse_channel_name, normalize_region_code, QUALITY_TOKENS


class ChannelRepository:
    """Repository for channel data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, channel_id: str) -> Optional[ChannelDB]:
        """Get channel by ID"""
        return self.session.query(ChannelDB).filter_by(id=channel_id).first()
    
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
                include_hidden: bool = False,
                hidden_only: bool = False,
                invert_prefix_filters: bool = False,
                include_untagged: bool = True,
                adult_mode: str = "all",
                force_adult_provider_ids: Optional[List[str]] = None,
                source_categories: Optional[List[str]] = None,
                include_uncategorized_content_types: bool = True,
                search_query: Optional[str] = None,
                limit: Optional[int] = None) -> List[ChannelDB]:
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
                from sqlalchemy import or_
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
            from sqlalchemy import or_ as _or, and_ as _and

            # Build per-axis conditions, then OR them into one identity pool
            axis_conditions = []

            if language_prefixes:
                # Language matches on detected_prefix OR parenthetical detected_region suffix
                axis_conditions.append(_or(
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

            identity_cond = _or(*axis_conditions)

            if invert_prefix_filters:
                # Show channels NOT in the identity pool (must have a tag to be meaningful)
                query = query.filter(
                    ~identity_cond,
                    ChannelDB.detected_prefix.isnot(None),
                )
            elif include_untagged:
                # Include identity matches OR channels with no prefix/region at all
                query = query.filter(
                    _or(
                        identity_cond,
                        _and(
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
        # Only channels explicitly tagged with a matching quality marker pass through.
        if quality_prefixes:
            query = query.filter(ChannelDB.detected_quality.in_(quality_prefixes))

        # Content-type filter (source_category — live channels only)
        if source_categories is not None:
            from sqlalchemy import or_
            cond = ChannelDB.source_category.in_(source_categories)
            if include_uncategorized_content_types:
                cond = or_(cond, ChannelDB.source_category.is_(None))
            query = query.filter(cond)

        # SQL text search pushdown (case-insensitive LIKE on channel name)
        if search_query:
            query = query.filter(ChannelDB.name.ilike(f"%{search_query}%"))

        query = query.order_by(ChannelDB.name)

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
               hidden_only: bool = False) -> List[ChannelDB]:
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
    ):
        """Update detected_prefix, detected_quality, and detected_region for all channels.

        - detected_prefix: raw separator-delimited prefix token (e.g. "EN", "4K")
        - detected_quality: quality token found anywhere in the name (suffix or quality-prefix)
        - detected_region: parenthetical lang/region qualifier at end of name (e.g. "(US)"→"US")

        Args:
            provider_id: Only update channels for this provider, or None for all.
            separators: Ordered list of separator strings to try. Defaults to
                ``DEFAULT_PREFIX_SEPARATORS`` from filter_utils when None.
        """
        query = self.session.query(ChannelDB)
        if provider_id:
            query = query.filter_by(provider_id=provider_id)

        channels = query.all()
        updated = 0

        for channel in channels:
            raw_prefix = extract_prefix(channel.name, separators=separators)
            # Normalize full country/language names to standard codes:
            # "NIGERIA" → "NGA", "ENGLISH" → "EN", "TELUGU" → "TE", etc.
            prefix = normalize_region_code(raw_prefix) if raw_prefix else raw_prefix

            parsed = parse_channel_name(channel.name)

            # detected_quality priority:
            #   1. Name suffix  ("CNN HD" → "HD")
            #   2. Quality-as-prefix  ("HD - Movie" → "HD")
            #   3. API quality field  (channel.quality = "hd" → "HD")
            quality: str | None = None
            if parsed.quality:
                quality = parsed.quality[0].upper()
            elif prefix and prefix.upper() in QUALITY_TOKENS:
                quality = prefix.upper()
            elif channel.quality and channel.quality.upper() not in ("UNKNOWN", ""):
                api_q = channel.quality.upper()
                if api_q in QUALITY_TOKENS:
                    quality = api_q

            # detected_region: parenthetical lang/region suffix (e.g. "(US)" → "US")
            region: str | None = parsed.lang or None

            changed = (
                prefix != channel.detected_prefix
                or quality != channel.detected_quality
                or region != channel.detected_region
            )
            if changed:
                channel.detected_prefix = prefix
                channel.detected_quality = quality
                channel.detected_region = region
                channel.updated_at = datetime.now()
                updated += 1

        self.session.commit()
        logger.info(f"Updated parsed name fields for {updated} of {len(channels)} channels")
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

        if search_query:
            q = q.filter(ChannelDB.name.ilike(f"%{search_query}%"))

        return q.order_by(ChannelDB.name).all()

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

    def get_prefix_stats(self,
                        provider_id: Optional[str] = None,
                        language_groups: Optional[Dict[str, List[str]]] = None,
                        quality_groups: Optional[Dict[str, List[str]]] = None,
                        platform_groups: Optional[Dict[str, List[str]]] = None,
                        regional_groups: Optional[Dict[str, List[str]]] = None,
                        excluded_user_categories: Optional[set] = None) -> Dict:
        """Get statistics about detected prefixes.

        Args:
            provider_id: Only analyze channels for this provider.
            language_groups: Language group mappings from config.
            quality_groups: Quality group mappings from config.
            platform_groups: Platform group mappings from config.

        Returns:
            Dict with statistics about prefix distribution.
        """
        language_groups = language_groups or {}
        quality_groups = quality_groups or {}
        platform_groups = platform_groups or {}
        regional_groups = regional_groups or {}
        
        query = self.session.query(ChannelDB)
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        query = query.filter_by(is_hidden=False)
        if excluded_user_categories:
            # Must explicitly allow NULL user_category — SQL NOT IN excludes NULLs
            query = query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories))
            )

        # Get unique prefixes with counts
        prefix_query = self.session.query(
            ChannelDB.detected_prefix,
            func.count(ChannelDB.id)
        ).filter_by(is_hidden=False)
        if excluded_user_categories:
            prefix_query = prefix_query.filter(
                or_(ChannelDB.user_category.is_(None),
                    ~ChannelDB.user_category.in_(excluded_user_categories))
            )
        
        if provider_id:
            prefix_query = prefix_query.filter_by(provider_id=provider_id)
        
        prefix_query = prefix_query.group_by(ChannelDB.detected_prefix)
        
        prefix_counts = {}
        all_prefixes = set()
        no_prefix_count = 0
        
        for prefix, count in prefix_query.all():
            if prefix:
                prefix_counts[prefix] = count
                all_prefixes.add(prefix)
            else:
                no_prefix_count = count
        
        # Quality counts — use detected_quality directly (matches what the SQL filter uses).
        # Channels like "NF - Movie 4K" have detected_prefix=NF but detected_quality=4K;
        # counting by prefix alone would miss them and produce wildly wrong counts.
        quality_counts: dict[str, int] = {}
        dq_rows = (
            self.session.query(ChannelDB.detected_quality, func.count(ChannelDB.id))
            .filter(ChannelDB.is_hidden == False,  # noqa: E712
                    ChannelDB.detected_quality.isnot(None))
        )
        if provider_id:
            dq_rows = dq_rows.filter(ChannelDB.provider_id == provider_id)
        dq_rows = dq_rows.group_by(ChannelDB.detected_quality).all()
        dq_counts = {dq: cnt for dq, cnt in dq_rows}

        for group_name, tokens in quality_groups.items():
            total = sum(dq_counts.get(t.upper(), 0) for t in tokens)
            if total:
                quality_counts[group_name] = total

        # Categorize prefixes into language / platform groups
        language_counts = {}
        platform_counts = {}
        unmapped_prefixes = set()

        # Build reverse lookup: prefix → set of regional group names
        region_prefix_to_groups: Dict[str, List[str]] = {}
        for group_name, prefixes in regional_groups.items():
            for p in prefixes:
                region_prefix_to_groups.setdefault(p.upper(), []).append(group_name)

        region_counts: Dict[str, int] = {}

        for prefix in all_prefixes:
            categories = categorize_prefix(prefix, language_groups, quality_groups, platform_groups)
            count = prefix_counts[prefix]

            # A prefix that is itself a quality token (e.g. "4K - Movie") is already
            # counted via detected_quality above — don't double-count under language.
            if categories['quality']:
                continue

            in_region = prefix.upper() in region_prefix_to_groups
            if not (categories['language'] or categories['platform'] or in_region):
                unmapped_prefixes.add(prefix)

            if categories['language']:
                lang = categories['language']
                language_counts[lang] = language_counts.get(lang, 0) + count

            if categories['platform']:
                plat = categories['platform']
                platform_counts[plat] = platform_counts.get(plat, 0) + count

            # A prefix can belong to multiple regional groups (e.g. MX = both
            # "North America" and "Latin America" and "Central America")
            for rg in region_prefix_to_groups.get(prefix.upper(), []):
                region_counts[rg] = region_counts.get(rg, 0) + count

        # Unmapped prefixes surface as "Other" in the Language dropdown.
        # The individual prefix codes are also returned so the filter can pass them
        # to get_all() when the user selects "Other".
        unmapped_list = sorted(unmapped_prefixes)
        other_count = sum(prefix_counts[p] for p in unmapped_list)
        if unmapped_list:
            language_counts["Other"] = other_count

        total_channels = query.count()

        return {
            'all_prefixes': list(all_prefixes),
            'prefix_counts': prefix_counts,
            'language_groups': language_counts,
            'quality_groups': quality_counts,
            'platform_groups': platform_counts,
            'region_groups': region_counts,
            'unmapped_prefixes': unmapped_list,
            'total_channels': total_channels,
            'channels_with_prefix': total_channels - no_prefix_count,
            'channels_without_prefix': no_prefix_count
        }

    # -------------------------------------------------------------------------
    # Special content queries
    # -------------------------------------------------------------------------

    def get_sports_channels(
        self,
        sport_types: Optional[List[str]] = None,
        league_names: Optional[List[str]] = None,
    ) -> List[ChannelDB]:
        """Get sports channels with optional cascade filters.

        Empty or None filter lists mean "no filter — include all".
        The special value ``'unknown'`` in sport_types also matches channels
        whose sport_type is NULL, ensuring unclassified channels stay visible.

        Args:
            sport_types: Canonical sport names to include (e.g. ['hockey', 'soccer']).
            league_names: League display names to include (e.g. ['NHL', 'Premier League']).

        Returns:
            Channels ordered by sport_type, league_name, name.
        """
        query = self.session.query(ChannelDB).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        )

        if sport_types:
            lower_types = [s.lower() for s in sport_types]
            if 'unknown' in lower_types:
                query = query.filter(
                    (ChannelDB.sport_type.in_(sport_types)) |
                    (ChannelDB.sport_type.is_(None))
                )
            else:
                query = query.filter(ChannelDB.sport_type.in_(sport_types))

        if league_names:
            query = query.filter(ChannelDB.league_name.in_(league_names))

        return query.order_by(
            ChannelDB.sport_type, ChannelDB.league_name, ChannelDB.name
        ).all()

    def get_events_channels(self) -> List[ChannelDB]:
        """Get all live event channels (special_view == 'live_event').

        Returns:
            Channels ordered by name.
        """
        return self.session.query(ChannelDB).filter(
            ChannelDB.special_view == 'live_event',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).order_by(ChannelDB.name).all()

    def get_sports_taxonomy(self) -> Dict[str, Dict[str, List[str]]]:
        """Build the sport → league → team hierarchy for cascade filter dropdowns.

        Channels without a sport_type are placed under the key ``'unknown'``.
        Channels with a sport_type but no league_name appear in that sport's dict
        but have no league sub-key (so the League dropdown shows only sports that
        actually have league data).

        Returns:
            Nested dict: ``{sport: {league: [team, ...]}}`` — leagues and teams
            are sorted alphabetically.
        """
        rows = self.session.query(
            ChannelDB.sport_type,
            ChannelDB.league_name,
            ChannelDB.team_name,
        ).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).distinct().all()

        taxonomy: Dict[str, Dict[str, set]] = {}
        for sport, league, team in rows:
            sport_key = sport if sport else 'unknown'
            taxonomy.setdefault(sport_key, {})
            if league:
                taxonomy[sport_key].setdefault(league, set())
                if team:
                    taxonomy[sport_key][league].add(team)

        return {
            sport: {league: sorted(teams) for league, teams in sorted(leagues.items())}
            for sport, leagues in sorted(taxonomy.items())
        }

    def get_sports_counts(self) -> Dict[str, int]:
        """Return channel counts grouped by sport_type, for dropdown badges.

        Returns:
            Dict mapping sport display name (or 'unknown') to channel count.
        """
        rows = self.session.query(
            ChannelDB.sport_type,
            func.count(ChannelDB.id),
        ).filter(
            ChannelDB.special_view == 'sports',
            ChannelDB.is_hidden == False,
            ChannelDB.stream_url.isnot(None),
            ~ChannelDB.name.like('#%'),
        ).group_by(ChannelDB.sport_type).all()

        return {(sport if sport else 'unknown'): count for sport, count in rows}
