"""Special content detection and parsing for PPV, Live Events, and Sports"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import yaml
from loguru import logger

from metatv.core.database import ChannelDB


# Built-in sport keyword map: canonical sport name → list of keywords to match
_DEFAULT_SPORT_KEYWORDS: Dict[str, List[str]] = {
    'soccer': [
        'soccer', 'football', 'fifa', 'premier league', 'la liga',
        'bundesliga', 'serie a', 'ligue 1', 'champions league',
        'europa league', 'mls', 'liga mx', 'eredivisie', 'superliga',
    ],
    'basketball': ['basketball', 'nba', 'wnba', 'euroleague', 'ncaa basketball'],
    'american_football': ['nfl', 'american football', 'ncaa football', 'superbowl', 'super bowl'],
    'baseball': ['baseball', 'mlb'],
    'field_hockey': ['field hockey'],
    'hockey': ['ice hockey', 'hockey', 'nhl', 'stanley cup'],
    'tennis': ['tennis', 'atp', 'wta', 'wimbledon', 'us open', 'roland garros', 'australian open'],
    'boxing': ['boxing', 'wbc', 'wba', 'ibf', 'wbo'],
    'mma': ['ufc', 'mma', 'bellator', 'one fc', 'pfl'],
    'racing': ['f1', 'formula 1', 'formula one', 'nascar', 'motogp', 'indycar', 'rally'],
    'cricket': ['cricket', 'ipl', 'test match', 'odi', 't20'],
    'rugby': ['rugby', 'six nations', 'super rugby', 'rugby league', 'rugby union'],
    'golf': ['golf', 'pga', 'masters', 'open championship', 'ryder cup'],
    'cycling': ['cycling', 'tour de france', 'vuelta', 'giro'],
    'wrestling': ['wwe', 'wrestling', 'aew'],
}

# Built-in league keyword map: display name → list of keywords to match
_DEFAULT_LEAGUE_KEYWORDS: Dict[str, List[str]] = {
    'Premier League': ['premier league', 'epl'],
    'Champions League': ['champions league', 'ucl'],
    'Europa League': ['europa league', 'uel'],
    'La Liga': ['la liga'],
    'Bundesliga': ['bundesliga'],
    'Serie A': ['serie a'],
    'Ligue 1': ['ligue 1'],
    'MLS': ['mls'],
    'Liga MX': ['liga mx'],
    'NBA': ['nba'],
    'NFL': ['nfl'],
    'NHL': ['nhl'],
    'AHL': ['american hockey league', ' ahl '],
    'OHL': ['ontario hockey league', ' ohl '],
    'QMJHL': ['qmjhl', 'quebec hockey league', 'quebec junior hockey league', 'quebec major junior'],
    'WHL': ['western hockey league', ' whl '],
    'SHL': ['svensk hockey', ' shl '],
    'Hockey Ettan': ['hockey ettan'],
    'ECHL': [' echl '],
    'KHL': [' khl '],
    'Liiga': ['sm-liiga', 'liiga'],
    'DEL': [' del ', 'deutsche eishockey liga'],
    'Stanley Cup': ['stanley cup'],
    'MLB': ['mlb'],
    'UFC': ['ufc'],
    'Formula 1': ['formula 1', 'formula one', 'f1 '],
    'ATP': ['atp tour'],
    'WTA': ['wta tour'],
    'Wimbledon': ['wimbledon'],
    'US Open (Tennis)': ['us open tennis'],
    'IPL': ['ipl'],
    'Six Nations': ['six nations'],
    'Super Rugby': ['super rugby'],
    'WWE': ['wwe'],
}

_VS_PATTERN = re.compile(r'\s+(?:vs\.?|v\.?)\s+', re.IGNORECASE)
_TRAILING_JUNK = re.compile(r'[\[\(].*$')  # Strip trailing "[EVENT]", "(HD)", etc.

# Bundled definitions file — shipped with the app, checked into git.
_BUNDLED_DEFINITIONS = Path(__file__).parent.parent / 'data' / 'sports_definitions.yaml'


def get_user_definitions_path(config=None) -> Path:
    """Return path to the user's personal definitions override file.

    This file is created ONLY by the settings UI when the user explicitly
    customises definitions. It should never be auto-created by the code.
    """
    if config is not None:
        return Path(config.config_dir) / 'sports_definitions.yaml'
    return Path.home() / '.config' / 'metatv' / 'sports_definitions.yaml'


def _load_definitions_file(path: Path) -> Tuple[Dict, Dict]:
    """Read a definitions YAML and return (sport_keywords, league_keywords)."""
    with open(path) as f:
        data = yaml.safe_load(f) or {}
    return data.get('sport_keywords') or {}, data.get('league_keywords') or {}


def load_sports_definitions(config=None) -> Tuple[Dict[str, List[str]], Dict[str, List[str]]]:
    """Load sport and league keyword maps.

    Always reads from the bundled ``metatv/data/sports_definitions.yaml`` as the
    base. If the user has a personal override file at
    ``~/.config/metatv/sports_definitions.yaml`` (written by the settings UI),
    those entries are merged on top — new sports/leagues are added, existing
    keyword lists are extended.

    The user override file is never auto-created by this function.

    Args:
        config: Application Config object (optional). Used only to locate the
                user's config directory.

    Returns:
        Tuple of (sport_keywords, league_keywords) dicts.
    """
    # Load bundled defaults
    try:
        sport_kw, league_kw = _load_definitions_file(_BUNDLED_DEFINITIONS)
    except Exception as e:
        logger.warning(f"Failed to read bundled sports definitions: {e} — using in-memory defaults")
        sport_kw = {k: list(v) for k, v in _DEFAULT_SPORT_KEYWORDS.items()}
        league_kw = {k: list(v) for k, v in _DEFAULT_LEAGUE_KEYWORDS.items()}

    # Merge user overrides if the settings UI has created them
    user_path = get_user_definitions_path(config)
    if user_path.exists():
        try:
            user_sports, user_leagues = _load_definitions_file(user_path)
            for sport, keywords in user_sports.items():
                existing = set(sport_kw.get(sport, []))
                sport_kw.setdefault(sport, []).extend(k for k in keywords if k not in existing)
            for league, keywords in user_leagues.items():
                existing = set(league_kw.get(league, []))
                league_kw.setdefault(league, []).extend(k for k in keywords if k not in existing)
            logger.debug(f"Merged user sports definitions from {user_path}")
        except Exception as e:
            logger.warning(f"Failed to read user sports definitions ({user_path}): {e}")

    return sport_kw, league_kw


def parse_sports_channel(channel: ChannelDB, config=None) -> Dict[str, Any]:
    """Extract sport_type, league_name, and team_name from a sports channel.

    Channels that do not match any keyword are assigned sport_type='unknown'
    so they remain visible in the Sports view rather than being silently excluded.

    Args:
        channel: The channel to parse.
        config: Optional Config for user-customized keyword maps.

    Returns:
        Dict with keys: sport_type (str), league_name (str|None), team_name (str|None).
    """
    result: Dict[str, Any] = {
        'sport_type': 'unknown',
        'league_name': None,
        'team_name': None,
    }

    sport_kw, league_kw = load_sports_definitions(config)

    name = channel.name or ''
    category = (channel.category or '').lstrip('#').strip()
    name_lower = name.lower()
    category_lower = category.lower()

    # --- Sport detection (first match wins) ---
    for sport, keywords in sport_kw.items():
        if any(kw in name_lower or kw in category_lower for kw in keywords):
            result['sport_type'] = sport
            break

    # --- League detection ---
    for league_name, keywords in league_kw.items():
        if any(kw in name_lower or kw in category_lower for kw in keywords):
            result['league_name'] = league_name
            break

    # --- Team extraction via "vs" / "v" pattern ---
    # Split on " | " (with surrounding spaces) to get pipe-delimited segments,
    # then scan from the end for a segment containing a "vs" matchup. This
    # correctly handles names like "EN | NHL | Panthers vs Bruins" where
    # the matchup is always in the last meaningful segment.
    segments = [s.strip() for s in name.split(' | ')]
    for segment in reversed(segments):
        vs_match = _VS_PATTERN.search(segment)
        if vs_match:
            left = segment[:vs_match.start()].strip()
            right = segment[vs_match.end():].strip()
            # Strip trailing tags like "[EVENT]", "(HD)"
            right = _TRAILING_JUNK.sub('', right).strip()
            if left and right:
                result['team_name'] = f"{left} vs {right}"
            break

    return result


def detect_ppv_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a PPV event
    
    PPV Pattern: Contains date/time in channel name + "PPV" keyword
    Example: "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K EXCLUSIVE | US: SOCCER PPV 1"
    """
    name = channel.name.lower()
    
    # Must have "ppv" keyword
    if 'ppv' not in name:
        return False
    
    # Must have date pattern (DD-MM-YYYY or MM-DD-YYYY)
    date_pattern = r'\d{2}-\d{2}-\d{4}'
    if not re.search(date_pattern, channel.name):
        return False
    
    # Filter out organizational headers (no stream_url)
    if not channel.stream_url:
        return False
    
    return True


def detect_live_event_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a live event
    
    Live Event Pattern: [EVENT] or [LIVE-EVENT] tag in channel name
    Example: "4K| SKY SPORTS UHD [EVENT]"
    """
    name = channel.name.lower()
    
    # Check for event tags
    if '[event]' in name or '[live-event]' in name:
        return True
    
    return False


def detect_sports_channel(channel: ChannelDB) -> bool:
    """Detect if channel is a sports channel
    
    Sports Pattern: Contains sports keywords in name or category
    """
    name = channel.name.lower()
    category = (channel.category or "").lstrip('#').strip().lower()
    
    sports_keywords = [
        'sport', 'football', 'soccer', 'nba', 'nfl', 'nhl', 'mlb',
        'boxing', 'ufc', 'fight', 'racing', 'cricket', 'tennis',
        'rugby', 'hockey', 'basketball', 'baseball', 'f1', 'moto',
        'premier league', 'champions league', 'la liga', 'bundesliga',
        'espn', 'sky sports', 'bein', 'tsn', 'fox sports', 'nbc sports',
    ]
    
    return any(kw in name or kw in category for kw in sports_keywords)


def parse_ppv_event(channel: ChannelDB) -> Dict[str, Any]:
    """Parse PPV event details from channel name
    
    Example: "End | Rolling Loud | all | 11-05-2026 | 09:37 (GMT) | 8K EXCLUSIVE | US: SOCCER PPV 1"
    
    Returns:
        dict with keys: event_name, start_time, quality, sport_type, stream_number
    """
    result = {
        'event_name': None,
        'start_time': None,
        'quality': None,
        'sport_type': None,
        'stream_number': None,
    }
    
    parts = channel.name.split('|')
    
    # Extract event name (usually second part after status)
    if len(parts) >= 2:
        event_name = parts[1].strip()
        if event_name and event_name.lower() not in ['all', 'end', 'live']:
            result['event_name'] = event_name
    
    # Extract date and time
    date_match = re.search(r'(\d{2})-(\d{2})-(\d{4})', channel.name)
    time_match = re.search(r'(\d{2}):(\d{2})', channel.name)
    
    if date_match and time_match:
        try:
            # Parse date (DD-MM-YYYY format)
            day, month, year = date_match.groups()
            hour, minute = time_match.groups()
            
            # Create datetime object
            result['start_time'] = datetime(
                int(year), int(month), int(day),
                int(hour), int(minute)
            )
        except (ValueError, IndexError) as e:
            logger.debug(f"Failed to parse PPV date/time from {channel.name}: {e}")
    
    # Extract quality markers
    name_upper = channel.name.upper()
    if '8K' in name_upper:
        result['quality'] = '8K'
    elif '4K' in name_upper or 'UHD' in name_upper:
        result['quality'] = '4K'
    elif 'FHD' in name_upper or '1080' in name_upper:
        result['quality'] = 'FHD'
    elif 'HD' in name_upper or '720' in name_upper:
        result['quality'] = 'HD'
    
    # Extract sport type from channel name
    name_lower = channel.name.lower()
    sport_keywords = {
        'soccer': ['soccer', 'football', 'fifa'],
        'basketball': ['basketball', 'nba'],
        'football': ['nfl', 'american football'],
        'boxing': ['boxing', 'fight'],
        'mma': ['ufc', 'mma', 'bellator'],
        'racing': ['f1', 'formula', 'racing', 'nascar'],
        'hockey': ['hockey', 'nhl'],
        'baseball': ['baseball', 'mlb'],
    }
    
    for sport, keywords in sport_keywords.items():
        if any(kw in name_lower for kw in keywords):
            result['sport_type'] = sport
            break
    
    # Extract stream number (e.g., "PPV 1", "PPV 2")
    stream_match = re.search(r'PPV\s+(\d+)', channel.name, re.IGNORECASE)
    if stream_match:
        result['stream_number'] = int(stream_match.group(1))
    
    return result


def detect_and_categorize_channel(channel: ChannelDB) -> Optional[str]:
    """Detect and categorize channel into special views

    Priority:
        1. PPV (has date/time + PPV keyword)
        2. Live Event (has [EVENT] tag)
        3. Sports (has sports keywords)

    Returns:
        'ppv', 'live_event', 'sports', or None
    """
    # TREX-style organizational headers start with '#' — not actual channels
    if channel.name and channel.name.startswith('#'):
        return None

    # Priority 1: PPV
    if detect_ppv_channel(channel):
        return 'ppv'
    
    # Priority 2: Live Events
    if detect_live_event_channel(channel):
        return 'live_event'
    
    # Priority 3: Sports
    if detect_sports_channel(channel):
        return 'sports'
    
    return None


def update_channel_special_content(channel: ChannelDB, config=None) -> bool:
    """Update channel with special content categorization.

    Args:
        channel: Channel to categorize and enrich.
        config: Optional Config for user-customized keyword maps.

    Returns:
        True if channel was categorized, False otherwise.
    """
    special_view = detect_and_categorize_channel(channel)

    if not special_view:
        return False

    channel.special_view = special_view

    if special_view == 'ppv':
        ppv_data = parse_ppv_event(channel)
        channel.event_start_time = ppv_data['start_time']
        channel.sport_type = ppv_data['sport_type']

        # Manual JSON serialization per CLAUDE.md SQLite compat rule
        import json
        metadata = ppv_data.copy()
        if metadata['start_time']:
            metadata['start_time'] = metadata['start_time'].isoformat()
        channel.event_metadata = json.dumps(metadata)

    elif special_view == 'sports':
        sports_data = parse_sports_channel(channel, config)
        channel.sport_type = sports_data['sport_type']
        channel.league_name = sports_data['league_name']
        channel.team_name = sports_data['team_name']

    return True
