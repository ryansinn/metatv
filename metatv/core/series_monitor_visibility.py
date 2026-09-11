"""ALERT-2: gate a monitored series' new-episode count/click-target to live sources.

A monitored series is mirrored across sources (:mod:`series_monitor`'s
``baselines``/``mirror_key``). ``unseen_new`` used to be one summed scalar with
no memory of WHICH mirror contributed it, so a mirror going hidden (provider
disabled/expired — ``ProviderRepository.get_hidden_provider_ids()``, the one
absolute gate per CLAUDE.md's engine/control/view layering) left its share
stuck in the total forever, and the row's click target (the entry's PRIMARY
channel) could open straight onto that dead source. Real case: "President
Curtis +17 eps" counted growth recorded on TREX Shared after it expired, and
clicking the row opened TREX Shared's copy.

:func:`visible_unseen` is the one predicate every forward-looking surface
(Watch Queue's Alerts Matched group, the Watch Alerts Series list, and their
menus) reads instead of the raw ``unseen_new``/``series_channel_id`` fields —
never a second gate hand-rolled per call site.
"""

from __future__ import annotations

from metatv.core.series_monitor import mirror_key, mirror_parts, provider_of


def visible_unseen(entry: dict, hidden_provider_ids) -> tuple[int, "str | None"]:
    """Return ``(count, mirror_key_to_open)`` gated to non-hidden sources.

    ``count`` sums ``unseen_by_mirror`` over mirrors whose provider (the half
    of the key before ``|``) is not in *hidden_provider_ids* — a mirror on a
    disabled/expired source contributes nothing, matching every other
    forward-looking view's absolute gate. ``(0, None)`` when every mirror
    carrying the series is hidden (or there is nothing unseen at all).

    ``mirror_key_to_open`` is the PRIMARY mirror when its provider is live
    (unchanged UX: the row still opens where the user favorited it from),
    else the live mirror with the largest share, else the first live mirror
    among the entry's established ``baselines``, else ``None``.

    Back-compat: an entry written before ``unseen_by_mirror`` existed carries
    its whole count on ``unseen_new`` alone with no per-mirror breakdown —
    that count can only ever be attributed to the PRIMARY mirror (the only
    listing ever checked before this change), so it is treated as if it were
    ``{primary: unseen_new}``. This is the ONE place that back-compat rule
    lives; nothing else re-derives it.
    """
    hidden = set(hidden_provider_ids or ())
    by_mirror = entry.get("unseen_by_mirror") or {}
    if not by_mirror:
        legacy = entry.get("unseen_new") or 0
        pid, sid = entry.get("provider_id"), entry.get("source_id")
        if legacy > 0 and pid and sid is not None:
            by_mirror = {mirror_key(pid, sid): legacy}

    live = {k: v for k, v in by_mirror.items() if v and provider_of(k) not in hidden}
    total = sum(live.values())
    if total <= 0:
        return 0, None

    pid, sid = entry.get("provider_id"), entry.get("source_id")
    primary = mirror_key(pid, sid) if pid and sid is not None else None
    if primary is not None and pid not in hidden:
        return total, primary
    if live:
        return total, max(live, key=live.get)
    for k in entry.get("baselines") or {}:
        if provider_of(k) not in hidden:
            return total, k
    return total, None


def resolve_open_channel_id(repos, mirror_key_to_open, fallback_channel_id: str) -> str:
    """Resolve a ``visible_unseen`` open target to a live ``ChannelDB.id``.

    Looks up the mirror's (provider_id, source_id) via ``ChannelRepository.
    get_by_source_id`` (same lookup ``main_window_series_playback`` uses to
    find an episode's parent channel) — falls back to *fallback_channel_id*
    (the entry's own ``series_channel_id``) when there is no open target or
    the mirror has no matching channel row. Must run inside the caller's open
    session (``repos`` is session-bound); never call off-thread work here.
    """
    if mirror_key_to_open:
        provider_id, source_id = mirror_parts(mirror_key_to_open)
        channel = repos.channels.get_by_source_id(provider_id=provider_id, source_id=source_id)
        if channel is not None:
            return channel.id
    return fallback_channel_id
