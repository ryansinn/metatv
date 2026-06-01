"""Provider repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

import json
from metatv.core.database import ProviderDB
from metatv.core.models import Provider, ProviderURL


def parse_provider_urls(raw: "str | list | None") -> list[dict]:
    """Coerce a ProviderDB.urls value (JSON string or list) into a list of dicts.

    Handles all formats that may appear in the DB column:
    - JSON-encoded string  → decoded then filtered
    - Already a list       → filtered in place
    - None / empty string  → empty list
    - Malformed JSON       → empty list (logged as warning by callers)
    """
    if isinstance(raw, str):
        if not raw:
            return []
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return [u for u in (raw or []) if isinstance(u, dict)]


class ProviderRepository:
    """Repository for provider data access"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def get_by_id(self, provider_id: str) -> Optional[ProviderDB]:
        """Get provider by ID"""
        return self.session.query(ProviderDB).filter_by(id=provider_id).first()
    
    def get_all(self, active_only: bool = False) -> List[ProviderDB]:
        """Get all providers"""
        query = self.session.query(ProviderDB)
        if active_only:
            query = query.filter_by(is_active=True)
        return query.all()
    
    def create(self, provider: ProviderDB) -> ProviderDB:
        """Create a new provider"""
        self.session.add(provider)
        self.session.commit()
        self.session.refresh(provider)
        return provider
    
    def update(self, provider: ProviderDB) -> ProviderDB:
        """Update provider"""
        provider.updated_at = datetime.now()
        self.session.commit()
        self.session.refresh(provider)
        return provider
    
    def delete(self, provider_id: str) -> bool:
        """Delete provider"""
        provider = self.get_by_id(provider_id)
        if provider:
            self.session.delete(provider)
            self.session.commit()
            return True
        return False
    
    def update_stats(self, provider_id: str, total_channels: int, total_categories: int):
        """Update provider statistics"""
        provider = self.get_by_id(provider_id)
        if provider:
            provider.total_channels = total_channels
            provider.total_categories = total_categories
            provider.last_refresh = datetime.now()
            provider.updated_at = datetime.now()
            self.session.commit()
    
    def get_used_icons(self) -> List[str]:
        """Return all non-empty icon values currently set on providers."""
        rows = self.session.query(ProviderDB.icon).all()
        return [r.icon for r in rows if r.icon]

    def to_model(self, db_provider: ProviderDB) -> Provider:
        """Convert database model to domain model, including alternate URLs."""
        urls: List[ProviderURL] = []
        for u in parse_provider_urls(db_provider.urls):
            if not u.get('url'):
                continue
            urls.append(ProviderURL(
                url=u['url'],
                priority=u.get('priority', 999),
                is_active=u.get('is_active', True),
                success_count=u.get('success_count', 0),
                failure_count=u.get('failure_count', 0),
            ))

        return Provider(
            id=db_provider.id,
            name=db_provider.name,
            type=db_provider.type,
            url=db_provider.url,
            urls=urls,
            username=db_provider.username,
            password=db_provider.password
        )
