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
