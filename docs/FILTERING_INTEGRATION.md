"""Integration guide for the filtering system

This document explains how to integrate the new filtering system into MainWindow.

## Quick Start

### 1. Add FilterBar to MainWindow

```python
from metatv.gui.filter_bar import FilterBar

class MainWindow(QMainWindow):
    def __init__(self):
        # ... existing init code ...
        
        # Create filter bar
        self.filter_bar = FilterBar(self.config)
        self.filter_bar.filter_changed.connect(self.on_filter_changed)
        
        # Add to layout (above channel list)
        self.content_layout.insertWidget(0, self.filter_bar)
```

### 2. Update Channels on Filter Change

```python
def on_filter_changed(self):
    """Handle filter changes and refresh channel list"""
    filter_state = self.filter_bar.get_filter_state()
    
    # Convert language/quality/platform groups to prefix lists
    language_prefixes = []
    for group_name in filter_state['language_groups']:
        prefixes = self.config.filter_language_groups.get(group_name, [])
        language_prefixes.extend(prefixes)
    
    quality_prefixes = []
    for group_name in filter_state['quality_groups']:
        prefixes = self.config.filter_quality_groups.get(group_name, [])
        quality_prefixes.extend(prefixes)
    
    platform_prefixes = []
    for group_name in filter_state['platform_groups']:
        prefixes = self.config.filter_platform_groups.get(group_name, [])
        platform_prefixes.extend(prefixes)
    
    # Get filtered channels from repository
    channels = self.repos.channels.get_all(
        provider_id=self.current_provider_id,
        media_types=filter_state['media_types'],
        language_prefixes=language_prefixes or None,
        quality_prefixes=quality_prefixes or None,
        platform_prefixes=platform_prefixes or None,
        invert_prefix_filters=filter_state['show_excluded']
    )
    
    # Update UI
    self.populate_channel_list(channels)
    
    # Update filter stats
    total = self.repos.channels.count(provider_id=self.current_provider_id)
    shown = len(channels)
    filtered = total - shown
    self.filter_bar.update_stats(shown, total, filtered)
```

### 3. Initialize Filter Groups on Provider Refresh

```python
def on_provider_refresh_complete(self, provider_id: str):
    """Called when provider data is refreshed"""
    # Update detected prefixes for all channels
    self.repos.channels.update_detected_prefixes(provider_id=provider_id)
    
    # Get prefix statistics
    stats = self.repos.channels.get_prefix_stats(
        provider_id=provider_id,
        language_groups=self.config.filter_language_groups,
        quality_groups=self.config.filter_quality_groups,
        platform_groups=self.config.filter_platform_groups
    )
    
    # Update filter bar with current counts
    self.filter_bar.update_filter_groups(
        language_groups=stats['language_groups'],
        quality_groups=stats['quality_groups'],
        platform_groups=stats['platform_groups']
    )
    
    # Refresh channel list with current filters
    self.on_filter_changed()
```

### 4. Run Database Migration

Before first use, run the migration to add the `detected_prefix` column:

```bash
python -m metatv.core.migrations.001_add_detected_prefix
```

Or add to your startup code:

```python
from metatv.core.migrations.001_add_detected_prefix import migrate

# On application startup
try:
    migrate()
except Exception as e:
    logger.error(f"Migration failed: {e}")
```

## Configuration

The filter system uses these config settings:

```yaml
# config.yaml
filters_enabled: true
filter_default_mode: include_all
filter_media_types:
  - live
  - movies
  - series
filter_language_groups:
  English: [EN, UK, US, AU, CA, NZ, IE]
  Arabic: [AR, AE, SA, EG, MA, TN, DZ, LB, JO]
  Spanish: [ES, MX, AR, CO, CL, PE, VE]
  # ... more groups
filter_quality_groups:
  4K / UHD: [4K, UHD, 8K, 2160P]
  HD: [HD, FHD, 1080P, 720P, HDR]
  SD: [SD, 480P, 360P]
filter_platform_groups:
  Streaming: [NETFLIX, HBO, HULU, DISNEY+, PRIME]
  Sports: [ESPN, DAZN, NBA, NFL, UFC]
  News: [CNN, BBC, FOX, NBC, CBS]
```

## Features

### Toggle Chips
- Simple on/off for Live/Movies/Series
- Visual feedback with filled/unfilled circles
- Multiple can be active simultaneously

### Complex Filter Dropdowns
- Multi-select checkboxes for Language/Quality/Platform
- Show item counts per group
- Select All / Clear buttons
- Scrollable for long lists

### Show Excluded Button
- Temporarily inverts Language/Quality/Platform filters
- Does NOT invert media type toggles
- Button color changes when active
- Useful for seeing what's being filtered out

### Filter Stats
- Shows "Showing X of Y · Z filtered out"
- Updates in real-time
- Helps users understand filtering scope

### Clear Filters Button
- Resets everything to default (all enabled)
- Quick way to start over

## Performance

- Prefix detection runs once per provider refresh (~1-2 seconds for 200k channels)
- Database queries use indexes on `detected_prefix` and `media_type`
- Expected query time: <50ms for 200k channels
- Filter bar UI updates are instant (local state changes)

## Future Enhancements

See FILTERING_DESIGN.md for planned features:
- Search within excluded results
- Filter presets ("4K English Content", etc.)
- Smart filter suggestions
- Remember last filter state per provider
