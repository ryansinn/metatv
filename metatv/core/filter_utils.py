"""Filtering utilities for channel organization"""

import re
from typing import Optional, Dict, List, Set
from dataclasses import dataclass
from loguru import logger


# Bracket prefix at start of name: [SE], [UK], [4K], etc.
_BRACKET_RE = re.compile(r'^\[([A-Z0-9]{1,8})\]\s*')

# Valid prefix: starts with uppercase letter or digit, only [A-Z0-9/], max 10 chars.
# Rejects anything with spaces, lowercase, ★, or other separators embedded in it.
# + is allowed for streaming brands: D+, DISNEY+, PARAMOUNT+
_VALID_PREFIX = re.compile(r'^[A-Z0-9][A-Z0-9/+]{0,9}$')

# Fallback: PREFIX-  Title (dash directly after prefix, followed by 1+ spaces).
# Some providers omit the leading space: "EN-  Walking Dead" instead of "EN - Walking Dead".
_DASH_NO_SPACE_RE = re.compile(r'^([A-Z][A-Z0-9/+]{0,9})-\s+(.+)$')

# Default separator search order — longer/more-specific patterns first to avoid
# partial matches (e.g. " ★ " before bare "★").
DEFAULT_PREFIX_SEPARATORS: list[str] = [" ★ ", "★", " | ", "| ", "|", ": ", ":", " - "]


def extract_prefix(channel_name: str, separators: list[str] | None = None) -> Optional[str]:
    """Extract the prefix code from a channel name.

    Tries, in order:
    1. Bracket format: ``[XX] Title`` → returns ``XX``
    2. Each separator in *separators* (default: ★, |, :, then ' - ').
       The candidate before the separator must match ``[A-Z0-9][A-Z0-9/]{0,9}``
       (no spaces, no lowercase, ≤ 10 chars) to avoid false positives.
    3. Dash-no-space fallback: ``PREFIX-  Title`` → returns ``PREFIX``.

    Examples::

        extract_prefix("EN - Breaking Bad")    → 'EN'
        extract_prefix("EN-  Breaking Bad")    → 'EN'  (dash no-space variant)
        extract_prefix("AF ★ Wede - Doc")      → 'AF'
        extract_prefix("AFR| RTN TELE SAHEL")  → 'AFR'
        extract_prefix("[SE] Star Trek")       → 'SE'
        extract_prefix("UK: Channel Name")     → 'UK'
        extract_prefix("Breaking Bad - S01")   → None  (has lowercase)
        extract_prefix("Just A Title")         → None
    """
    if not channel_name:
        return None

    # [XX] bracket format at start of name
    m = _BRACKET_RE.match(channel_name)
    if m:
        return m.group(1)

    seps = separators if separators is not None else DEFAULT_PREFIX_SEPARATORS
    for sep in seps:
        if sep in channel_name:
            candidate = channel_name.split(sep, 1)[0].strip()
            if _VALID_PREFIX.match(candidate):
                return candidate

    # Fallback: PREFIX-  Title (no space before dash, 1+ spaces after)
    m2 = _DASH_NO_SPACE_RE.match(channel_name)
    if m2 and _VALID_PREFIX.match(m2.group(1)):
        return m2.group(1)

    return None


@dataclass
class PrefixStats:
    """Statistics about detected prefixes in channel list."""
    
    all_prefixes: Set[str]  # All unique prefixes found
    prefix_counts: Dict[str, int]  # Count per prefix
    language_groups: Dict[str, int]  # Count per language group
    quality_groups: Dict[str, int]  # Count per quality group
    platform_groups: Dict[str, int]  # Count per platform group
    unmapped_prefixes: Set[str]  # Prefixes not in any group
    total_channels: int  # Total channels analyzed
    channels_with_prefix: int  # Channels that have a detected prefix


def categorize_prefix(
    prefix: str,
    language_groups: Dict[str, List[str]],
    quality_groups: Dict[str, List[str]],
    platform_groups: Dict[str, List[str]]
) -> Dict[str, str]:
    """Categorize a prefix into language/quality/platform groups.
    
    Args:
        prefix: The detected prefix (e.g., "EN", "4K", "NETFLIX")
        language_groups: Mapping of group names to prefix lists
        quality_groups: Mapping of group names to prefix lists
        platform_groups: Mapping of group names to prefix lists
        
    Returns:
        Dict with keys 'language', 'quality', 'platform' and group names as values
        Empty string if no match found in that category
    """
    result = {
        'language': '',
        'quality': '',
        'platform': ''
    }
    
    prefix_upper = prefix.upper()
    
    # Check language groups
    for group_name, prefixes in language_groups.items():
        if any(prefix_upper == p.upper() for p in prefixes):
            result['language'] = group_name
            break
    
    # Check quality groups
    for group_name, prefixes in quality_groups.items():
        if any(prefix_upper == p.upper() for p in prefixes):
            result['quality'] = group_name
            break
    
    # Check platform groups
    for group_name, prefixes in platform_groups.items():
        if any(prefix_upper == p.upper() for p in prefixes):
            result['platform'] = group_name
            break
    
    return result


def compute_prefix_stats(
    channels: List[Dict],
    language_groups: Dict[str, List[str]],
    quality_groups: Dict[str, List[str]],
    platform_groups: Dict[str, List[str]]
) -> PrefixStats:
    """Compute statistics about prefix distribution in channel list.
    
    Args:
        channels: List of channel dicts with 'name' and 'detected_prefix' keys
        language_groups: Language group mappings from config
        quality_groups: Quality group mappings from config
        platform_groups: Platform group mappings from config
        
    Returns:
        PrefixStats object with aggregated statistics
    """
    all_prefixes = set()
    prefix_counts = {}
    language_counts = {}
    quality_counts = {}
    platform_counts = {}
    unmapped = set()
    channels_with_prefix = 0
    
    for channel in channels:
        prefix = channel.get('detected_prefix')
        if not prefix:
            continue
        
        channels_with_prefix += 1
        all_prefixes.add(prefix)
        prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
        
        # Categorize prefix
        categories = categorize_prefix(prefix, language_groups, quality_groups, platform_groups)
        
        # Track if unmapped
        if not any(categories.values()):
            unmapped.add(prefix)
        
        # Count by category
        if categories['language']:
            lang = categories['language']
            language_counts[lang] = language_counts.get(lang, 0) + 1
        
        if categories['quality']:
            qual = categories['quality']
            quality_counts[qual] = quality_counts.get(qual, 0) + 1
        
        if categories['platform']:
            plat = categories['platform']
            platform_counts[plat] = platform_counts.get(plat, 0) + 1
    
    return PrefixStats(
        all_prefixes=all_prefixes,
        prefix_counts=prefix_counts,
        language_groups=language_counts,
        quality_groups=quality_counts,
        platform_groups=platform_counts,
        unmapped_prefixes=unmapped,
        total_channels=len(channels),
        channels_with_prefix=channels_with_prefix
    )


def get_excluded_prefixes(config) -> set[str]:
    """Return the set of explicitly blocked prefix codes.

    These are always hidden regardless of the allowlist state. Written by the
    "Block [PREFIX]" quick action in the Other Versions section of the details pane.
    """
    return set(getattr(config, "global_filter_excluded_prefixes", []))


def get_active_category_filter(config) -> tuple[list[str] | None, bool]:
    """Return prefix codes to EXCLUDE from the global category blacklist.

    config.global_filter_excluded_categories stores prefix codes to hide
    (e.g. ["AR", "KU"]). Empty list = hide nothing (show everything).

    Returns:
        (excluded_prefixes_or_None, include_uncategorized)
        excluded_prefixes is None when no exclusions are active.
    """
    if getattr(config, "global_filter_paused", False):
        return None, True
    prefixes = list(getattr(config, "global_filter_excluded_categories", []))
    include_uncategorized = getattr(config, "global_filter_include_uncategorized", True)
    return (prefixes if prefixes else None), include_uncategorized


def get_active_content_type_filter(config) -> list[str] | None:
    """Resolve excluded content types → raw source_category labels to hide.

    Combines:
    1. Named group exclusions (global_filter_excluded_content_types) — group name → raw labels
    2. Individual raw label exclusions (global_filter_excluded_source_categories) — the
       "Other" expandable section in the Exclusions dialog

    Returns a list of raw source_category labels to hide, or None if nothing active.
    The sentinel "_other_" in excluded_content_types means hide ALL unmapped — callers handle it.
    """
    if getattr(config, "global_filter_paused", False):
        return None

    excluded_types: list[str] = list(getattr(config, "global_filter_excluded_content_types", []))
    excluded_raw:   list[str] = list(getattr(config, "global_filter_excluded_source_categories", []))

    if not excluded_types and not excluded_raw:
        return None

    groups: dict = getattr(config, "content_category_groups", {})
    raw_labels: list[str] = list(excluded_raw)  # start with individually excluded labels
    for type_name in excluded_types:
        if type_name == "_other_":
            continue  # handled separately by callers
        for lbl in groups.get(type_name, []):
            raw_labels.append(lbl)
    return raw_labels if raw_labels else None


def matches_filter(
    channel_detected_prefix: Optional[str],
    channel_media_type: str,
    included_media_types: List[str],
    included_language_groups: List[str],
    included_quality_groups: List[str],
    included_platform_groups: List[str],
    language_group_mappings: Dict[str, List[str]],
    quality_group_mappings: Dict[str, List[str]],
    platform_group_mappings: Dict[str, List[str]],
    invert_complex_filters: bool = False
) -> bool:
    """Check if a channel matches the current filter settings.
    
    Args:
        channel_detected_prefix: Detected prefix from channel name
        channel_media_type: Media type (live, movie, series)
        included_media_types: List of included media types
        included_language_groups: List of included language group names
        included_quality_groups: List of included quality group names
        included_platform_groups: List of included platform group names
        language_group_mappings: Config mapping of group names to prefixes
        quality_group_mappings: Config mapping of group names to prefixes
        platform_group_mappings: Config mapping of group names to prefixes
        invert_complex_filters: If True, show excluded items (for "Show Excluded" feature)
        
    Returns:
        True if channel should be shown, False if filtered out
    """
    # Media type filter (simple toggle, no invert)
    if channel_media_type not in included_media_types:
        return False
    
    # If no prefix, include by default (unless we're inverting to show excluded)
    if not channel_detected_prefix:
        return not invert_complex_filters
    
    # If no complex filters active (all empty), include everything
    if not (included_language_groups or included_quality_groups or included_platform_groups):
        return not invert_complex_filters
    
    # Categorize the channel's prefix
    categories = categorize_prefix(
        channel_detected_prefix,
        language_group_mappings,
        quality_group_mappings,
        platform_group_mappings
    )
    
    # Check if prefix matches any included group
    matches_language = (not included_language_groups or 
                       categories['language'] in included_language_groups)
    matches_quality = (not included_quality_groups or 
                      categories['quality'] in included_quality_groups)
    matches_platform = (not included_platform_groups or 
                       categories['platform'] in included_platform_groups)
    
    # All active filters must match
    matches = matches_language and matches_quality and matches_platform
    
    # Apply invert logic for "Show Excluded" feature
    if invert_complex_filters:
        return not matches
    
    return matches
