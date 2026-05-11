"""Episode repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import EpisodeDB


class EpisodeRepository:
    """Repository for episode data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, episode_id: str) -> Optional[EpisodeDB]:
        """Get episode by ID"""
        return self.session.query(EpisodeDB).filter_by(id=episode_id).first()
    
    def get_by_series(self, series_id: str, provider_id: str) -> List[EpisodeDB]:
        """Get all episodes for a series"""
        return self.session.query(EpisodeDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).order_by(
            EpisodeDB.season_num,
            EpisodeDB.episode_num
        ).all()
    
    def get_by_season(self, season_id: str) -> List[EpisodeDB]:
        """Get all episodes for a season"""
        return self.session.query(EpisodeDB).filter_by(
            season_id=season_id
        ).order_by(EpisodeDB.episode_num).all()
    
    def get_last_played(self, series_id: str, provider_id: str) -> Optional[EpisodeDB]:
        """Get last played episode for a series"""
        return self.session.query(EpisodeDB).filter(
            EpisodeDB.series_id == series_id,
            EpisodeDB.provider_id == provider_id,
            EpisodeDB.last_played.isnot(None)
        ).order_by(EpisodeDB.last_played.desc()).first()
    
    def mark_played(self, episode_id: str):
        """Mark episode as played"""
        episode = self.get_by_id(episode_id)
        if episode:
            episode.last_played = datetime.now()
            episode.play_count = (episode.play_count or 0) + 1
            episode.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Marked episode as played: {episode.title}")
    
    def mark_watched(self, episode_id: str, watched: bool = True):
        """Mark episode as watched/unwatched"""
        episode = self.get_by_id(episode_id)
        if episode:
            episode.is_watched = watched
            episode.updated_at = datetime.now()
            self.session.commit()
            logger.info(f"Marked episode {episode.title} as {'watched' if watched else 'unwatched'}")
    
    def update_progress(self, episode_id: str, progress_seconds: int):
        """Update watch progress"""
        episode = self.get_by_id(episode_id)
        if episode:
            episode.watch_progress = progress_seconds
            episode.updated_at = datetime.now()
            self.session.commit()
    
    def bulk_create_or_update(self, episodes: List[EpisodeDB]):
        """Bulk create or update episodes"""
        for episode in episodes:
            existing = self.get_by_id(episode.id)
            if existing:
                # Update existing, preserve playback tracking
                existing.title = episode.title
                existing.duration = episode.duration
                existing.container_extension = episode.container_extension
                existing.stream_url = episode.stream_url
                existing.cover_url = episode.cover_url
                existing.raw_data = episode.raw_data
                existing.updated_at = datetime.now()
            else:
                # Create new
                self.session.add(episode)
        
        self.session.commit()
        logger.info(f"Bulk created/updated {len(episodes)} episodes")
    
    def delete_by_series(self, series_id: str, provider_id: str) -> int:
        """Delete all episodes for a series"""
        count = self.session.query(EpisodeDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).delete()
        self.session.commit()
        logger.info(f"Deleted {count} episodes for series {series_id}")
        return count
