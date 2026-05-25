"""Channel repository for data access"""

from typing import Optional, List, Dict, Set
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from loguru import logger

from metatv.core.database import ChannelDB
from metatv.core.filter_utils import extract_prefix, categorize_prefix


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
                quality_prefixes: Optional[List[str]] = None,
                include_hidden: bool = False,
                invert_prefix_filters: bool = False,
                include_untagged: bool = True,
                adult_mode: str = "all",
                force_adult_provider_ids: Optional[List[str]] = None,
                source_categories: Optional[List[str]] = None,
                include_uncategorized_content_types: bool = True) -> List[ChannelDB]:
        """Get all channels with optional filters.

        Args:
            provider_id: Filter by provider — str for one provider, List[str] for multiple.
            media_type: Filter by single media type (deprecated, use media_types).
            media_types: Filter by list of media types (e.g. ['live', 'movies']).
            language_prefixes: List of language prefixes to include (e.g. ['EN', 'UK']).
            quality_prefixes: List of quality prefixes to include (e.g. ['4K', 'UHD']).
            include_hidden: Include hidden channels.
            invert_prefix_filters: If True, show only items NOT matching prefix filters.
            include_untagged: When False, exclude channels with no detected_prefix.
            source_categories: Raw source_category labels to include (live channels only).
                None = no filter (show all). Only meaningful when querying live channels.
            include_uncategorized_content_types: When source_categories is set, also
                include live channels with no source_category (True by default).

        Returns:
            List of channels matching all filters.
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

        if not include_hidden:
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

        # Prefix filtering (language + quality combined)
        prefix_filters = []
        if language_prefixes:
            prefix_filters.extend(language_prefixes)
        if quality_prefixes:
            prefix_filters.extend(quality_prefixes)

        if prefix_filters:
            if invert_prefix_filters:
                query = query.filter(
                    (ChannelDB.detected_prefix.notin_(prefix_filters)) |
                    (ChannelDB.detected_prefix.is_(None))
                )
            elif include_untagged:
                # Normal inclusive mode: matching prefixes OR untagged channels
                query = query.filter(
                    (ChannelDB.detected_prefix.in_(prefix_filters)) |
                    (ChannelDB.detected_prefix.is_(None))
                )
            else:
                # Strict mode: only channels with one of the selected prefixes
                query = query.filter(ChannelDB.detected_prefix.in_(prefix_filters))
        elif not include_untagged:
            # No prefix filter active, but user wants to hide untagged channels
            query = query.filter(ChannelDB.detected_prefix.isnot(None))

        # Content-type filter (source_category — live channels only)
        if source_categories is not None:
            from sqlalchemy import or_
            cond = ChannelDB.source_category.in_(source_categories)
            if include_uncategorized_content_types:
                cond = or_(cond, ChannelDB.source_category.is_(None))
            query = query.filter(cond)

        return query.all()
    
    def get_favorites(self) -> List[ChannelDB]:
        """Get all favorite channels"""
        return self.session.query(ChannelDB).filter_by(
            is_favorite=True,
            is_hidden=False
        ).order_by(ChannelDB.name).all()
    
    def get_recent_history(self, limit: int = 30) -> List[ChannelDB]:
        """Get recently played channels"""
        return self.session.query(ChannelDB).filter(
            ChannelDB.last_played.isnot(None)
        ).order_by(
            ChannelDB.last_played.desc()
        ).limit(limit).all()
    
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
               media_type: Optional[str] = None) -> List[ChannelDB]:
        """Search channels by name"""
        db_query = self.session.query(ChannelDB).filter(
            ChannelDB.name.ilike(f"%{query}%"),
            ChannelDB.is_hidden == False
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
        """Update detected_prefix for all channels using prefix detection.

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
            detected = extract_prefix(channel.name, separators=separators)
            if detected != channel.detected_prefix:
                channel.detected_prefix = detected
                channel.updated_at = datetime.now()
                updated += 1

        self.session.commit()
        logger.info(f"Updated detected_prefix for {updated} of {len(channels)} channels")
        return updated
    
    def get_prefix_stats(self,
                        provider_id: Optional[str] = None,
                        language_groups: Optional[Dict[str, List[str]]] = None,
                        quality_groups: Optional[Dict[str, List[str]]] = None) -> Dict:
        """Get statistics about detected prefixes.

        Args:
            provider_id: Only analyze channels for this provider.
            language_groups: Language group mappings from config.
            quality_groups: Quality group mappings from config.

        Returns:
            Dict with statistics about prefix distribution.
        """
        language_groups = language_groups or {}
        quality_groups = quality_groups or {}
        platform_groups: Dict[str, List[str]] = {}
        
        query = self.session.query(ChannelDB)
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        query = query.filter_by(is_hidden=False)
        
        # Get unique prefixes with counts
        prefix_query = self.session.query(
            ChannelDB.detected_prefix,
            func.count(ChannelDB.id)
        ).filter_by(is_hidden=False)
        
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
        
        # Categorize prefixes into groups
        language_counts = {}
        quality_counts = {}
        platform_counts = {}
        unmapped_prefixes = set()
        
        for prefix in all_prefixes:
            categories = categorize_prefix(prefix, language_groups, quality_groups, platform_groups)
            count = prefix_counts[prefix]
            
            if not any(categories.values()):
                unmapped_prefixes.add(prefix)
            
            if categories['language']:
                lang = categories['language']
                language_counts[lang] = language_counts.get(lang, 0) + count
            
            if categories['quality']:
                qual = categories['quality']
                quality_counts[qual] = quality_counts.get(qual, 0) + count
            
            if categories['platform']:
                plat = categories['platform']
                platform_counts[plat] = platform_counts.get(plat, 0) + count
        
        total_channels = query.count()
        
        return {
            'all_prefixes': list(all_prefixes),
            'prefix_counts': prefix_counts,
            'language_groups': language_counts,
            'quality_groups': quality_counts,
            'platform_groups': platform_counts,
            'unmapped_prefixes': list(unmapped_prefixes),
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
