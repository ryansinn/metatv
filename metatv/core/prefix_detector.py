"""Robust prefix detection for IPTV channel names"""

import re
from typing import List, Set, Dict, Optional
from dataclasses import dataclass


@dataclass
class PrefixMatch:
    """A detected prefix with metadata"""
    text: str           # Raw prefix text (e.g., "EN", "4K")
    category: str       # Category: language, quality, platform, numeric, unknown
    position: int       # Character position in title
    confidence: float   # 0.0-1.0 confidence score


class PrefixDetector:
    """Extract prefixes from IPTV channel names using pattern matching"""
    
    # ISO 639-1 language codes (common ones)
    LANGUAGE_CODES = {
        'EN', 'AR', 'FR', 'DE', 'ES', 'IT', 'PT', 'RU', 'TR', 'NL', 
        'PL', 'UK', 'SE', 'NO', 'DK', 'FI', 'GR', 'HU', 'RO', 'BG',
        'HR', 'CS', 'SK', 'SL', 'SR', 'MK', 'AL', 'LV', 'LT', 'ET'
    }
    
    # Region codes
    REGION_CODES = {
        'US', 'UK', 'CA', 'AU', 'NZ', 'IE', 'ZA', 'IN', 'PK', 'BD',
        'AE', 'SA', 'EG', 'MA', 'TN', 'DZ', 'LB', 'JO', 'IQ', 'KW'
    }
    
    # Quality markers
    QUALITY_MARKERS = {
        '4K', '8K', 'UHD', 'FHD', 'HD', 'SD', 'HDR', 'HDR10',
        'DOLBY', 'ATMOS', 'DTS', '60FPS', '50FPS', 'HEVC', 'H264', 'H265',
        'HQ', 'LQ', 'LD', 'CAM', 'HDTS', 'CAMRIP', 'TSCAM',
    }
    
    # Platform/network markers
    PLATFORM_MARKERS = {
        'NETFLIX', 'HBO', 'HULU', 'DISNEY', 'AMAZON', 'PRIME', 'APPLE',
        'PEACOCK', 'PARAMOUNT', 'SHOWTIME', 'STARZ', 'ESPN', 'NBC', 'ABC',
        'CBS', 'FOX', 'CNN', 'BBC', 'SKY', 'DAZN', 'PPV'
    }
    
    # Separator patterns
    SEPARATORS = r'[\s\-_|/:]+'
    
    def __init__(self):
        # Build regex pattern for known prefixes
        all_known = (
            self.LANGUAGE_CODES | 
            self.REGION_CODES | 
            self.QUALITY_MARKERS | 
            self.PLATFORM_MARKERS
        )
        self.known_pattern = '|'.join(sorted(all_known, key=len, reverse=True))
    
    def extract_prefixes(self, title: str) -> List[PrefixMatch]:
        """Extract all prefixes from a title
        
        Strategy:
        1. Look for known codes/markers anywhere in title
        2. Check first segment before " - " for unknown prefixes
        3. Parse composite prefixes (e.g., "UK/EN", "4K HDR")
        4. Assign confidence scores based on position and pattern
        """
        prefixes = []
        
        # Strategy 1: Find all known codes (case-insensitive)
        for match in re.finditer(rf'\b({self.known_pattern})\b', title, re.IGNORECASE):
            prefix_text = match.group(1).upper()
            category = self._categorize(prefix_text)
            
            # Higher confidence if at start of title
            confidence = 0.9 if match.start() < 20 else 0.7
            
            prefixes.append(PrefixMatch(
                text=prefix_text,
                category=category,
                position=match.start(),
                confidence=confidence
            ))
        
        # Strategy 2: Check first segment before " - "
        first_segment = title.split(' - ')[0].strip()
        if first_segment and len(first_segment) <= 30:  # Reasonable prefix length
            # Parse composite prefixes like "UK/EN", "02/AR", "4K HDR"
            tokens = re.split(r'[/\s]+', first_segment)
            for token in tokens:
                token_upper = token.upper()
                
                # Skip if already found as known prefix
                if any(p.text == token_upper for p in prefixes):
                    continue
                
                # Numeric prefix (e.g., "02", "123")
                if re.match(r'^\d{1,4}$', token):
                    prefixes.append(PrefixMatch(
                        text=token,
                        category='numeric',
                        position=title.index(token),
                        confidence=0.6
                    ))
                
                # Short uppercase token (likely a code)
                elif len(token) <= 5 and token.isupper():
                    prefixes.append(PrefixMatch(
                        text=token_upper,
                        category='unknown',
                        position=title.index(token),
                        confidence=0.5
                    ))
        
        # Sort by position (prefixes at start are more significant)
        return sorted(prefixes, key=lambda p: p.position)
    
    def _categorize(self, prefix: str) -> str:
        """Categorize a prefix"""
        prefix_upper = prefix.upper()
        if prefix_upper in self.LANGUAGE_CODES:
            return 'language'
        if prefix_upper in self.REGION_CODES:
            return 'region'
        if prefix_upper in self.QUALITY_MARKERS:
            return 'quality'
        if prefix_upper in self.PLATFORM_MARKERS:
            return 'platform'
        return 'unknown'
    
    def get_primary_prefix(self, title: str) -> Optional[str]:
        """Get the most likely primary prefix (for simple filtering)"""
        prefixes = self.extract_prefixes(title)
        if not prefixes:
            return None
        
        # Prioritize: language > region > platform > quality > numeric > unknown
        priority_order = ['language', 'region', 'platform', 'quality', 'numeric', 'unknown']
        
        for category in priority_order:
            matches = [p for p in prefixes if p.category == category]
            if matches:
                # Return highest confidence match in this category
                return max(matches, key=lambda p: p.confidence).text
        
        return prefixes[0].text  # Fallback to first detected
    
    def get_all_prefixes(self, title: str) -> Set[str]:
        """Get all detected prefixes as a set (for multi-filter)"""
        return {p.text for p in self.extract_prefixes(title)}
    
    def build_prefix_index(self, channels: List) -> Dict[str, Set[str]]:
        """Build an inverted index: prefix -> set of channel IDs
        
        This enables O(1) filtering by prefix.
        """
        index = {}
        for channel in channels:
            prefixes = self.get_all_prefixes(channel.name)
            for prefix in prefixes:
                if prefix not in index:
                    index[prefix] = set()
                index[prefix].add(channel.id)
        return index


# Example usage
if __name__ == "__main__":
    detector = PrefixDetector()
    
    test_titles = [
        "EN - Breaking Bad",
        "AR - خليجي - Drama Show",
        "02/EN - Action Movie",
        "UK/US - The Office",
        "4K HDR - Planet Earth II",
        "NETFLIX - Stranger Things",
        "Breaking Bad - S01E01 - Pilot",
        "Star Trek: The Next Generation",
        "ESPN US - NBA Live",
    ]
    
    for title in test_titles:
        prefixes = detector.extract_prefixes(title)
        primary = detector.get_primary_prefix(title)
        print(f"\n{title}")
        print(f"  Primary: {primary}")
        print(f"  All: {[f'{p.text}({p.category})' for p in prefixes]}")
