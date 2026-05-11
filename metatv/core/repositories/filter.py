"""Filter repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from metatv.core.database import FilterDB


class FilterRepository:
    """Repository for filter data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, filter_id: str) -> Optional[FilterDB]:
        """Get filter by ID"""
        return self.session.query(FilterDB).filter_by(id=filter_id).first()
    
    def get_all(self, provider_id: Optional[str] = None, enabled_only: bool = False) -> List[FilterDB]:
        """Get all filters"""
        query = self.session.query(FilterDB)
        
        if provider_id:
            query = query.filter(
                (FilterDB.is_global == True) | (FilterDB.provider_id == provider_id)
            )
        
        if enabled_only:
            query = query.filter_by(is_enabled=True)
        
        return query.order_by(FilterDB.order).all()
    
    def create(self, filter_db: FilterDB) -> FilterDB:
        """Create a new filter"""
        self.session.add(filter_db)
        self.session.commit()
        self.session.refresh(filter_db)
        return filter_db
    
    def update(self, filter_db: FilterDB) -> FilterDB:
        """Update filter"""
        filter_db.updated_at = datetime.now()
        self.session.commit()
        self.session.refresh(filter_db)
        return filter_db
    
    def delete(self, filter_id: str) -> bool:
        """Delete filter"""
        filter_db = self.get_by_id(filter_id)
        if filter_db:
            self.session.delete(filter_db)
            self.session.commit()
            return True
        return False
