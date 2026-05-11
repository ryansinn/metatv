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
    
    def get_all(self, provider_id: Optional[str] = None, 
                media_type: Optional[str] = None,
                media_types: Optional[List[str]] = None,
                language_prefixes: Optional[List[str]] = None,
                quality_prefixes: Optional[List[str]] = None,
                platform_prefixes: Optional[List[str]] = None,
                include_hidden: bool = False,
                invert_prefix_filters: bool = False) -> List[ChannelDB]:
        """Get all channels with optional filters
        
        Args:
            provider_id: Filter by specific provider (ready for future multi-provider filtering UI)
            media_type: Filter by single media type (deprecated, use media_types)
            media_types: Filter by list of media types (e.g., ['live', 'movies'])
            language_prefixes: List of language prefixes to include (e.g., ['EN', 'UK', 'US'])
            quality_prefixes: List of quality prefixes to include (e.g., ['4K', 'UHD'])
            platform_prefixes: List of platform prefixes to include (e.g., ['NETFLIX', 'HBO'])
            include_hidden: Include hidden channels
            invert_prefix_filters: If True, show only items NOT matching prefix filters
            
        Returns:
            List of channels matching all filters
        """
        query = self.session.query(ChannelDB)
        
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        
        # Media type filtering
        if media_types:
            query = query.filter(ChannelDB.media_type.in_(media_types))
        elif media_type:
            query = query.filter_by(media_type=media_type)
        
        if not include_hidden:
            query = query.filter_by(is_hidden=False)
        
        # Prefix filtering (language, quality, platform)
        prefix_filters = []
        if language_prefixes:
            prefix_filters.extend(language_prefixes)
        if quality_prefixes:
            prefix_filters.extend(quality_prefixes)
        if platform_prefixes:
            prefix_filters.extend(platform_prefixes)
        
        if prefix_filters:
            if invert_prefix_filters:
                # Show excluded items: channels NOT matching any of these prefixes
                query = query.filter(
                    (ChannelDB.detected_prefix.notin_(prefix_filters)) |
                    (ChannelDB.detected_prefix.is_(None))
                )
            else:
                # Normal mode: show only items matching these prefixes
                # Include channels with no prefix (NULL) by default
                query = query.filter(
                    (ChannelDB.detected_prefix.in_(prefix_filters)) |
                    (ChannelDB.detected_prefix.is_(None))
                )
        
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
    
    def update_detected_prefixes(self, provider_id: Optional[str] = None):
        """Update detected_prefix for all channels using prefix detection
        
        Args:
            provider_id: Only update channels for this provider, or None for all
        """
        query = self.session.query(ChannelDB)
        if provider_id:
            query = query.filter_by(provider_id=provider_id)
        
        channels = query.all()
        updated = 0
        
        for channel in channels:
            detected = extract_prefix(channel.name)
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
                        quality_groups: Optional[Dict[str, List[str]]] = None,
                        platform_groups: Optional[Dict[str, List[str]]] = None) -> Dict:
        """Get statistics about detected prefixes
        
        Args:
            provider_id: Only analyze channels for this provider
            language_groups: Language group mappings from config
            quality_groups: Quality group mappings from config
            platform_groups: Platform group mappings from config
            
        Returns:
            Dict with statistics about prefix distribution
        """
        language_groups = language_groups or {}
        quality_groups = quality_groups or {}
        platform_groups = platform_groups or {}
        
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
