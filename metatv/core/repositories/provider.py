"""Provider repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

import json
from metatv.core.database import ProviderDB, ChannelDB
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
        """Delete provider and cascade-prune its non-engaged content.

        Non-engaged channels (not favorited, not played, not queued) and all
        their dependents (metadata, EPG, seasons, episodes, ratings, alerts)
        are deleted in memory-safe batches before the provider row is removed.

        Engaged channels of this provider are intentionally kept — they remain
        accessible in History / Favorites / Watch Queue and are hidden from
        forward-looking views via ``get_hidden_provider_ids()``.
        """
        provider = self.get_by_id(provider_id)
        if not provider:
            return False

        from metatv.core.repositories.channel import ChannelRepository
        ChannelRepository(self.session).prune_provider_content([provider_id])

        self.session.delete(provider)
        self.session.commit()
        logger.info(f"Provider {provider_id!r} deleted.")
        return True
    
    def update_stats(self, provider_id: str, total_channels: int, total_categories: int):
        """Update provider statistics"""
        provider = self.get_by_id(provider_id)
        if provider:
            provider.total_channels = total_channels
            provider.total_categories = total_categories
            provider.last_refresh = datetime.now()
            provider.updated_at = datetime.now()
            self.session.commit()
    
    def get_expired_provider_ids(self) -> List[str]:
        """Return IDs of providers whose subscription has lapsed (account_exp_date <= now).

        Uses datetime.now() — consistent with how account_exp_date is stored
        (datetime.fromtimestamp() in provider_editor.py, local-time naive).
        """
        now = datetime.now()
        rows = (
            self.session.query(ProviderDB.id)
            .filter(ProviderDB.account_exp_date.isnot(None))
            .filter(ProviderDB.account_exp_date <= now)
            .all()
        )
        return [r.id for r in rows]

    def get_inactive_provider_ids(self) -> List[str]:
        """Return IDs of providers the user has toggled off (is_active = False).

        Discovery/recommendation queries use an exclusion list, so disabled
        sources must be passed here to keep their content out of those views —
        mirroring how the main channel list scopes to active providers only.
        """
        rows = self.session.query(ProviderDB.id).filter_by(is_active=False).all()
        return [r.id for r in rows]

    def get_hidden_provider_ids(self) -> List[str]:
        """Return IDs of providers whose content must be hidden from forward-looking
        views — the union of **inactive** (user toggled off), **expired**, and
        **orphaned** (provider_id appears in channels but has no matching row in
        providers) sources.

        Orphaned provider_ids arise when a provider is deleted: the ``providers``
        row is removed but its channels are left behind with a stale ``provider_id``
        that no longer exists.  ``get_hidden_provider_ids`` was previously unaware
        of these, so orphaned channels bypassed all scoping and leaked into every
        forward-looking view.  Including them here closes that leak at the single
        canonical chokepoint — every existing ``excluded_provider_ids=get_hidden_provider_ids()``
        caller benefits automatically with no per-site changes.

        This is the single source of truth for provider scoping. Every view that
        shows "what you can watch" — the channel list, Discover shelves, See-All
        browse, recommendations — must exclude these ids. Record/engaged views
        (History, Favorites, Watch Queue) are the deliberate exception: they show
        prior engagement regardless of a source's current state.
        """
        orphaned = {
            row[0] for row in (
                self.session.query(ChannelDB.provider_id)
                .filter(~ChannelDB.provider_id.in_(self.session.query(ProviderDB.id)))
                .distinct()
                .all()
            )
            if row[0]
        }
        return list(
            set(self.get_inactive_provider_ids())
            | set(self.get_expired_provider_ids())
            | orphaned
        )

    def get_epg_active_provider_ids(self) -> List[str]:
        """Providers eligible for EPG/watchlist surfacing: is_active, not expired,
        with a non-empty epg_url, and epg_enabled is not False (NULL treated as
        enabled for backwards compatibility with rows predating the column).

        The include-list counterpart of get_hidden_provider_ids() for EPG queries.
        """
        from sqlalchemy import or_
        expired = set(self.get_expired_provider_ids())
        rows = (
            self.session.query(ProviderDB.id)
            .filter(ProviderDB.is_active == True)  # noqa: E712
            .filter(ProviderDB.epg_url.isnot(None), ProviderDB.epg_url != "")
            .filter(
                or_(  # NULL → treat as enabled (legacy rows)
                    ProviderDB.epg_enabled.is_(None),
                    ProviderDB.epg_enabled == True,  # noqa: E712
                )
            )
            .all()
        )
        return [r.id for r in rows if r.id not in expired]

    def get_stale_epg_providers(self) -> List[tuple]:
        """Return ``(id, name, epg_data_end)`` for active providers whose fetched EPG
        guide has already ended — they have an ``epg_url`` but no current programmes.

        Staleness uses the canonical :func:`metatv.core.epg_utils.epg_is_stale`
        boundary (UTC-naive vs now_utc). Inactive sources and providers with
        epg_enabled=False are excluded — no point warning about EPG data the user
        has intentionally disabled."""
        from metatv.core.epg_utils import now_utc
        from sqlalchemy import or_
        rows = (
            self.session.query(ProviderDB.id, ProviderDB.name, ProviderDB.epg_data_end)
            .filter(ProviderDB.is_active == True)  # noqa: E712
            .filter(ProviderDB.epg_url.isnot(None), ProviderDB.epg_url != "")
            .filter(ProviderDB.epg_data_end.isnot(None))
            .filter(ProviderDB.epg_data_end < now_utc())
            .filter(
                or_(  # NULL → treat as enabled (legacy rows)
                    ProviderDB.epg_enabled.is_(None),
                    ProviderDB.epg_enabled == True,  # noqa: E712
                )
            )
            .all()
        )
        return [(r.id, r.name, r.epg_data_end) for r in rows]

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
