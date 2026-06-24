"""Filtering utilities for channel organization"""

import html
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

    # |XX| leading-pipe format: prefix wrapped in pipes (ProSat/ottcst style),
    # e.g. "|WC| BEIN SPORTS 1 HD FR" → "WC", "|EN| Breaking Bad" → "EN".
    # Splitting on a bare "|" yields an empty candidate, so handle it explicitly:
    # take the token between the first two pipes and validate it as a prefix.
    if channel_name.startswith("|"):
        end = channel_name.find("|", 1)
        if end > 1:
            candidate = channel_name[1:end].strip()
            if _VALID_PREFIX.match(candidate):
                return candidate

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


# Normalises multilingual genre strings from Xtream providers to English canonical names.
# Providers supply genres in their own language (French, Italian, German, Spanish, Dutch, etc.)
# which creates duplicate clusters like Drama/Drame/Dramma/Dramat/Dramat.
# Keys are lowercased for case-insensitive lookup; values are the canonical English label.
#
# Canonical home (single source of truth): imported by both
# ``repositories/channel.py`` (normalize_genre) and ``repositories/channel_stats.py``
# (filter-stat aggregation). It lives here — a dependency-free leaf — because channel.py
# imports channel_stats.py, so the table cannot live in either of them without a cycle.
_GENRE_NORM: dict[str, str] = {
    # Drama variants (cross-language only — "Drama & History" is its own compound)
    "drame":                    "Drama",
    "dramma":                   "Drama",
    "dramat":                   "Drama",
    "draама":                   "Drama",
    # Comedy variants
    "comédie":                  "Comedy",
    "comedie":                  "Comedy",
    "komödie":                  "Comedy",
    "komedie":                  "Comedy",
    "commedia":                 "Comedy",
    "comedia":                  "Comedy",
    # Crime variants (cross-language only — "Crime & Mystery" is its own compound)
    "crimen":                   "Crime",
    "krimi":                    "Crime",
    "misdaad":                  "Crime",
    # Documentary variants
    "documentaire":             "Documentary",
    "documental":               "Documentary",
    "dokumentär":               "Documentary",
    "dokumentar":               "Documentary",
    "dokumentation":            "Documentary",
    "doku":                     "Documentary",
    # Sci-Fi (pure) — abbreviations + cross-language spellings of plain Science
    # Fiction. Kept DISTINCT from the "Sci-Fi & Fantasy" compound: a pure-SciFi or
    # pure-Fantasy title must never be mis-tagged into the combined genre — that
    # would muddy a clean SciFi (or Fantasy) set with the other (user steer
    # 2026-06-21; DR-0005 — compounds and their components are separate categories).
    "science fiction":          "Science Fiction",
    "sci-fi":                   "Science Fiction",
    "sci fi":                   "Science Fiction",
    "science-fiction":          "Science Fiction",
    "fantascienza":             "Science Fiction",
    "ciencia ficción":          "Science Fiction",
    "fantasy":                  "Fantasy",
    # "Sci-Fi & Fantasy" is the TMDb combined genre — its own category; only
    # cross-language aliases of the *compound* normalise to it.
    "science-fiction & fantastique": "Sci-Fi & Fantasy",
    # Mystery / Thriller variants
    "mystère":                  "Mystery",
    "mystere":                  "Mystery",
    "misterio":                 "Mystery",
    "mistero":                  "Mystery",
    "thriller":                 "Thriller",
    # Action / Adventure — pure forms stay distinct from the "Action & Adventure"
    # compound; only cross-language aliases of the *compound* normalise to it.
    "action & abenteuer":       "Action & Adventure",
    "action et aventure":       "Action & Adventure",
    "action":                   "Action",
    "adventure":                "Adventure",
    "abenteuer":                "Adventure",
    "aventure":                 "Adventure",
    "aventura":                 "Adventure",
    # Animation variants
    "animazione":               "Animation",
    "animación":                "Animation",
    "dessin animé":             "Animation",
    # Family / Kids variants
    "familial":                 "Family",
    "famille":                  "Family",
    "famiglia":                 "Family",
    "familia":                  "Family",
    "children":                 "Kids",
    "children & family":        "Kids",
    "kinder":                   "Kids",
    "jeunesse":                 "Kids",
    # Reality variants
    "reality tv":               "Reality",
    "realité":                  "Reality",
    "realite":                  "Reality",
    # War — pure "War" stays distinct from the "War & Politics" compound.
    "war & politics":           "War & Politics",
    "guerra":                   "War",
    "guerre":                   "War",
    # Western
    "western":                  "Western",
    # Horror / Suspense
    "horror":                   "Horror",
    "horreur":                  "Horror",
    "terror":                   "Horror",
    # Romance
    "romance":                  "Romance",
    "romantique":               "Romance",
    "romantico":                "Romance",
    # History
    "history":                  "History",
    "histoire":                 "History",
    "historia":                 "History",
    "historical":               "History",
    # Music
    "music":                    "Music",
    "musique":                  "Music",
    "música":                   "Music",
    # Sport
    "sport":                    "Sport",
    "sports":                   "Sport",
    # News / Current affairs
    "news":                     "News",
    "actualité":                "News",
    # Talk / Variety
    "talk show":                "Talk Show",
    "talk":                     "Talk Show",
    "variety":                  "Talk Show",
    # Arabic script variants (Arabic .lower() is a no-op so keys match directly)
    "دراما":                    "Drama",
    "ﺩﺭاﻣﺎ":                    "Drama",    # Arabic presentation-form variant
    "كوميديا":                  "Comedy",
    "ﻛﻮﻣﻴﺪﻱ":                  "Comedy",   # Arabic presentation-form variant
    "وثائقي":                   "Documentary",
    "جريمة":                    "Crime",
    "رعب":                      "Horror",
    "إثارة":                    "Thriller",
    "رومانسي":                  "Romance",
    "مغامرة":                   "Adventure",
    "أكشن":                     "Action",
    "أطفال":                    "Kids",
    "تاريخي":                   "History",
    "رياضة":                    "Sport",
    # Arabic — additional high-count compound and individual terms
    "حركة ومغامرة":              "Action & Adventure",   # Action & Adventure
    "غموض":                     "Mystery",               # Mystery
    "خيال علمي وفانتازيا":       "Sci-Fi & Fantasy",     # Sci-Fi & Fantasy
    "رسوم متحركة":               "Animation",             # Animation
    "عائلي":                    "Family",                # Family
    "حرب وسياسة":               "War & Politics",        # War & Politics
    "واقع":                     "Reality",               # Reality
    "أوبرا صابونية":            "Soap",                  # Soap opera
    "غربي":                     "Western",               # Western
    "كوميدي":                   "Comedy",                # Comedy (masculine form)
    "ﺗﺸﻮﻳﻖ ﻭﺇﺛﺎﺭﺓ":             "Thriller",              # Suspense & Excitement (presentation forms)
    "ﻏﻤﻮﺽ":                    "Mystery",               # Mystery (presentation forms)
    "ﻋﺎﺋﻠﻲ":                    "Family",                # Family (presentation forms)
    "ﺭﺳﻮﻡ ﻣﺘﺤﺮﻛﺔ":              "Animation",             # Animation (presentation forms)
    "ﺭﻋﺐ":                     "Horror",                # Horror (presentation forms)
    # Polish
    "kryminał":                 "Crime",                 # Crime
    "komedia":                  "Comedy",                # Comedy
    "akcja i przygoda":         "Action & Adventure",    # Action & Adventure
    "animacja":                 "Animation",             # Animation
    "tajemnica":                "Mystery",               # Mystery / Secret
    "dokumentalny":             "Documentary",           # Documentary
    "familijny":                "Family",                # Family
    "wojenny":                  "War",                   # War
    "akcja":                    "Action",                # Action
    "przygoda":                 "Adventure",             # Adventure
    "przygodowy":               "Adventure",             # Adventure (adjective form)
    "romans":                   "Romance",               # Romance
    "sensacyjny":               "Thriller",              # Thriller / Sensational
    "historyczny":              "History",               # Historical
    "fantastyczny":             "Fantasy",               # Fantastic/Fantasy
    # German / Scandinavian shared
    "kriminal":                 "Crime",                 # Criminal/Crime (German: Kriminal, ~1000 channels)
    # Swedish
    "komedi":                   "Comedy",                # Comedy
    "sci-fi & fantasi":         "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy
    "mystik":                   "Mystery",               # Mystery
    "dokumentarfilm":           "Documentary",           # Documentary
    "äventyr":                  "Adventure",             # Adventure
    "action & äventyr":         "Action & Adventure",    # Action & Adventure
    "animerat":                 "Animation",             # Animated
    "verklighet":               "Reality",               # Reality
    "brott":                    "Crime",                 # Crime
    "barn":                     "Kids",                  # Children/Kids
    "familj":                   "Family",                # Family
    "mysterium":                "Mystery",               # Mystery
    "krig & politik":           "War & Politics",        # War & Politics
    "kriminalitet":             "Crime",                 # Criminality
    "västern":                  "Western",               # Western
    "musik":                    "Music",                 # Music
    "skräck":                   "Horror",                # Horror/Fright
    "romantik":                 "Romance",               # Romance
    "underhållning":            "Talk Show",             # Entertainment/Variety
    "tävling":                  "Reality",               # Competition/Game Show
    "biografi":                 "History",               # Biography
    # Danish / Norwegian
    "virkelighed":              "Reality",               # Reality (Danish)
    "kriminalitet":             "Crime",                 # Criminality (shared)
    "børn":                     "Kids",                  # Children (Danish)
    "sci-fi og fantasy":        "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy (Danish)
    "dokumentarni":             "Documentary",           # Documentary (Croatian/Bosnian, also Norwegian)
    # Dutch
    "mysterie":                 "Mystery",               # Mystery
    "familie":                  "Family",                # Family
    "animatie":                 "Animation",             # Animation
    "misdaad (nordic)":         "Crime",                 # Crime (Nordic label)
    "romantiek":                "Romance",               # Romance
    "realiteit":                "Reality",               # Reality
    "muziek":                   "Music",                 # Music
    # Slovak
    "kriminálny":               "Crime",                 # Criminal
    "mysteriózny":              "Mystery",               # Mysterious
    "akčný a dobrodružný":      "Action & Adventure",    # Action & Adventure
    "vojnový a politický":      "War & Politics",        # War & Political
    "animovaný":                "Animation",             # Animated
    "rodinný":                  "Family",                # Family
    "dráma":                    "Drama",                 # Drama (Slovak/Hungarian)
    "komédia":                  "Comedy",                # Comedy (Slovak)
    "sf & fantasy":             "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy (Slovak short form)
    # Croatian / Bosnian / Serbian (Latin)
    "komedija":                 "Comedy",                # Comedy
    "akcija i avantura":        "Action & Adventure",    # Action & Adventure
    "rat i politika":           "War & Politics",        # War & Politics
    "ratni":                    "War",                   # War (adjective)
    "misterija":                "Mystery",               # Mystery
    "horor":                    "Horror",                # Horror
    "triler":                   "Thriller",              # Thriller
    "porodica":                 "Family",                # Family
    "porodični":                "Family",                # Family (adjective)
    "kriminalistički":          "Crime",                 # Criminal
    "romansa":                  "Romance",               # Romance
    # Portuguese
    "mistério":                 "Mystery",               # Mystery
    "comédia":                  "Comedy",                # Comedy
    "animação":                 "Animation",             # Animation
    "família":                  "Family",                # Family
    "documentário":             "Documentary",           # Documentary
    "documentario":             "Documentary",           # Documentary (no accent)
    "fantasia":                 "Fantasy",               # Fantasy
    "fantastique":              "Fantasy",               # Fantasy (French)
    # Greek
    "δράμα":                    "Drama",                 # Drama
    "μυστηρίου":                "Mystery",               # Mystery (genitive form)
    "κωμωδία":                  "Comedy",                # Comedy
    "κινούμενα σχέδια":         "Animation",             # Animation (lit. "moving designs")
    "ντοκυμαντέρ":              "Documentary",           # Documentary
    "οικογενειακή":             "Family",                # Family (feminine)
    "αστυνομική":               "Crime",                 # Police/Detective
    # Russian / Cyrillic
    "драма":                    "Drama",                 # Drama
    "комедия":                  "Comedy",                # Comedy
    "детектив":                 "Crime",                 # Detective/Crime
    "криминал":                 "Crime",                 # Criminal/Crime
    "боевик и приключения":     "Action & Adventure",    # Action & Adventure
    "нф и фэнтези":             "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy
    "семейный":                 "Family",                # Family
    # Hebrew
    "דרמה":                     "Drama",                 # Drama
    "קומדיה":                   "Comedy",                # Comedy
    "מדע בדיוני ופנטזיה":       "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy
    "מסתורין":                  "Mystery",               # Mystery
    "פשע":                      "Crime",                 # Crime
    "ילדים":                    "Kids",                  # Children/Kids
    "אקשן והרפתקאות":           "Action & Adventure",    # Action & Adventure
    "משפחה":                    "Family",                # Family
    # Turkish
    "aksiyon & macera":         "Action & Adventure",    # Action & Adventure
    "bilim kurgu & fantazi":    "Sci-Fi & Fantasy",      # Sci-Fi & Fantasy
    "suç":                      "Crime",                 # Crime
    "gizem":                    "Mystery",               # Mystery
    "aile":                     "Family",                # Family
    "savaş & politik":          "War & Politics",        # War & Politics
    "belgesel":                 "Documentary",           # Documentary
    "animasyon":                "Animation",             # Animation
    # Romanian
    "dramă":                    "Drama",                 # Drama
    "acţiune & aventuri":       "Action & Adventure",    # Action & Adventure
    "animaţie":                 "Animation",             # Animation
    "crimă":                    "Crime",                 # Crime
    # Persian / Farsi (commonly mixed in with English labels by providers)
    "درام":                     "Drama",                 # Drama (short form)
    "جنایی":                    "Crime",                 # Criminal/Crime
    "معمایی":                   "Mystery",               # Mystery
    "پلیسی":                    "Crime",                 # Police/Detective
    "خانوادگی":                 "Family",                # Family
    "تاریخی":                   "History",               # Historical
    "عاشقانه":                  "Romance",               # Romantic
    "اجتماعی":                  "Drama",                 # Social drama (closest canonical)
    "انیمیشن":                  "Animation",             # Animation
    "ماورایی":                  "Fantasy",               # Supernatural/Fantasy
    # Case-insensitive English variants (ALLCAPS from some providers)
    "drama":                    "Drama",
    "comedy":                   "Comedy",
    "documentary":              "Documentary",
    "crime":                    "Crime",
    "animation":                "Animation",
    "reality":                  "Reality",
    "horror":                   "Horror",
    "kids":                     "Kids",
    "western":                  "Western",
}


def normalize_genre(genre: str) -> str:
    """Return the canonical English genre label for a raw genre string.

    Applies the :data:`_GENRE_NORM` lookup so a genre clicked in the details
    pane maps to the same filter-panel key produced during stat aggregation.

    HTML entities are unescaped first so provider strings like
    ``"Action &amp; Adventure"`` and ``"Action & Adventure"`` both resolve to
    the same canonical label (bug A — duplicate shelves from HTML-encoded genres).
    """
    unescaped = html.unescape(genre)
    return _GENRE_NORM.get(unescaped.lower(), unescaped)


# The canonical genre vocabulary — the set of all values produced by
# ``normalize_genre``.  Used as a **strict allowlist** for the category→genre
# cross-walk: a token is only emitted as a genre tag when it normalizes to one
# of these known values.  This prevents junk provider labels like
# "NETFLIX MOVIES" or "TOP IMDB" from leaking into the genre namespace.
KNOWN_GENRES: frozenset[str] = frozenset(_GENRE_NORM.values())


def recognized_genre(s: str) -> str | None:
    """Return the canonical genre if *s* is a recognized genre string, else None.

    Unlike :func:`normalize_genre`, which passes through unknown strings
    unchanged, this function returns ``None`` for any input that does NOT
    resolve to a known canonical genre.  Use this as the **strict** predicate
    for the category→genre cross-walk, where the input is a raw provider
    category token and many tokens are NOT genres.

    Args:
        s: A raw string to test (e.g. a provider category segment like
           ``"ACTION"`` or ``"THRILLER"`` or ``"NETFLIX MOVIES"``).

    Returns:
        The canonical genre string (e.g. ``"Action"``, ``"Drama"``) if *s* is
        a recognized genre, or ``None`` if it is not.

    Examples::

        recognized_genre("action")          → "Action"
        recognized_genre("drame")           → "Drama"
        recognized_genre("KOMEDIE")         → "Comedy"
        recognized_genre("DRAMAT")          → "Drama"
        recognized_genre("NETFLIX MOVIES")  → None
        recognized_genre("TOP IMDB")        → None
        recognized_genre("")                → None
    """
    if not s or not s.strip():
        return None
    # Primary lookup: s.lower() is a key in _GENRE_NORM.
    lowered = s.strip().lower()
    canon = _GENRE_NORM.get(lowered)
    if canon is not None:
        return canon
    # Secondary: normalize_genre pass-through — if the result is itself a known
    # canonical value (e.g. "Action" → "Action"), accept it.
    unescaped = html.unescape(s.strip())
    result = _GENRE_NORM.get(unescaped.lower(), unescaped)
    if result in KNOWN_GENRES:
        return result
    return None
