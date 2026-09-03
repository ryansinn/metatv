"""Catalog-refresh due-ness (SPORT-7) — the control-layer decision.

The owner's decision, 2026-09-03: "the solution to stale data is telling the
user the data is stale in the UI and then the user either refreshes manually
or changes the interval to something that works better for how they use the
app." Two halves ship together: the Sports view says when the catalog is
stale (always on, ``BANNER_STALE_THRESHOLD`` below), and a source can opt
into automatic refresh via its existing "Auto-refresh" schedule.

That schedule (``ProviderDB.refresh_schedule`` — manual/launch/daily/weekly/
monthly) already existed in the provider editor and ``provider_settings_dialog``
with zero readers: nothing anywhere fired a refresh from it. This module is
what finally reads it. A refresh is always a BULK COMPLETE source refresh
through the existing serial queue (``RefreshQueueManager.enqueue``) — never
per-category polling.

Pure functions only: no DB session, no Qt. ``main_window_providers.py``'s
tick supplies the effective-last-refresh timestamps (from
``ProviderRepository``, the data layer) and calls :func:`catalog_refresh_due`
per provider — the decision itself, kept out of both the repository and the
GUI orchestration per DR-0007 (engine ← control ← view).
"""

from __future__ import annotations

from datetime import datetime, timedelta

#: schedule value -> interval. "manual" and "launch" are handled specially in
#: catalog_refresh_due and never looked up here.
CATALOG_REFRESH_THRESHOLDS: dict[str, timedelta] = {
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=30),
}

#: How stale an active source's catalog must be before the Sports view
#: banner speaks up. Independent of any source's opted-in schedule — this is
#: the always-on, passive half of the owner's decision; it fires even for a
#: source left on "Manual".
BANNER_STALE_THRESHOLD = timedelta(hours=6)

# ---------------------------------------------------------------------------
# LIVE-1 — the live-only refresh's own due-ness rules.
#
# Measured live on the owner's two active sources (2026-09-03):
# ``get_live_streams`` alone returns the COMPLETE live catalog in one request
# (ProSat 17,906 streams / 5.0 MB / 1.6s; Shark 55,761 / 18.7 MB / 3.9s), byte-
# identical to the live half of a full refresh. So the Sports banner's
# "Refresh sources" action, a global auto-rate (Settings -> Content), and
# opening Sports/Events all drive a LIVE-ONLY refresh — never the full one —
# through the rules below.
# ---------------------------------------------------------------------------

#: ``config.live_refresh_mode`` interval values -> interval. "manual" and
#: "on_view_open" are handled by the banner button and the view-open hook
#: respectively and are never looked up here.
LIVE_REFRESH_INTERVALS: dict[str, timedelta] = {
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "3h": timedelta(hours=3),
}

#: How long after a live refresh a Sports/Events VIEW OPEN must wait before it
#: can trigger another one. Owner, 2026-09-03: "within 5-10 minutes or
#: something" — the low end was chosen so a source that was skipped for
#: currently streaming recovers quickly. Sports and Events cover overlapping
#: content, so either view opening can trigger this — and the cooldown is
#: SHARED across both for free: both compare against the same
#: ``last_live_refresh_at`` stamp, so opening Sports then Events inside the
#: window sees the stamp Sports's own refresh already wrote and does not
#: double-fire.
LIVE_REFRESH_ON_OPEN_COOLDOWN = timedelta(minutes=5)


def live_refresh_due(mode: str, last_live_refresh: datetime | None, now: datetime) -> bool:
    """Whether the GLOBAL live-refresh interval lane should fire right now.

    Args:
        mode: ``config.live_refresh_mode`` ("manual"/"on_view_open"/"15m"/
            "30m"/"1h"/"3h"). "manual" and "on_view_open" never fire from
            this function — they are driven by the banner button and the
            on-view-open hook respectively, not the 5-minute interval tick.
        last_live_refresh: The provider's ``last_live_refresh_at``, or None
            when it has never had a live-only (or full) refresh.
        now: The instant to measure from — injected, never read from the
            clock here, so this is testable without sleeping.

    Returns:
        True when a live-only refresh is due for this provider right now.
    """
    interval = LIVE_REFRESH_INTERVALS.get(mode)
    if interval is None:
        return False
    if last_live_refresh is None:
        return True  # never live-refreshed at all — always due
    return (now - last_live_refresh) >= interval


def live_refresh_on_view_open_due(last_live_refresh: datetime | None, now: datetime) -> bool:
    """Whether opening Sports or Events should trigger a live-only refresh.

    Cooldown-only: the caller has already confirmed
    ``config.live_refresh_mode == "on_view_open"``. Both views call this
    through the same host hook (``_maybe_live_refresh_on_view_open``), and the
    SHARED cooldown falls out of comparing against the same
    ``last_live_refresh_at`` stamp — no separate per-view cooldown state.

    Args:
        last_live_refresh: The provider's ``last_live_refresh_at``, or None.
        now: The instant to measure from — injected, never read from the
            clock here.

    Returns:
        True when the cooldown has elapsed (or never applied).
    """
    if last_live_refresh is None:
        return True
    return (now - last_live_refresh) >= LIVE_REFRESH_ON_OPEN_COOLDOWN


def catalog_refresh_due(
    schedule: str | None,
    effective_last_refresh: datetime | None,
    now: datetime,
    *,
    at_launch: bool,
) -> bool:
    """Whether one provider's catalog is due for an automatic refresh right now.

    Args:
        schedule: The provider's ``refresh_schedule``
            ("manual"/"launch"/"daily"/"weekly"/"monthly"). Any other or
            missing value is treated as "manual" (never fires) — the safe
            default for a legacy/blank row.
        effective_last_refresh: ``COALESCE(last_catalog_refresh_at,
            MAX(channels.last_seen_at))`` for this provider
            (``ProviderRepository._effective_catalog_refresh``), or ``None``
            when the source has never ingested a channel.
        now: The instant to measure from — injected, never read from the
            clock here, so this is testable without sleeping.
        at_launch: True only for the one-time launch-time check; False for
            the hourly tick. "launch" fires ONLY when this is True, and
            unconditionally — that is what the "On App Launch" label
            promises, not a staleness check.

    Returns:
        True when this provider should be enqueued for a full catalog
        refresh right now.
    """
    schedule = schedule or "manual"
    if schedule == "manual":
        return False
    if schedule == "launch":
        return at_launch
    threshold = CATALOG_REFRESH_THRESHOLDS.get(schedule)
    if threshold is None:
        return False  # unrecognised value — never fires, same as "manual"
    if effective_last_refresh is None:
        return True  # never refreshed at all — always due
    return (now - effective_last_refresh) >= threshold
