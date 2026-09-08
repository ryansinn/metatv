"""Playback-failure "may be stale" hint (roadmap "Playback & Queue", STALE-1).

Pure functions only: no Qt, no DB session — the caller resolves the DB value
and injects ``now``; nothing here reads the real clock.

**Which stored field feeds ``last_refresh`` below.** ``ProviderDB`` carries
two differently-named candidates, ``last_refresh`` and ``last_sync``, and
neither is the one this module actually wants:

- ``last_sync`` is never written anywhere in the codebase — it is listed in
  ``tests/unwired_stored_fields_allowlist.json`` as a known-dead stored
  field.
- ``last_refresh`` is set only by ``ProviderRepository.update_stats()``,
  which itself has zero call sites — so it never actually moves either.
- The field that DOES move on every successful catalog refresh is
  ``last_catalog_refresh_at`` (SPORT-7, stamped by
  ``ProviderRepository.mark_catalog_refreshed`` from
  ``catalog_refresh_tick._mark_catalog_refreshed`` after every successful
  refresh through ``RefreshQueueManager``), read via the existing
  ``ProviderRepository.effective_catalog_refresh_by_id()`` chokepoint
  (``COALESCE(last_catalog_refresh_at, MAX(channels.last_seen_at))`` — the
  same signal the retired Sports staleness banner and the catalog-refresh
  auto-refresh tick both already use). Callers here should pass THAT value
  as ``last_refresh``, not the identically-named-but-dead column.

Callers pass ``now = datetime.now()`` (local, naive) — the same clock
``mark_catalog_refreshed``/``catalog_refresh_tick`` use to stamp and compare
this timestamp family; EPG's UTC convention (``epg_utils.now_utc()``) does
not apply here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: A source not refreshed within this many hours is "probably stale" — the
#: owner's heuristic (2026-08-31): stream URLs carry provider-side tokens
#: that "sometimes go stale in a day or two."
STALE_AFTER_H = 24


def is_probably_stale(last_refresh: datetime | None, now: datetime) -> bool:
    """Whether a source's catalog is probably stale enough to explain a play failure.

    Args:
        last_refresh: The provider's effective last catalog refresh
            (``ProviderRepository.effective_catalog_refresh_by_id()``), or
            ``None`` when it has never ingested a channel.
        now: The instant to measure from — injected, never read from the
            real clock here.

    Returns:
        ``True`` when never refreshed, or refreshed >= ``STALE_AFTER_H``
        hours ago.
    """
    if last_refresh is None:
        return True
    return (now - last_refresh) >= timedelta(hours=STALE_AFTER_H)


def stale_hint(provider_name: str, last_refresh: datetime | None, now: datetime) -> str | None:
    """Build the failure-toast sentence for a probably-stale source, or None.

    Args:
        provider_name: The source's display name — named in the sentence
            only when there is no elapsed time to anchor it (never
            refreshed); the days-ago sentence omits it because the toast's
            "Refresh <name>" action button (built from this same
            truthiness in ``main_window_streaming.py``) already names the
            source once.
        last_refresh: Same meaning as in :func:`is_probably_stale`.
        now: Same meaning as in :func:`is_probably_stale`.

    Returns:
        A sentence like ``"Last refreshed 3 days ago — its stream links may
        have expired"``, or ``None`` when the source was refreshed within
        ``STALE_AFTER_H`` hours.
    """
    if not is_probably_stale(last_refresh, now):
        return None
    if last_refresh is None:
        return f"{provider_name} has never been refreshed — its stream links may have expired"
    days = (now - last_refresh).days
    plural = "s" if days != 1 else ""
    return f"Last refreshed {days} day{plural} ago — its stream links may have expired"
