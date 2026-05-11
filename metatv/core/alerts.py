"""Watch alerts system - tracks patterns and notifies on new matches"""

import re
import uuid
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import ChannelDB, AlertPatternDB, AlertMatchDB


class AlertPattern:
    """Watch alert pattern"""
    def __init__(
        self,
        id: str,
        name: str,
        pattern_type: str,
        pattern_value: str,
        applies_to: str = "all",
        description: str = "",
        is_enabled: bool = True,
        last_checked: Optional[datetime] = None
    ):
        self.id = id
        self.name = name
        self.pattern_type = pattern_type
        self.pattern_value = pattern_value
        self.applies_to = applies_to
        self.description = description
        self.is_enabled = is_enabled
        self.last_checked = last_checked


class AlertScanner:
    """Scans channels for alert pattern matches"""
    
    @staticmethod
    def scan_for_matches(session: Session, alert_pattern: AlertPattern, since: Optional[datetime] = None) -> List[str]:
        """
        Scan channels for matches to an alert pattern
        
        Args:
            session: Database session
            alert_pattern: Alert pattern to match against
            since: Only check channels added after this time (for new content detection)
        
        Returns:
            List of channel IDs that match
        """
        # Build base query
        query = session.query(ChannelDB)
        
        # Filter by media type if specified
        if alert_pattern.applies_to != "all":
            query = query.filter(ChannelDB.media_type == alert_pattern.applies_to)
        
        # Filter by added date if checking for new content
        if since:
            query = query.filter(ChannelDB.added_at > since)
        
        # Get all candidates
        channels = query.all()
        
        matches = []
        
        for channel in channels:
            if AlertScanner._matches_pattern(channel, alert_pattern):
                matches.append(channel.id)
        
        return matches
    
    @staticmethod
    def _matches_pattern(channel: ChannelDB, pattern: AlertPattern) -> bool:
        """Check if a channel matches the alert pattern"""
        
        if pattern.pattern_type == "keyword":
            # Case-insensitive keyword search in channel name
            return pattern.pattern_value.lower() in channel.name.lower()
        
        elif pattern.pattern_type == "regex":
            # Regex pattern matching
            try:
                return bool(re.search(pattern.pattern_value, channel.name, re.IGNORECASE))
            except re.error:
                logger.error(f"Invalid regex pattern: {pattern.pattern_value}")
                return False
        
        elif pattern.pattern_type == "quality":
            # Match quality level
            return channel.quality == pattern.pattern_value
        
        elif pattern.pattern_type == "media_type":
            # Match media type
            return channel.media_type == pattern.pattern_value
        
        elif pattern.pattern_type == "genre":
            # Genre matching (requires metadata)
            # TODO: Join with MetadataDB when metadata is integrated
            return False
        
        elif pattern.pattern_type == "actor":
            # Actor matching (requires metadata)
            # TODO: Join with MetadataDB when metadata is integrated
            return False
        
        return False
    
    @staticmethod
    def create_alert_matches(
        session: Session,
        alert_pattern_id: str,
        channel_ids: List[str]
    ) -> int:
        """
        Create alert match records for matched channels
        
        Args:
            session: Database session
            alert_pattern_id: ID of the alert pattern
            channel_ids: List of channel IDs that matched
        
        Returns:
            Number of new matches created
        """
        # Check for existing matches to avoid duplicates
        existing_matches = session.query(AlertMatchDB).filter(
            AlertMatchDB.alert_pattern_id == alert_pattern_id,
            AlertMatchDB.channel_id.in_(channel_ids)
        ).all()
        
        existing_channel_ids = {match.channel_id for match in existing_matches}
        
        new_count = 0
        for channel_id in channel_ids:
            if channel_id not in existing_channel_ids:
                match = AlertMatchDB(
                    id=str(uuid.uuid4()),
                    alert_pattern_id=alert_pattern_id,
                    channel_id=channel_id,
                    matched_at=datetime.now(),
                    is_viewed=False,
                    is_dismissed=False
                )
                session.add(match)
                new_count += 1
        
        if new_count > 0:
            session.commit()
            logger.info(f"Created {new_count} new alert matches for pattern {alert_pattern_id}")
        
        return new_count
    
    @staticmethod
    def get_alert_stats(session: Session) -> Dict[str, int]:
        """
        Get counts of unviewed matches per alert pattern
        
        Returns:
            Dict mapping alert_pattern_id to count of unviewed matches
        """
        results = session.query(
            AlertMatchDB.alert_pattern_id,
            session.query(AlertMatchDB).filter(
                AlertMatchDB.alert_pattern_id == AlertMatchDB.alert_pattern_id,
                AlertMatchDB.is_viewed == False,
                AlertMatchDB.is_dismissed == False
            ).count().label('count')
        ).group_by(AlertMatchDB.alert_pattern_id).all()
        
        # Simpler approach
        stats = {}
        patterns = session.query(AlertPatternDB).filter(AlertPatternDB.is_enabled == True).all()
        
        for pattern in patterns:
            count = session.query(AlertMatchDB).filter(
                AlertMatchDB.alert_pattern_id == pattern.id,
                AlertMatchDB.is_viewed == False,
                AlertMatchDB.is_dismissed == False
            ).count()
            stats[pattern.id] = count
        
        return stats
    
    @staticmethod
    def mark_matches_viewed(session: Session, alert_pattern_id: str):
        """Mark all matches for an alert pattern as viewed"""
        session.query(AlertMatchDB).filter(
            AlertMatchDB.alert_pattern_id == alert_pattern_id,
            AlertMatchDB.is_viewed == False
        ).update({AlertMatchDB.is_viewed: True})
        session.commit()
    
    @staticmethod
    def get_matched_channels(session: Session, alert_pattern_id: str, only_new: bool = True) -> List[ChannelDB]:
        """
        Get channels that match an alert pattern
        
        Args:
            session: Database session
            alert_pattern_id: Alert pattern ID
            only_new: If True, only return unviewed matches
        
        Returns:
            List of matching channels
        """
        query = session.query(ChannelDB).join(
            AlertMatchDB,
            ChannelDB.id == AlertMatchDB.channel_id
        ).filter(AlertMatchDB.alert_pattern_id == alert_pattern_id)
        
        if only_new:
            query = query.filter(
                AlertMatchDB.is_viewed == False,
                AlertMatchDB.is_dismissed == False
            )
        
        return query.all()
