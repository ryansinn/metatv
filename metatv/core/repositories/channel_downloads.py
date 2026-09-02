"""The Downloaded channel-list scope (DL-5) — the ``downloaded_only`` axis.

Downloaded is a record/engaged view (DR-0007), same family as History/
Favorites/Queue: it lists channels with at least one COMPLETED download
regardless of the source's active state or Global Exclusions — a file
already saved to disk is the definition of engaged content, and it stays
playable even when its source is disabled.

Split out of ``channel.py`` rather than grown in place: that file is pinned
at its code-health ratchet ceiling, and CLAUDE.md's size rule is explicit —
"a pinned file at its ceiling means extract to a cohesive new module, not
rebaseline". ``_apply_channel_filters`` calls the two functions here; the
predicates themselves, and the reasoning for them, live here instead.
"""

from __future__ import annotations

from sqlalchemy import select

from metatv.core.database import ChannelDB, DownloadDB


def predicate():
    """WHERE clause: this channel has >=1 completed download."""
    completed = select(DownloadDB.channel_id).where(DownloadDB.state == "completed")
    return ChannelDB.id.in_(completed)


def visibility_overrides(downloaded_only: bool, excluded_provider_ids, excluded_keywords) -> dict:
    """``VisibilityScope`` kwargs for the provider/keyword exclusion axes.

    Forced empty when *downloaded_only* is set — regardless of what the
    caller passed — so the engine itself enforces the DR-0007/DL-5 exemption
    from active-source scoping and the Global Exclusions keyword axis, even
    if a caller forgets to omit them. ``hidden_only`` gets no such override;
    it stays scoped to active sources. Splat into ``VisibilityScope(**...)``.
    """
    if downloaded_only:
        return {"excluded_provider_ids": [], "excluded_keywords": set()}
    return {
        "excluded_provider_ids": list(excluded_provider_ids or []),
        "excluded_keywords": set(excluded_keywords or []),
    }
