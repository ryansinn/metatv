"""How urgent a provider's subscription expiry is, as a theme colour.

Lived in ``provider_editor.py`` under its own "Subscription time helper" banner
and was used by NOTHING in that file — all four callers are elsewhere
(``sources_manager_view``, ``provider_editor_tabs``, ``sidebar/sources_strip``,
``sidebar/sources``). A pure function with no dialog dependency, misfiled in a
1,000-line dialog module.

Moved while giving it an injectable ``now``: ``summarize_providers`` passes a
reference time and this reached for the real clock instead, so half the
classification followed each. The test that caught it had pinned a fixed date
since it was written and still went red on 2026-08-30, taking three unrelated
PRs with it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from metatv.gui import theme as _theme


def subscription_color(exp_date: Optional[datetime], created_at: Optional[datetime],
                       now: Optional[datetime] = None) -> str:
    """Return a CSS hex color for the subscription time remaining.

    ``now`` defaults to ``datetime.now()``; a caller with its own reference
    point MUST pass it, or half its answer follows a clock it cannot see.
    """
    if exp_date is None:
        return ""
    now = now or datetime.now()
    if exp_date <= now:
        return _theme.COLOR_MUTED  # expired — gray
    days_remaining = (exp_date - now).days
    if created_at and created_at < exp_date:
        total_days = (exp_date - created_at).days
        pct = days_remaining / total_days if total_days > 0 else 1.0
    else:
        pct = min(1.0, days_remaining / 30.0)  # fallback: 30-day window

    if pct > 0.15 and days_remaining > 7:
        return _theme.COLOR_OK   # green — plenty of time
    elif pct > 0.05 or days_remaining > 2:
        return _theme.COLOR_WARN   # amber — getting close
    else:
        return _theme.COLOR_ERR   # red — expiring very soon

