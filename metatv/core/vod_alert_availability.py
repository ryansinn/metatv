"""Re-validate stored VOD watch-for matches against live source state.

Stored ``alerted_ids`` on a watch-for rule can reference channels whose source
was later disabled or expired (or channels since user-hidden).  Those are a
top-level gate — ``ProviderRepository.get_hidden_provider_ids()`` (inactive ∪
expired) content is NEVER shown, counted, or revealed by "show all".  Config's
raw ``get_vod_*`` methods stay the storage truth (used by the scan/dedup); every
COUNT surfaced to the user derives from the *available* subset computed here.

Single chokepoint: :func:`compute_alert_availability` runs one bounded ``IN``
query (via ``ChannelRepository.filter_available_ids``) for all rules' ids at
once, then derives every per-rule and aggregate count from that one set.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertAvailability:
    """AVAILABLE-only view of the stored watch-for matches (hidden-source ids gated out).

    Attributes:
        available_ids: Stored match ids currently on an active, visible source.
        excluded_provider_ids: The hidden (inactive ∪ expired) provider ids gated out.
        per_rule_unviewed: rule ``created`` → available *unviewed* match count.
        per_rule_total: rule ``created`` → available *total* match count.
        firing_rules: Number of rules with ≥1 available unviewed match.
        unviewed_total: Distinct available unviewed match ids across all rules.
    """

    available_ids: frozenset
    excluded_provider_ids: frozenset
    per_rule_unviewed: dict
    per_rule_total: dict
    firing_rules: int
    unviewed_total: int


def compute_alert_availability(config, repos) -> AlertAvailability:
    """Re-validate every rule's stored matches against live source state.

    Args:
        config: The app config (source of the raw watch-for rules).
        repos: A ``RepositoryFactory`` bound to an open session.

    Returns:
        An :class:`AlertAvailability` whose counts reflect only currently-available
        matches (never content on disabled/expired sources or user-hidden channels).
    """
    rules = config.get_vod_watch_alerts()

    all_ids: set = set()
    for r in rules:
        all_ids.update(r.get("alerted_ids") or [])

    excluded = set(repos.providers.get_hidden_provider_ids())
    available = repos.channels.filter_available_ids(all_ids, excluded) if all_ids else set()

    per_unviewed: dict = {}
    per_total: dict = {}
    unviewed_union: set = set()
    firing = 0
    for r in rules:
        created = r.get("created", "")
        alerted = set(r.get("alerted_ids") or [])
        viewed = set(r.get("viewed_ids") or [])
        avail_alerted = alerted & available
        avail_unviewed = (alerted - viewed) & available
        per_total[created] = len(avail_alerted)
        per_unviewed[created] = len(avail_unviewed)
        unviewed_union |= avail_unviewed
        if avail_unviewed:
            firing += 1

    return AlertAvailability(
        available_ids=frozenset(available),
        excluded_provider_ids=frozenset(excluded),
        per_rule_unviewed=per_unviewed,
        per_rule_total=per_total,
        firing_rules=firing,
        unviewed_total=len(unviewed_union),
    )
