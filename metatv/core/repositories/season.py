"""Season repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

from metatv.core.database import SeasonDB


class SeasonRepository:
    """Repository for season data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, season_id: str) -> Optional[SeasonDB]:
        """Get season by ID"""
        return self.session.query(SeasonDB).filter_by(id=season_id).first()
    
    def get_by_series(self, series_id: str, provider_id: str) -> List[SeasonDB]:
        """Get all seasons for a series"""
        return self.session.query(SeasonDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).order_by(SeasonDB.season_number).all()
    
    def bulk_create_or_update(self, seasons: List[SeasonDB]):
        """Bulk create or update seasons"""
        for season in seasons:
            existing = self.get_by_id(season.id)
            if existing:
                # Update existing
                existing.name = season.name
                existing.cover_url = season.cover_url
                existing.episode_count = season.episode_count
                existing.raw_data = season.raw_data
                existing.updated_at = datetime.now()
            else:
                # Create new
                self.session.add(season)
        
        self.session.commit()
        logger.info(f"Bulk created/updated {len(seasons)} seasons")
    
    def delete_by_series(self, series_id: str, provider_id: str) -> int:
        """Delete all seasons for a series"""
        count = self.session.query(SeasonDB).filter_by(
            series_id=series_id,
            provider_id=provider_id
        ).delete()
        self.session.commit()
        logger.info(f"Deleted {count} seasons for series {series_id}")
        return count
