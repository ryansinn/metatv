# Filtering System Design

## Philosophy

**Filter where it adds value, skip where it doesn't.**

Prefix/language filtering is useful for **browsing the channel list**, not for **viewing episodes within a series**.

---

## Filtering Hierarchy

### Level 1: Channel List (Main View)
**What you're filtering**: 200,000+ channels (series, movies, live streams)  
**Filters available**:
- Media Type (Movies, Series, Live)
- Language/Region groups (EN, AR, ES, FR, etc.)
- Quality (4K, HD, SD)
- Platform (Netflix, HBO, etc.)
- Search text

**Why this works**: Large dataset, need to narrow down before exploring.

### Level 2: Series Detail (Episode Tree)
**What you're filtering**: 50-200 episodes of one series  
**Filters available**:
- ~~Prefix/Language~~ (inherited from parent, not useful here)
- Watched/Unwatched toggle
- Search within episodes (future)

**Why this works**: Small dataset, already language-filtered by parent selection.

### Level 3: Live Channels
**What you're filtering**: Streams with inconsistent naming  
**Filters available**:
- Media Type indicator (redundant if already in Live tab)
- Search text
- ~~Complex prefix detection~~ (too unreliable)

**Why this works**: Live channels are browsed more by name/category than language.

---

## Prefix Detection Strategy

### Simple Heuristic (Good Enough)

```python
def extract_prefix(channel_name: str) -> Optional[str]:
    """Extract prefix from channel name
    
    Strategy: Take everything before first ' - '
    Only return if it looks like a prefix (short, has uppercase)
    
    Examples:
        "EN - Breaking Bad" → "EN"
        "AR - Drama" → "AR"
        "UK/US - The Office" → "UK/US"
        "4K - Movie" → "4K"
        "Breaking Bad - S01E01" → None (no clear prefix)
    """
    if ' - ' not in channel_name:
        return None
    
    first_segment = channel_name.split(' - ', 1)[0].strip()
    
    # Heuristic: prefix should be short and have some uppercase
    if len(first_segment) <= 20 and any(c.isupper() for c in first_segment):
        return first_segment
    
    return None
```

**Rationale**: 
- Simple, fast, good enough for 80% of cases
- Handles most IPTV naming conventions
- Doesn't try to be perfect (impossible with inconsistent data)
- Easy to understand and debug

---

## Category Mapping

Group related prefixes into user-friendly categories:

**Key Insight**: These mappings serve as the **standardization layer** across multiple providers.

When you have multiple providers (TREX, M3U, Jellyfin, etc.), each might use different prefixes:
- Provider A: "EN - Breaking Bad"
- Provider B: "UK - Breaking Bad"  
- Provider C: "US - Breaking Bad"

All three map to the "English" language group, so filtering for "English" shows content from all providers consistently.

```python
LANGUAGE_GROUPS = {
    'English': ['EN', 'UK', 'US', 'AU', 'CA', 'NZ', 'IE'],
    'Arabic': ['AR', 'AE', 'SA', 'EG', 'MA', 'TN', 'DZ', 'LB', 'JO'],
    'Spanish': ['ES', 'MX', 'AR', 'CO', 'CL', 'PE', 'VE'],
    'French': ['FR', 'BE', 'CH', 'CA', 'LU'],
    'German': ['DE', 'AT', 'CH'],
    'Italian': ['IT', 'CH'],
    # ... more groups
}

QUALITY_GROUPS = {
    '4K / UHD': ['4K', 'UHD', '8K'],
    'HD': ['HD', 'FHD', 'HDR', 'HDR10'],
    'SD': ['SD'],
}

PLATFORM_GROUPS = {
    'Streaming': ['NETFLIX', 'HBO', 'HULU', 'DISNEY', 'AMAZON', 'PRIME'],
    'Sports': ['ESPN', 'DAZN', 'PPV', 'NBA', 'NFL'],
    'News': ['CNN', 'BBC', 'FOX', 'NBC', 'CBS'],
}
```

---

## UI Design

### Filter Bar Layout

```
┌─ Main Window ────────────────────────────────────────────────┐
│  [← Back]   Channels                                          │
├───────────────────────────────────────────────────────────────┤
│  Search: [_________________________________] [x]               │
│                                                               │
│  Media: [Live ●] [Movies ●] [Series ●]                        │
│  Filters: [Languages ▼] [Quality ▼] [Platforms ▼]            │
│           Showing 125,482 of 240,000 · 114,518 filtered out  │
│           [Show Excluded]  [Clear Filters]                    │
│                                                               │
├───────────────────────────────────────────────────────────────┤
│  ┌─ Channels ──────────────────────────┬─ Info ─────┐        │
│  │ EN - Breaking Bad (2008)            │ Series     │        │
│  │ AR - مسلسل درامي                    │ Series     │        │
│  │ 4K - Planet Earth II                │ Movie      │        │
│  └─────────────────────────────────────┴────────────┘        │
└───────────────────────────────────────────────────────────────┘
```

**UI Elements**:

1. **Media Type Toggle Chips**: `[Live ●] [Movies ●] [Series ●]`
   - Simple on/off toggle (● = included, ○ = excluded)
   - All enabled by default (include everything)
   - Click to toggle individual types
   - Multiple can be active simultaneously

2. **Complex Filter Dropdowns**: `[Languages ▼] [Quality ▼] [Platforms ▼]`
   - Multi-select checkboxes within dropdown
   - Include-by-default philosophy (all checked initially)
   - Show count per group
   - Support invert mode via "Show Excluded" button

3. **Filter Stats**: `Showing X of Y · Z filtered out`
   - Always visible for transparency
   - Updates in real-time as filters change
   - Helps users understand scope

4. **Show Excluded Button**: Temporary view of filtered-out content
   - Inverts language/quality/platform filters only
   - Does NOT invert media type toggles
   - Populates main results list with excluded items
   - Button label changes to "Show Included" when active
   - Allows search within excluded results (future enhancement)
   - **Future**: Make excluded results searchable for large datasets

### Language Filter Dropdown

```
[Languages ▼] (clicked, dropdown appears)
╔═══════════════════════════════════════╗
║  Languages                      [x]   ║
╟───────────────────────────────────────╢
║  ☑ English (EN, UK, US...)  ─ 45,234 ║
║  ☐ Arabic (AR, AE, SA...)   ─ 23,156 ║
║  ☐ Spanish (ES, MX...)      ─ 12,445 ║
║  ☐ French (FR, CA, BE)      ─  8,901 ║
║  ☐ German (DE, AT, CH)      ─  5,678 ║
║  ☐ Italian (IT)             ─  3,456 ║
║  ───────────────────────────────────  ║
║  ☐ Other Languages          ─  7,890 ║
║                                       ║
║  [Select All] [Clear]                 ║
╚═══════════════════════════════════════╝
```

**Interaction**:
- Checkboxes (multi-select, all checked by default)
- Shows count per language group
- Multiple can be checked simultaneously
- "Other" catches unmapped prefixes
- Unchecking excludes that language group from results
- Can be temporarily inverted via "Show Excluded" button

---

## Database Schema

### No New Tables Needed

```sql
-- Store detected prefix in existing ChannelDB
ALTER TABLE channels ADD COLUMN detected_prefix TEXT;

-- Create index for fast filtering
CREATE INDEX idx_channels_prefix ON channels(detected_prefix);
```

### Filter State Storage

```yaml
# Store in config.yaml
filters:
  language_groups:
    - English
    - Arabic
  quality_groups:
    - 4K / UHD
  platform_groups: []
  media_types:
    - movies
    - series
    # live excluded
```

---

## Implementation Steps

1. **Prefix Detection** (one-time per provider refresh)
   - Run `extract_prefix()` on all channels
   - Store in `ChannelDB.detected_prefix`
   - Group by category for counts

2. **Filter UI** (PyQt6 widgets)
   - Add filter bar above channel list
   - Implement checkable dropdown menus
   - Show item counts per group

3. **Filtering Logic** (repository layer)
   - Extend `ChannelRepository.get_all()` with filter params
   - Use indexed queries for performance
   - Combine with existing search

4. **Skip Episode Filtering**
   - Don't show prefix in episode tree
   - Don't filter episodes by prefix (use parent)

---

## Performance Considerations

### Database Query Optimization

```sql
-- Efficient filtering with multiple languages
SELECT * FROM channels 
WHERE 
  detected_prefix IN ('EN', 'UK', 'US', 'AU', 'CA')
  AND media_type = 'series'
  AND name LIKE '%Breaking%'
  AND is_hidden = 0
LIMIT 1000;
```

**Expected Performance**: <50ms for 200k channels with proper indexes

### In-Memory Caching

```python
# Cache prefix groups and counts (updated on provider refresh)
@dataclass
class PrefixStats:
    all_prefixes: Set[str]
    language_groups: Dict[str, int]  # group_name -> count
    quality_groups: Dict[str, int]
    platform_groups: Dict[str, int]
    unmapped: Set[str]
```

---

## Decision: Simplicity Over Perfection

**What we're NOT doing**:
- ❌ Machine learning for language detection
- ❌ Complex multi-token parsing
- ❌ Tri-state filtering (unnecessary complexity)
- ❌ Episode-level prefix filtering
- ❌ Live channel special handling

**What we ARE doing**:
- ✅ Simple "first segment" extraction
- ✅ Grouped checkboxes (English, Arabic, Spanish...)
- ✅ Toggle chips for media types (Live/Movies/Series)
- ✅ Include-by-default philosophy (filter out, not filter in)
- ✅ Show excluded content with temporary invert button
- ✅ Channel list filtering only
- ✅ Good enough for 80% of cases
- ✅ Fast, debuggable, maintainable

**Future Enhancements** (not in initial release):
- 🔮 Search within excluded results (for large filtered datasets)
- 🔮 Filter presets ("4K English Content", "Arabic Movies", etc.)
- 🔮 Smart filter suggestions based on content
- 🔮 Remember last filter state per provider
- 🔮 **Provider-level filtering**: Filter by source when multiple providers active
  - Add "Sources" dropdown in filter bar
  - Visual provider indicator in channel list (colored badge or icon)
  - Combined filters: "English content from Provider A only"
  - Useful when dealing with overlapping content from multiple sources

**Why**: IPTV data is inherently messy. A simple, forgiving approach that works "most of the time" is better than a complex system that tries to be perfect but fails unpredictably.

---

## Multi-Provider Standardization

The language/quality/platform group mappings in `config.yaml` serve as the **standardization layer**:

- Different providers may use different prefixes for the same language
- Example: "EN", "UK", "US" all map to "English" group
- When filtering for "English", you get matching content from ALL providers
- This prevents provider-specific inconsistencies from affecting the user experience

**Future Consideration**: When multiple providers are active, users may want:
1. See which provider each channel comes from (visual indicator)
2. Filter by specific provider ("Show only TREX content")
3. Compare same content across providers (quality, reliability)

This will be addressed in a future update with provider-level filtering.
