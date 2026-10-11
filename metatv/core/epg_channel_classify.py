"""EPG-side channel classification — split out of ``channel_name_utils``.

Two EPG questions about a channel: what KIND of viewing it is for the "On Now"
type filter, and whether an EPG source's country domain can match its region.
Neither is name-parsing vocabulary, so they live beside the EPG code that asks.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from metatv.core.channel_name_utils import CONTENT_DESCRIPTOR_GROUPS


# ── EPG "On Now" viewing content-type classifier (Slice 3C) ────────────────────── #
# A *lighter*, distinct namespace from CONTENT_DESCRIPTOR_GROUPS/CONTENT_TYPE_DISPLAY_NAMES
# above — those classify the channel CORPUS (facet tagging / dedup provenance); this
# classifies a channel for the EPG "On Now" viewing-content-type filter ("All Types ▼").
# "Movies" is deliberately new here — it has no CONTENT_DESCRIPTOR_GROUPS/prefix-group
# equivalent, so it is keyword-only (never a direct prefix-group hit).
EPG_CONTENT_TYPES: tuple[str, ...] = ("Sports", "News", "Kids", "Movies", "Music")

# Keyword tables for the keyword-scan fallback (case-insensitive substring match against
# the channel name).  "Sports" is deliberately absent — its keywords are loaded from
# special_content.py's load_sports_definitions() (bundled sports_definitions.yaml + any
# user override) via _sports_keywords_flat() below, so the sport/league keyword list has
# exactly one home instead of a second, drifting copy here.
EPG_CONTENT_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "News": (
        "news", "cnn", "bbc news", "sky news", "msnbc", "fox news", "nbc news",
        "cbs news", "abc news", "al jazeera", "euronews", "france24", "reuters",
    ),
    "Kids": (
        "kids", "cartoon", "nick", "disney", "cbeebies", "junior", "baby",
        "nickelodeon", "boomerang", "cbbc", "toon",
    ),
    "Movies": (
        "movies", "cinema", "film", "hbo", "cinemax", "starz", "showtime",
    ),
    "Music": (
        "music", "mtv", "vh1", "hits", "radio", "trace", "vevo",
    ),
}


@lru_cache(maxsize=1)
def _sports_keywords_flat() -> tuple[str, ...]:
    """Flattened sport + league keywords from special_content.py (single source of truth).

    Deferred import: ``special_content.py`` imports ``parse_platform_event`` from this
    module at module scope, so importing it back here at module level would be a
    circular import — this local import breaks the cycle by deferring it to call time.

    Cached for the process lifetime: ``load_sports_definitions()`` reads a YAML file
    from disk, and this classifier runs once per On-Now row per render — re-reading the
    file per channel would be wasteful for a table that is effectively static per
    session (a settings-UI edit to the user override file takes effect next launch).
    """
    from metatv.core.special_content import load_sports_definitions

    sport_kw, league_kw = load_sports_definitions()
    flat: list[str] = []
    for keywords in sport_kw.values():
        flat.extend(k.lower() for k in keywords)
    for keywords in league_kw.values():
        flat.extend(k.lower() for k in keywords)
    return tuple(flat)


def classify_channel_content_type(name: str, detected_prefix: Optional[str]) -> Optional[str]:
    """Classify a channel's EPG viewing content type for the On Now "All Types" filter.

    Priority (cheapest/most-confident first):
      1. ``detected_prefix`` already denotes a content-descriptor group that is also
         in :data:`EPG_CONTENT_TYPES` (e.g. a channel whose stored prefix IS "Sports" /
         "Kids" / "Music" / "News") — no keyword scan needed, no ambiguity.
      2. Keyword scan over the lowercased channel *name* — Sports keywords come from
         special_content.py's sport/league loader (:func:`_sports_keywords_flat`);
         News/Kids/Movies/Music from :data:`EPG_CONTENT_TYPE_KEYWORDS`.
      3. ``None`` — the caller displays this as "Other".

    Pure — no DB, no Qt.  ``detected_prefix`` must be the channel's already-stored
    ``detected_prefix`` field (ingestion-computed) — never re-derive it by parsing the
    name here (CLAUDE.md "channel-name fields" rule).

    Args:
        name: The channel's raw name.
        detected_prefix: The channel's stored ``detected_prefix``, or ``None``/``""``.

    Returns:
        One of :data:`EPG_CONTENT_TYPES`, or ``None`` if nothing matched.
    """
    if detected_prefix:
        prefix_titled = detected_prefix.strip().title()
        if prefix_titled in CONTENT_DESCRIPTOR_GROUPS and prefix_titled in EPG_CONTENT_TYPES:
            return prefix_titled

    name_lower = (name or "").lower()
    if not name_lower:
        return None

    if any(kw in name_lower for kw in _sports_keywords_flat()):
        return "Sports"

    for content_type, keywords in EPG_CONTENT_TYPE_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return content_type

    return None


# ── EPG TLD compatibility (region-gated fuzzy matching, Wave 3 Slice 3B) ─────── #
# Maps a normalized region/prefix code (as stored in ChannelDB.detected_prefix /
# .detected_region — see channel_name_utils.normalize_region_code) to the set of EPG-feed
# TLDs (the lowercase suffix of an XMLTV epg_id, e.g. "UandEden.uk" -> "uk")
# that are plausible broadcast pairings for that region. Consulted ONLY by
# EpgManager._build_match_map's tiers 2/3 (same-/cross-provider fuzzy name
# matching, core/epg_manager.py) to reject cross-region false positives — e.g.
# an EN-prefixed channel fuzzy-matching a Spanish (.es) guide feed. Tier-1
# exact epg_channel_id matches are never gated.
#
# A code absent from this map, or an EPG feed with no parseable TLD, means the
# gate ABSTAINS — the match proceeds exactly as it did before this feature
# existed. This is deliberately partial: only common broadcast-language
# groupings are covered; an unrecognized region/prefix never blocks a match.
_EPG_TLD_EN = frozenset({"uk", "us", "ca", "ie", "au", "nz"})
_EPG_TLD_ES = frozenset({"es", "mx", "ar", "cl", "co"})
_EPG_TLD_DE = frozenset({"de", "at", "ch"})
_EPG_TLD_FR = frozenset({"fr", "be", "ca", "ch"})
_EPG_TLD_IT = frozenset({"it"})
_EPG_TLD_NL = frozenset({"nl", "be"})

REGION_TLD_COMPATIBILITY: dict[str, frozenset[str]] = {
    # English-language broadcast regions (2- and 3-letter forms + the "EN"
    # language-code prefix some providers use)
    "US": _EPG_TLD_EN, "UK": _EPG_TLD_EN, "GB": _EPG_TLD_EN, "CA": _EPG_TLD_EN,
    "IE": _EPG_TLD_EN, "AU": _EPG_TLD_EN, "NZ": _EPG_TLD_EN, "EN": _EPG_TLD_EN,
    "AUS": _EPG_TLD_EN, "IRL": _EPG_TLD_EN, "CAN": _EPG_TLD_EN,
    # Spanish-language broadcast regions
    "ES": _EPG_TLD_ES, "ESP": _EPG_TLD_ES, "MX": _EPG_TLD_ES, "MEX": _EPG_TLD_ES,
    "ARG": _EPG_TLD_ES, "CL": _EPG_TLD_ES, "CHL": _EPG_TLD_ES,
    "CO": _EPG_TLD_ES, "COL": _EPG_TLD_ES,
    # German-language broadcast regions (Switzerland is multilingual — also
    # compatible with the French/Italian TLD groups)
    "DE": _EPG_TLD_DE, "GER": _EPG_TLD_DE, "AT": _EPG_TLD_DE, "AUT": _EPG_TLD_DE,
    "CH": _EPG_TLD_DE | _EPG_TLD_FR | _EPG_TLD_IT,
    "SUI": _EPG_TLD_DE | _EPG_TLD_FR | _EPG_TLD_IT,
    # French-language broadcast regions (Belgium is multilingual — also
    # compatible with the Dutch TLD group)
    "FR": _EPG_TLD_FR, "FRA": _EPG_TLD_FR,
    "BE": _EPG_TLD_FR | _EPG_TLD_NL, "BEL": _EPG_TLD_FR | _EPG_TLD_NL,
    # Italian
    "IT": _EPG_TLD_IT, "ITA": _EPG_TLD_IT,
    # Dutch
    "NL": _EPG_TLD_NL, "NED": _EPG_TLD_NL,
}


def epg_tld_compatible(codes: "list[str | None] | tuple[str | None, ...]", epg_tld: str | None) -> bool:
    """Region-gate for EPG fuzzy matching (tiers 2/3 only — see epg_manager.py).

    Given a channel's detected region/prefix code(s) and an EPG feed's TLD
    (parsed from the trailing dot-suffix of its ``epg_id``), decide whether a
    fuzzy name match between them is a plausible broadcast pairing.

    Args:
        codes: The channel's ``detected_prefix`` / ``detected_region`` values
            (order doesn't matter; ``None``/empty entries are ignored).
        epg_tld: The EPG feed's parsed TLD (lowercase, no dot), or ``None``
            when the feed's epg_id had no parseable suffix.

    Returns:
        ``True`` whenever the gate can't make a confident call — no TLD, or
        neither code is in :data:`REGION_TLD_COMPATIBILITY` — so an
        unrecognized combination never blocks a match that would have
        succeeded before this feature existed (abstain). ``False`` only when
        at least one code IS mapped and the TLD is known but not in ANY
        mapped code's compatible set — an actual region mismatch.
    """
    if not epg_tld:
        return True  # abstain — no TLD to gate on
    known_sets = [
        REGION_TLD_COMPATIBILITY[c.strip().upper()]
        for c in codes
        if c and c.strip().upper() in REGION_TLD_COMPATIBILITY
    ]
    if not known_sets:
        return True  # abstain — neither code is in the compatibility map
    return any(epg_tld in s for s in known_sets)
