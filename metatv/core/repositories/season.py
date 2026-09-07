"""Season repository for data access"""

from typing import Optional, List
from sqlalchemy.orm import Session

from metatv.core.database import SeasonDB
from metatv.core.repositories.dtos import SeasonDTO


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

    def get_seasons_dto(self, series_id: str, provider_id: str) -> "List[SeasonDTO]":
        """Return seasons as plain DTOs — thread-safe, no live session required."""
        seasons = self.get_by_series(series_id=series_id, provider_id=provider_id)
        result: list[SeasonDTO] = []
        for s in seasons:
            rating: str | None = None
            if s.raw_data and isinstance(s.raw_data, dict):
                rating = s.raw_data.get("rating") or None
            result.append(SeasonDTO(
                id=s.id,
                name=s.name,
                season_num=s.season_number,
                episode_count=s.episode_count,
                rating=rating,
            ))
        return result
    

