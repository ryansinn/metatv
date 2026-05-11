"""Alert pattern repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session

from metatv.core.database import AlertPatternDB


class AlertRepository:
    """Repository for alert pattern data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, alert_id: str) -> Optional[AlertPatternDB]:
        """Get alert pattern by ID"""
        return self.session.query(AlertPatternDB).filter_by(id=alert_id).first()
    
    def get_all(self, enabled_only: bool = False) -> List[AlertPatternDB]:
        """Get all alert patterns"""
        query = self.session.query(AlertPatternDB)
        
        if enabled_only:
            query = query.filter_by(is_enabled=True)
        
        return query.all()
    
    def create(self, alert: AlertPatternDB) -> AlertPatternDB:
        """Create a new alert pattern"""
        self.session.add(alert)
        self.session.commit()
        self.session.refresh(alert)
        return alert
    
    def update(self, alert: AlertPatternDB) -> AlertPatternDB:
        """Update alert pattern"""
        alert.updated_at = datetime.now()
        self.session.commit()
        self.session.refresh(alert)
        return alert
    
    def delete(self, alert_id: str) -> bool:
        """Delete alert pattern"""
        alert = self.get_by_id(alert_id)
        if alert:
            self.session.delete(alert)
            self.session.commit()
            return True
        return False
