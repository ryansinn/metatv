"""Filtering utilities for channel organization"""

from typing import Optional, Dict, List, Set
from dataclasses import dataclass
from loguru import logger


def extract_prefix(channel_name: str) -> Optional[str]:
    """Extract prefix from channel name using simple heuristic.
    
    Strategy: Take everything before first ' - '
    Only return if it looks like a prefix (short, has uppercase)
    
    Deliberately ignores other formats like [XX], |XX|, etc. to keep them
    included by default (inclusive philosophy).
    
    Args:
        channel_name: Full channel name
        
    Returns:
        Detected prefix or None if no clear prefix found
        
    Examples:
        >>> extract_prefix("EN - Breaking Bad")
        'EN'
        >>> extract_prefix("AR - Drama Series")
        'AR'
        >>> extract_prefix("UK/US - The Office")
        'UK/US'
        >>> extract_prefix("4K - Movie Title")
        '4K'
        >>> extract_prefix("[SE] Star Trek")
        None  # No ' - ' separator, included by default
        >>> extract_prefix("Breaking Bad - S01E01")
        None
        >>> extract_prefix("Just A Title")
        None
    """
    if not channel_name or ' - ' not in channel_name:
        return None
    
    first_segment = channel_name.split(' - ', 1)[0].strip()
    
    # Heuristic: prefix should be short and have some uppercase
    # This filters out false positives like "Breaking Bad - S01E01"
    if len(first_segment) <= 20 and any(c.isupper() for c in first_segment):
        return first_segment
    
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
