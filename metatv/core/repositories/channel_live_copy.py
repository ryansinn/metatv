"""The details pane's primary-copy resolver — VERS-1 (2026-09-11).

Owner report (screenshots): opening "President Curtis" from the Watch Queue's
Alerts Matched row rendered the copy on "TREX Shared" (an EXPIRED source) as
primary — Play, Watch Later, poster, "Source: TREX Shared" — while the only
PLAYABLE copy (ProSat, active) sat collapsed under "Also Available". Owner:
"the prosat version was buried under Also Available but it was the only
available enabled and online version."

CLAUDE.md's "Engine/control/view layering" rule makes a disabled/expired/
orphaned source an ABSOLUTE gate for forward-looking views —
``ProviderRepository.get_hidden_provider_ids()`` (inactive ∪ expired ∪
orphaned) is the one predicate. Engaged views (History/Favorites/Queue/
Alerts) are the documented exception and may legitimately hold a dead copy's
id — but the details PANE must still never show that dead copy as primary
when a live sibling of the same title exists. ``resolve_live_copy()`` is the
one chokepoint that enforces that, independent of which engaged view handed
it the id.

A module function, not a ``ChannelRepository`` mixin: ``channel.py`` is
baselined at 1739 lines in ``tests/code_health_baseline.json`` (currently
1686 — 53 lines of headroom), and this operation reaches across TWO
repositories (channels + providers) rather than owning one, so a bare
function taking the caller's already-open ``RepositoryFactory`` is the
better fit than growing the pinned class.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from metatv.core.database import ChannelDB, ProviderDB
from metatv.core.repositories.dtos import LiveCopy

if TYPE_CHECKING:
    from metatv.core.config import Config
    from metatv.core.repositories import RepositoryFactory


def _provider_state(provider: "Optional[ProviderDB]") -> str:
    """"expired" / "disabled" / "gone" — the same three axes
    ``ProviderRepository.get_hidden_provider_ids()`` unions (inactive ∪
    expired ∪ orphaned), read the same way it reads them.
    """
    if provider is None:
        return "gone"  # orphaned: provider_id has no matching providers row
    if provider.account_exp_date is not None and provider.account_exp_date <= datetime.now():
        return "expired"
    return "disabled"  # is_active == False, and not expired


def resolve_live_copy(
    repos: "RepositoryFactory", channel_id: str, config: "Optional[Config]" = None
) -> "Optional[LiveCopy]":
    """Return the copy of *channel_id* the details pane should show as primary.

    Must be called inside a ``session_scope()`` — *repos* carries the open
    session. Every ``PlayableChannelDTO`` on the returned ``LiveCopy`` is
    built by ``ChannelRepository.get_playable_dto()``, so no ORM object
    crosses the session boundary.

    Args:
        repos: The caller's ``RepositoryFactory`` (open session).
        channel_id: The channel an engaged view (or any other caller) asked
            to show.
        config: The user's ``Config`` — scores candidate siblings by version
            preference (prefix/provider/quality) via
            ``preference_engine.version_score``, the SAME ranking the
            "Other Versions" list uses for ``is_preferred``. ``None`` skips
            scoring (first live sibling encountered wins) — callers that
            have no ``Config`` handy (e.g. a stripped test host) still get a
            correct redirect, just not a preference-ranked one.

    Returns:
        None only when *channel_id* does not exist. Otherwise a ``LiveCopy``
        — see its docstring for the three shapes (live already / redirected
        / no live sibling).
    """
    requested = repos.channels.get_by_id(channel_id)
    if requested is None:
        return None

    hidden_ids = set(repos.providers.get_hidden_provider_ids())
    requested_dto = repos.channels.get_playable_dto(channel_id)

    if requested.provider_id not in hidden_ids:
        return LiveCopy(dto=requested_dto, redirected_from=None, dead_source_name=None)

    # The requested copy is on a hidden (inactive/expired/orphaned) source.
    # Find its live siblings — same content_key, matching how the "Other
    # Versions" list (_bg_fetch_versions, main_window_metadata.py) groups.
    # COALESCE(content_key, 'id:'||id): a row with no content_key is its own
    # singleton group by construction, so it has no siblings to query for —
    # querying content_key == None would (harmlessly) match every other
    # content_key-less row, which is wrong, so that case just short-circuits.
    live_siblings: "list[ChannelDB]" = []
    if requested.content_key:
        candidates = (
            repos.session.query(ChannelDB)
            .filter(
                ChannelDB.content_key == requested.content_key,
                ChannelDB.id != channel_id,
            )
            .all()
        )
        live_siblings = [
            c for c in candidates
            if c.media_type == requested.media_type
            and c.provider_id not in hidden_ids
            and not c.is_hidden
        ]

    best = None
    best_score = None
    if live_siblings:
        from metatv.core.preference_engine import version_score
        for c in live_siblings:
            score = version_score(c, config) if config is not None else 0
            if best is None or score > best_score:
                best = c
                best_score = score

    dead_provider = repos.session.get(ProviderDB, requested.provider_id)
    dead_state = _provider_state(dead_provider)
    dead_name = dead_provider.name if dead_provider is not None else requested.provider_id

    if best is not None:
        best_dto = repos.channels.get_playable_dto(best.id)
        return LiveCopy(
            dto=best_dto,
            redirected_from=requested_dto,
            dead_source_name=dead_name,
            dead_source_state=dead_state,
        )

    # No live sibling — the engaged row still opens, showing the dead copy,
    # but says why it cannot play.
    return LiveCopy(
        dto=requested_dto,
        redirected_from=None,
        dead_source_name=dead_name,
        dead_source_state=dead_state,
    )
