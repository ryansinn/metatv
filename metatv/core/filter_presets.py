"""Provider-specific filter presets"""

import re
from typing import List, Dict, Callable
from dataclasses import dataclass


@dataclass
class FilterRule:
    """A single filter rule"""
    name: str
    description: str
    pattern: str  # Regex pattern
    is_category_header: bool = False  # If true, this is a category marker, not actual content
    

@dataclass
class FilterPreset:
    """A collection of filter rules for a provider"""
    provider_name: str
    description: str
    rules: List[FilterRule]
    category_detector: Callable[[str], bool] = None  # Function to detect category headers
    

# TREX Provider Preset
TREX_PRESET = FilterPreset(
    provider_name="TREX",
    description="TreX Shared provider filter preset",
    rules=[
        # Primary content type filters (top-level organization)
        FilterRule(
            name="Livestream",
            description="Live TV and perpetually streaming content",
            pattern=r"^(?!.*VOD)(?!.*Series)(?!.*Movie)",  # Match if not VOD
            is_category_header=False
        ),
        FilterRule(
            name="Series",
            description="TV series and show episodes (VOD)",
            pattern=r"Series|TV\s?Series|Shows?|Episodes?",
            is_category_header=False
        ),
        FilterRule(
            name="Movies",
            description="Movies and films (VOD)",
            pattern=r"Movies?|Films?|Cinema",
            is_category_header=False
        ),
        
        # Category headers (to hide or use for organization)
        FilterRule(
            name="Category Headers",
            description="Lines starting with ## are category separators",
            pattern=r"^#{2,5}\s.*\s#{2,5}$",
            is_category_header=True
        ),
        
        # Quality filters
        FilterRule(
            name="4K/UHD",
            description="4K and UHD quality channels",
            pattern=r"4K|UHD|3840P|2160P"
        ),
        FilterRule(
            name="HD",
            description="HD quality channels",
            pattern=r"\bHD\b|ᴴᴰ|1080P"
        ),
        FilterRule(
            name="RAW",
            description="Raw/uncompressed streams",
            pattern=r"\bRAW\b|ᴿᴬᵂ"
        ),
        FilterRule(
            name="60fps",
            description="60fps streams",
            pattern=r"60\s?FPS|⁶⁰ᶠᵖˢ"
        ),
        
        # Content type filters (sub-categories)
        FilterRule(
            name="24/7 Streams",
            description="24/7 streaming channels",
            pattern=r"24\s?/\s?7"
        ),
        FilterRule(
            name="PPV",
            description="Pay-per-view events",
            pattern=r"\bPPV\b"
        ),
        FilterRule(
            name="Sports",
            description="Sports channels and events",
            pattern=r"SPORT|ESPN|DAZN|LIGA|FOOTBALL|SOCCER|F1|FORMULA|PREMIER\s?LEAGUE"
        ),
        FilterRule(
            name="Kids",
            description="Children's content",
            pattern=r"\bKIDS?\b|BAMBINI|DISNEY|CARTOON|NICKELODEON"
        ),
        FilterRule(
            name="News",
            description="News channels",
            pattern=r"\bNEWS\b|CNN|BBC|FOX\s?NEWS|MSNBC"
        ),
        
        # Platform/Service filters
        FilterRule(
            name="Netflix",
            description="Netflix content",
            pattern=r"NETFLIX"
        ),
        FilterRule(
            name="Prime Video",
            description="Amazon Prime Video",
            pattern=r"PRIME\s?VIDEO"
        ),
        FilterRule(
            name="Disney+",
            description="Disney Plus content",
            pattern=r"DISNEY\+?"
        ),
        FilterRule(
            name="DAZN",
            description="DAZN sports",
            pattern=r"\bDAZN\b"
        ),
        FilterRule(
            name="Canal+",
            description="Canal Plus channels",
            pattern=r"CANAL\s?\+"
        ),
    ],
    category_detector=lambda name: bool(re.search(r"^#{2,5}\s.*\s#{2,5}$", name))
)


# Generic preset for other providers
GENERIC_PRESET = FilterPreset(
    provider_name="Generic",
    description="Generic IPTV provider filters",
    rules=[
        FilterRule(
            name="HD Quality",
            description="HD channels",
            pattern=r"\bHD\b|1080"
        ),
        FilterRule(
            name="4K Quality",
            description="4K channels",
            pattern=r"4K|UHD|2160"
        ),
        FilterRule(
            name="Sports",
            description="Sports channels",
            pattern=r"SPORT|ESPN|FOX\s?SPORTS"
        ),
        FilterRule(
            name="Movies",
            description="Movie channels",
            pattern=r"MOVIE|CINEMA|FILM|HBO"
        ),
        FilterRule(
            name="News",
            description="News channels",
            pattern=r"\bNEWS\b|CNN|BBC\s?NEWS|FOX\s?NEWS"
        ),
        FilterRule(
            name="Kids",
            description="Kids channels",
            pattern=r"KIDS?|CARTOON|NICK|DISNEY"
        ),
    ],
    category_detector=None
)


class FilterPresetManager:
    """Manages filter presets"""
    
    def __init__(self):
        self.presets: Dict[str, FilterPreset] = {
            "TREX": TREX_PRESET,
            "Generic": GENERIC_PRESET,
        }
    
    def get_preset(self, provider_name: str) -> FilterPreset:
        """Get preset for provider, fallback to generic"""
        # Try exact match
        if provider_name in self.presets:
            return self.presets[provider_name]
        
        # Try case-insensitive match
        for name, preset in self.presets.items():
            if name.lower() == provider_name.lower():
                return preset
        
        # Fallback to generic
        return self.presets["Generic"]
    
    def add_preset(self, preset: FilterPreset):
        """Add a custom preset"""
        self.presets[preset.provider_name] = preset
    
    def get_available_presets(self) -> List[str]:
        """Get list of available preset names"""
        return list(self.presets.keys())
    
    def apply_filter(self, channels: List, preset_name: str, rule_name: str) -> List:
        """Apply a specific filter rule to channels"""
        preset = self.get_preset(preset_name)
        
        # Find the rule
        rule = None
        for r in preset.rules:
            if r.name == rule_name:
                rule = r
                break
        
        if not rule:
            return channels
        
        # Special handling for primary content type filters (use media_type field)
        if rule_name in ["Livestream", "Series", "Movies"]:
            media_type_map = {
                "Livestream": "live",
                "Series": "series",
                "Movies": "movie"
            }
            target_type = media_type_map.get(rule_name)
            
            filtered = []
            for channel in channels:
                # Get media_type from channel
                if hasattr(channel, 'media_type'):
                    media_type = channel.media_type
                elif isinstance(channel, tuple) and len(channel) > 1 and hasattr(channel[1], 'media_type'):
                    media_type = channel[1].media_type
                else:
                    continue
                
                if media_type == target_type:
                    filtered.append(channel)
            
            return filtered
        
        # Apply regex pattern filter for other rules
        pattern = re.compile(rule.pattern, re.IGNORECASE)
        filtered = []
        
        for channel in channels:
            # Get channel name (handle both DB objects and tuples)
            if hasattr(channel, 'name'):
                name = channel.name
            elif isinstance(channel, tuple):
                name = channel[0]  # Assume (name, channel_obj) tuple
            else:
                continue
            
            if pattern.search(name):
                filtered.append(channel)
        
        return filtered
    
    def is_category_header(self, channel_name: str, preset_name: str) -> bool:
        """Check if a channel name is actually a category header"""
        preset = self.get_preset(preset_name)
        
        if preset.category_detector:
            return preset.category_detector(channel_name)
        
        return False
    
    def get_category_from_name(self, channel_name: str, preset_name: str) -> str:
        """Extract category from channel name based on provider patterns"""
        preset = self.get_preset(preset_name)
        
        if preset_name == "TREX":
            # For TREX, extract content between hashes
            match = re.search(r"^#{2,5}\s+(.+?)\s+#{2,5}$", channel_name)
            if match:
                return match.group(1).strip()
        
        return None
