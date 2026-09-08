"""The failure toast's "Refresh <source>" offer (STALE-1).

Stream URLs carry provider-side tokens that expire, so a channel that played
yesterday can stop playing until its source is refreshed — and the app
already had the fix without ever suggesting it (owner, 2026-08-31). The
offer is scoped to the FAILING channel's provider and is only ever offered,
never auto-fired: a refresh is minutes of work and a connection.

Two halves, split by thread: :func:`read_last_refresh` runs in the play
worker (a DB read never belongs on the UI thread); :func:`stale_source_offer`
is a pure composition the main-thread toast builder calls with that result.
Kept out of ``main_window_streaming.py`` because that file sits at its
code-health ceiling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from loguru import logger

from metatv.core.repositories import RepositoryFactory
from metatv.core.source_staleness import stale_hint

Offer = tuple[str | None, tuple[str, Callable[[], None]] | None]


def read_last_refresh(db, provider_id: str | None):
    """The provider's effective last catalog refresh, read off-thread.

    Returns a ``datetime``, ``None`` when the provider has never ingested a
    channel (which :func:`stale_source_offer` treats as stale), or the
    string ``"unknown"`` when nothing trustworthy came back — no provider
    id, a lookup error, or a value that is not a datetime (a test double's
    ``MagicMock`` session, for one) — which yields NO offer rather than a
    wrong one.
    """
    if not provider_id:
        return "unknown"
    try:
        with db.session_scope(commit=False) as session:
            value = RepositoryFactory(session).providers.effective_catalog_refresh_by_id(provider_id)
    except Exception as exc:
        logger.debug("stale-source lookup failed for {}: {}", provider_id, exc)
        return "unknown"
    return value if value is None or isinstance(value, datetime) else "unknown"


def stale_source_offer(display_name: Callable[[str], str], refresh: Callable[[str], None],
                       provider_id: str | None, last_refresh, now: datetime) -> Offer:
    """Compose the toast's stale-source sentence and its action button.

    Args:
        display_name: ``MainWindow._provider_display_name``.
        refresh: ``MainWindow.refresh_provider`` — the ONE per-source refresh
            path; the button calls it with this provider id and nothing else.
        provider_id: The failing channel's provider.
        last_refresh: What :func:`read_last_refresh` returned.
        now: Injected clock.

    Returns:
        ``(hint, action)`` — both ``None`` when the source is not probably
        stale or its freshness is unknown; otherwise the sentence for the
        toast's detail line and a ``("Refresh <source>", callable)`` action.
    """
    if not provider_id or last_refresh == "unknown":
        return None, None
    name = display_name(provider_id)
    hint = stale_hint(name, last_refresh, now)
    if not hint:
        return None, None
    return hint, (f"Refresh {name}", lambda _p=provider_id: refresh(_p))
