"""Special content detection and parsing for PPV, Live Events, and Sports"""

import re
from datetime import datetime
from typing import Optional, Dict, Any
from loguru import logger

from metatv.core.database import ChannelDB


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


def update_channel_special_content(channel: ChannelDB) -> bool:
    """Update channel with special content categorization
    
    Returns:
        True if channel was categorized, False otherwise
    """
    special_view = detect_and_categorize_channel(channel)
    
    if not special_view:
        return False
    
    channel.special_view = special_view
    
    # Parse additional metadata for PPV channels
    if special_view == 'ppv':
        ppv_data = parse_ppv_event(channel)
        channel.event_start_time = ppv_data['start_time']
        channel.sport_type = ppv_data['sport_type']
        
        # Convert datetime to ISO string for JSON storage
        metadata = ppv_data.copy()
        if metadata['start_time']:
            metadata['start_time'] = metadata['start_time'].isoformat()
        channel.event_metadata = metadata
    
    return True
