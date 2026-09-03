"""Provider repository for data access"""

from typing import Optional, List
from datetime import datetime
from sqlalchemy.orm import Session
from loguru import logger

import json
from metatv.core.url_policy import UrlRankingPolicy, get_url_ranking_policy
from metatv.core.database import Database, ProviderDB, ChannelDB
from metatv.core.models import ConnectionAttempt, Provider, ProviderURL

__all__ = [
    "ProviderRepository",
    "parse_provider_urls",
    "persist_url_stats",
    "provider_url_to_raw",
]


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
        except (ValueError, TypeError):
            return []  # silent: a malformed stored value means "no urls", which is the fallback
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


def provider_url_to_raw(pu: ProviderURL, *, priority: int) -> dict:
    """Serialize one in-memory ``ProviderURL`` for the ``ProviderDB.urls`` JSON blob.

    The single symmetric counterpart to :meth:`ProviderRepository.to_model`'s
    URL-parsing loop — every field ``to_model`` reads back out is written here,
    including ``recent_attempts`` (via ``_serialize_attempt``, the same helper
    ``persist_url_stats`` uses) and ``try_first``. *priority* is taken as a
    parameter rather than read off *pu* because callers serialize a whole list
    and want the priority to reflect DISPLAY order (``enumerate()``), not
    whatever stale value the field last held.

    Exists because the provider editor's old hand-built save-loop dict wrote
    only url/priority/is_active/success_count/failure_count — silently
    discarding ``recent_attempts``, ``last_success``, ``last_failure``,
    ``last_error``, and ``failed_client_ips`` on every Save. Centralizing the
    serialization here means a future ``ProviderURL`` field only needs to be
    added in ONE place to round-trip correctly.
    """
    return {
        "url": pu.url,
        "priority": priority,
        "is_active": pu.is_active,
        "success_count": pu.success_count,
        "failure_count": pu.failure_count,
        "last_success": pu.last_success.isoformat() if pu.last_success else None,
        "last_failure": pu.last_failure.isoformat() if pu.last_failure else None,
        "last_error": pu.last_error,
        "recent_attempts": [_serialize_attempt(a) for a in pu.recent_attempts],
        "failed_client_ips": pu.failed_client_ips,
        "try_first": pu.try_first,
    }


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
                entry['try_first'] = pu.try_first
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
        with an effective EPG URL, and epg_enabled is not False (NULL treated as
        enabled for backwards compatibility with rows predating the column).

        The include-list counterpart of get_hidden_provider_ids() for EPG queries.

        "Has a URL" is decided by ``EpgManager.effective_epg_url()`` — the one
        chokepoint for that resolution (CLAUDE.md) — never the stale ``epg_url``
        column, which is only ever a write-once cache of credentials that were
        current at the time it was populated. Filtered in Python rather than SQL
        because the derivation depends on live credentials, not a persisted
        column; the ``providers`` table is small (tens of rows), so this is not
        the kind of large-table scan the async-background-reads rule guards.
        """
        from metatv.core.epg_manager import EpgManager
        from sqlalchemy import or_
        expired = set(self.get_expired_provider_ids())
        rows = (
            self.session.query(ProviderDB)
            .filter(ProviderDB.is_active == True)  # noqa: E712
            .filter(
                or_(  # NULL → treat as enabled (legacy rows)
                    ProviderDB.epg_enabled.is_(None),
                    ProviderDB.epg_enabled == True,  # noqa: E712
                )
            )
            .all()
        )
        return [
            r.id for r in rows
            if r.id not in expired and EpgManager.effective_epg_url(r)
        ]

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
        from metatv.core.epg_manager import EpgManager

        expired = set(self.get_expired_provider_ids())

        active_rows = (
            self.session.query(ProviderDB)
            .filter(ProviderDB.is_active == True)  # noqa: E712
            .all()
        )
        non_expired = [r for r in active_rows if r.id not in expired]
        with_url = [r for r in non_expired if EpgManager.effective_epg_url(r)]
        enabled = [r for r in non_expired if r.epg_enabled is not False]
        return {
            "total": self.session.query(ProviderDB.id).count(),
            "with_url": len(with_url),
            "enabled": len(enabled),
            "eligible": len(self.get_epg_active_provider_ids()),
        }

    def get_stale_epg_providers(self) -> List[tuple]:
        """Return ``(id, name, epg_data_end)`` for active providers whose fetched EPG
        guide has already ended — they have an effective EPG URL but no current
        programmes.

        Staleness uses the canonical :func:`metatv.core.epg_utils.epg_is_stale`
        boundary (UTC-naive vs now_utc). Inactive sources and providers with
        epg_enabled=False are excluded — no point warning about EPG data the user
        has intentionally disabled. "Has a URL" is decided by
        ``EpgManager.effective_epg_url()`` (see ``get_epg_active_provider_ids``'s
        docstring), never the stale ``epg_url`` column."""
        from metatv.core.epg_manager import EpgManager
        from metatv.core.epg_utils import now_utc
        from sqlalchemy import or_
        rows = (
            self.session.query(ProviderDB)
            .filter(ProviderDB.is_active == True)  # noqa: E712
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
        rows = [r for r in rows if EpgManager.effective_epg_url(r)]
        return [(r.id, r.name, r.epg_data_end) for r in rows]

    def get_used_icons(self) -> List[str]:
        """Return all non-empty icon values currently set on providers."""
        rows = self.session.query(ProviderDB.icon).all()
        return [r.icon for r in rows if r.icon]

    # ── Catalog refresh (SPORT-7) ────────────────────────────────────────
    #
    # ``refresh_schedule`` (manual/launch/daily/weekly/monthly) shipped in the
    # provider editor with zero readers — nothing anywhere fired a refresh
    # from it. These three methods are what the tick
    # (``main_window_providers._maybe_auto_refresh_catalogs``) and the Sports
    # view staleness banner read; the due/interval decision itself is a pure
    # function in ``core/catalog_refresh.py`` (control layer, DR-0007) — this
    # class only returns data.

    def _effective_catalog_refresh(self, provider: ProviderDB) -> Optional[datetime]:
        """COALESCE(last_catalog_refresh_at, MAX(channels.last_seen_at)) for one row.

        ``last_catalog_refresh_at`` is only stamped going forward (on a
        SUCCESSFUL refresh through the queue); a source that predates the
        column, or has never been refreshed since, falls back to the newest
        ``last_seen_at`` its channels carry (stamped on every ingest) so it
        isn't treated as infinitely stale the moment this shipped. ``None``
        when neither is available — the source has never ingested a channel.
        """
        if provider.last_catalog_refresh_at is not None:
            return provider.last_catalog_refresh_at
        from sqlalchemy import func
        return (
            self.session.query(func.max(ChannelDB.last_seen_at))
            .filter(ChannelDB.provider_id == provider.id)
            .scalar()
        )

    def get_active_providers_with_refresh_schedule(self) -> List[tuple]:
        """``(id, name, refresh_schedule, effective_last_refresh)`` for every
        ACTIVE provider — the catalog-refresh tick's one read; see
        ``metatv.core.catalog_refresh.catalog_refresh_due`` for what happens
        with each row.
        """
        rows = self.session.query(ProviderDB).filter(ProviderDB.is_active == True).all()  # noqa: E712
        return [
            (p.id, p.name, p.refresh_schedule or "manual", self._effective_catalog_refresh(p))
            for p in rows
        ]

    def get_newest_catalog_refresh(self) -> Optional[datetime]:
        """Newest effective catalog-refresh stamp across ACTIVE providers.

        The freshest active source's stamp — if even THAT one is old, every
        active source is at least as stale. Powers the Sports view banner:
        ``None`` when no active provider has ever ingested a channel.
        """
        values = [
            self._effective_catalog_refresh(p)
            for p in self.session.query(ProviderDB).filter(ProviderDB.is_active == True).all()  # noqa: E712
        ]
        values = [v for v in values if v is not None]
        return max(values) if values else None

    def get_stale_active_providers(self, threshold, now: Optional[datetime] = None) -> List[tuple]:
        """``(id, name)`` for ACTIVE providers whose effective catalog refresh
        is older than *threshold* (a ``timedelta``), or has never happened.

        Powers the Sports banner's "Refresh sources" action — enqueues
        exactly the sources that are actually stale rather than the whole
        corpus, so a source refreshed moments ago elsewhere isn't
        redundantly re-queued.
        """
        now = now or datetime.now()
        out = []
        for p in self.session.query(ProviderDB).filter(ProviderDB.is_active == True).all():  # noqa: E712
            effective = self._effective_catalog_refresh(p)
            if effective is None or (now - effective) >= threshold:
                out.append((p.id, p.name))
        return out

    def mark_catalog_refreshed(self, provider_id: str, when: Optional[datetime] = None) -> None:
        """Stamp ``last_catalog_refresh_at`` on a SUCCESSFUL catalog refresh.

        Called only from the refresh-success path
        (``main_window_providers._on_queue_refresh_finished``) — never on
        failure, so a source that just failed to refresh isn't treated as
        freshly current by the tick or the banner.
        """
        provider = self.get_by_id(provider_id)
        if provider:
            provider.last_catalog_refresh_at = when or datetime.now()
            self.session.commit()

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
                try_first=bool(u.get('try_first', False)),
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
