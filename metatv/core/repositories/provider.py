"""Provider repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

import json
from metatv.core.url_policy import UrlRankingPolicy, get_url_ranking_policy
from metatv.core.database import Database, ProviderDB, ChannelDB
from metatv.core.models import ConnectionAttempt, Provider, ProviderURL


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


def _parse_iso(value: object) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp string stored in a urls JSON blob entry.

    Returns ``None`` for a missing/blank/malformed value rather than raising —
    a corrupt or legacy row must not break provider loading.
    """
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _serialize_attempt(attempt: ConnectionAttempt) -> dict:
    """Serialize one in-memory ``ConnectionAttempt`` for the urls JSON blob.

    ``timestamp`` uses ``.isoformat()``, matching every other datetime already
    stored in this blob (``last_success``/``last_failure``); parsed back via
    the shared ``_parse_iso`` helper, never a second date parser.
    """
    return {
        "timestamp": attempt.timestamp.isoformat() if attempt.timestamp else None,
        "success": attempt.success,
        "client_ip": attempt.client_ip,
        "error_message": attempt.error_message,
        "response_time_ms": attempt.response_time_ms,
    }


def _parse_attempt(raw: object) -> Optional[ConnectionAttempt]:
    """Parse one stored ``recent_attempts`` entry, or ``None`` if malformed.

    A malformed/legacy entry is dropped rather than raising — mirrors
    ``_parse_iso``'s "corrupt data must not break provider loading" contract.
    """
    if not isinstance(raw, dict):
        return None
    timestamp = _parse_iso(raw.get("timestamp"))
    if timestamp is None:
        return None
    return ConnectionAttempt(
        timestamp=timestamp,
        success=bool(raw.get("success", False)),
        client_ip=raw.get("client_ip"),
        error_message=raw.get("error_message"),
        response_time_ms=raw.get("response_time_ms"),
    )


def persist_url_stats(db: Database, provider: Provider, policy: Optional[UrlRankingPolicy] = None) -> None:
    """Write *provider*'s in-memory per-URL connection stats back to the DB.

    :class:`~metatv.core.url_cycle.UrlCycler` records success/failure
    counters and timestamps onto the in-memory ``Provider.urls`` list only —
    it has no ``Database`` handle (``providers/`` must not gain one, per the
    engine/control/view layering rule). This is the control-layer
    counterpart: whichever caller owns both the mutated ``Provider`` and a
    ``Database`` calls this once after cycling to make the stats durable.

    Merges by matching ``pu.url.rstrip('/')`` against each stored raw URL
    entry's ``url`` (mirrors ``UrlCycler``'s own matching), preserving every
    other key already in the JSON blob (priority, is_active, etc.) — the same
    merge semantics as the inline block this replaces
    (``provider_loader.py``'s old write-back). Datetimes serialize as
    ``.isoformat()`` strings, matching the format ``main_window_streaming.py``
    already wrote. No-op when *provider* has no URLs to merge.

    Copies each entry dict before mutating it (``dict(entry)``, not the alias
    ``parse_provider_urls`` returns): the raw list it returns holds the SAME
    dict objects already living on ``db_prov.urls``, so mutating those
    in place and then reassigning ``db_prov.urls = raw`` would compare the
    "old" and "new" value as equal (they're literally the same, already-
    mutated dicts) — SQLAlchemy's attribute-history check sees no change and
    silently skips the UPDATE. Copying first keeps the old value's dicts
    untouched so the reassignment is a real, detectable change.

    ``recent_attempts`` round-trips too, capped at ``policy.recent_attempts_kept``
    (newest kept — ``recent_attempts`` is stored oldest-first, so a plain
    ``[-n:]`` slice keeps the tail) so the JSON blob never grows unbounded.

    Args:
        db: Database handle providing ``session_scope()``.
        provider: The in-memory Provider whose ``urls`` counters/timestamps
            should be persisted.
        policy: Supplies ``recent_attempts_kept``. Defaults to the process-wide
            ranking policy (resolved from ``Config`` once at startup), so
            existing two-arg call sites pick up the user's real setting.
    """
    if not provider.urls:
        return
    if policy is None:
        policy = get_url_ranking_policy()
    keep_n = max(policy.recent_attempts_kept, 0)
    try:
        with db.session_scope() as session:
            db_prov = session.query(ProviderDB).filter_by(id=provider.id).first()
            if not db_prov:
                return
            raw = [dict(entry) for entry in parse_provider_urls(db_prov.urls)]
            url_map = {pu.url.rstrip('/'): pu for pu in provider.urls}
            for entry in raw:
                key = entry.get('url', '').rstrip('/')
                pu = url_map.get(key)
                if pu is None:
                    continue
                entry['success_count'] = pu.success_count
                entry['failure_count'] = pu.failure_count
                entry['last_success'] = pu.last_success.isoformat() if pu.last_success else None
                entry['last_failure'] = pu.last_failure.isoformat() if pu.last_failure else None
                entry['last_error'] = pu.last_error
                kept = pu.recent_attempts[-keep_n:] if keep_n else []
                entry['recent_attempts'] = [_serialize_attempt(a) for a in kept]
            db_prov.urls = raw
    except Exception as e:
        logger.warning(f"Failed to persist URL stats for provider {provider.id!r}: {e}")


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

    def get_epg_readiness(self) -> dict:
        """Counts that explain WHY the EPG view is empty, not just that it is.

        ``get_epg_active_provider_ids()`` collapses four very different
        situations into one empty list — no sources at all, sources that carry
        no guide URL, sources with EPG switched off, and sources that are ready
        but haven't fetched yet. The view needs to tell them apart to say
        something actionable (task #17), so this returns the counts rather than
        a single verdict; the wording decision stays in the UI layer.

        Returns:
            ``{"total": int, "with_url": int, "enabled": int, "eligible": int}``
            over ACTIVE, non-expired sources — ``total`` counts every source
            regardless of state, so "you have no sources" stays distinguishable
            from "your sources can't do EPG".
        """
        from sqlalchemy import or_

        expired = set(self.get_expired_provider_ids())

        def _count(query) -> int:
            return len([r.id for r in query.all() if r.id not in expired])

        base = self.session.query(ProviderDB.id).filter(
            ProviderDB.is_active == True  # noqa: E712
        )
        with_url = base.filter(
            ProviderDB.epg_url.isnot(None), ProviderDB.epg_url != ""
        )
        enabled = base.filter(
            or_(
                ProviderDB.epg_enabled.is_(None),
                ProviderDB.epg_enabled == True,  # noqa: E712
            )
        )
        return {
            "total": self.session.query(ProviderDB.id).count(),
            "with_url": _count(with_url),
            "enabled": _count(enabled),
            "eligible": len(self.get_epg_active_provider_ids()),
        }

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
        """Convert database model to domain model, including alternate URLs.

        ``last_success``/``last_failure``/``last_error`` round-trip through
        here too (parsed via ``_parse_iso``) — without this, every
        ``ProviderURL`` built from the DB would start with those fields blank,
        and ``persist_url_stats`` would then wipe genuinely-stored history for
        any URL not touched during the current cycle. ``recent_attempts``
        round-trips the same way via ``_parse_attempt`` — a row with counts
        but no ``recent_attempts`` key (every pre-upgrade provider) simply
        yields an empty list, which ``ProviderURL.health_score()`` treats as
        "fall back to the lifetime ratio", not "untested".
        """
        urls: List[ProviderURL] = []
        for u in parse_provider_urls(db_provider.urls):
            if not u.get('url'):
                continue
            recent_attempts = [
                a for a in (
                    _parse_attempt(raw) for raw in (u.get('recent_attempts') or [])
                )
                if a is not None
            ]
            urls.append(ProviderURL(
                url=u['url'],
                priority=u.get('priority', 999),
                is_active=u.get('is_active', True),
                success_count=u.get('success_count', 0),
                failure_count=u.get('failure_count', 0),
                last_success=_parse_iso(u.get('last_success')),
                last_failure=_parse_iso(u.get('last_failure')),
                last_error=u.get('last_error'),
                recent_attempts=recent_attempts,
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
