# MetaTV Design Guidelines

## UI State Persistence

### Design Principle
**All UI sections MUST remember their position, size, and state (collapsed/expanded) between application sessions.**

This ensures a consistent user experience where users' layout preferences are preserved.

### Implementation Pattern

#### For Sidebar Sections
Sidebar sections inherit from `CollapsibleSection` and use a standard pattern:

1. **Section ID**: Each section has a unique identifier via `get_section_id()`
   ```python
   def get_section_id(self):
       return self.title.lower().replace(" ", "_")
   ```

2. **State Storage**: Section state is stored in `config.sidebar_section_states[section_id]`
   ```python
   config.sidebar_section_states = {
       "sources": {
           "collapsed": False,
           "height": 300
       },
       "favorites": {
           "collapsed": True,
           "height": 200
       }
   }
   ```

3. **Save State**: Call `save_state()` whenever state changes
   ```python
   def save_state(self):
       section_id = self.get_section_id()
       self.config.sidebar_section_states[section_id] = {
           'collapsed': self.is_collapsed,
           'height': self.height()
       }
       self.config.save()
   ```

4. **Restore State**: Call `restore_state()` during initialization
   ```python
   def restore_state(self):
       section_id = self.get_section_id()
       state = self.config.sidebar_section_states.get(section_id)
       if state:
           self.set_collapsed(state.get('collapsed', False), save=False)
           if not state.get('collapsed'):
               height = state.get('height')
               if height:
                   self.setMinimumHeight(height)
   ```

#### For Main Content Sections
Main content sections (like the filter bar) use direct config fields:

1. **Config Field**: Add a specific field for the section's state
   ```python
   # In Config class
   filter_section_visible: bool = True
   ```

2. **Save State**: Save immediately when state changes
   ```python
   def toggle_filters(self):
       self.filters_visible = not self.filters_visible
       self.config.filter_section_visible = self.filters_visible
       self.config.save()
   ```

3. **Restore State**: Read config during initialization
   ```python
   self.filters_visible = getattr(self.config, 'filter_section_visible', True)
   self.filter_bar.setVisible(self.filters_visible)
   ```

#### For Splitters (Resizable Dividers)
Splitters use dedicated config fields for sizes:

1. **Horizontal Splitters**: Store width
   ```python
   # In Config
   sidebar_width: int = 300
   
   # Save on resize
   def save_sidebar_width(self):
       sizes = self.main_splitter.sizes()
       self.config.sidebar_width = sizes[0]
       self.config.save()
   
   # Restore on startup
   self.main_splitter.setSizes([sidebar_width, total_width - sidebar_width])
   ```

2. **Vertical Splitters**: Store heights
   ```python
   # In Config
   sidebar_section_sizes: list = Field(default_factory=list)
   
   # Save on resize
   def save_sidebar_section_sizes(self):
       sizes = self.sidebar_splitter.sizes()
       self.config.sidebar_section_sizes = sizes
       self.config.save()
   
   # Restore on startup
   if self.config.sidebar_section_sizes:
       self.sidebar_splitter.setSizes(self.config.sidebar_section_sizes)
   ```

### State Persistence Checklist
When implementing any new UI section:

- [ ] Add config field(s) for the section's state
- [ ] Implement save logic that triggers on state changes
- [ ] Implement restore logic during initialization
- [ ] Ensure config.save() is called after state updates
- [ ] Use getattr() with defaults for backward compatibility
- [ ] Test that state persists across application restarts

### Existing Implementations

| Component | State Tracked | Config Field(s) | Status |
|-----------|---------------|-----------------|--------|
| Sidebar width | Horizontal size | `sidebar_width` | ✅ Implemented |
| Sidebar section heights | Vertical sizes | `sidebar_section_sizes` | ✅ Implemented |
| Sidebar sections | Collapsed state, height | `sidebar_section_states` | ✅ Implemented |
| Filter section | Visible/hidden | `filter_section_visible` | ✅ Implemented |
| Filter selections | Language, quality, platform | `filter_included_*` | ✅ Implemented |
| Media type chips | Enabled types | `filter_enabled_media_types` | ✅ Implemented |

### Config Persistence
All config fields are automatically persisted to `~/.config/metatv/config.json` via the `Config.save()` method. Changes are saved immediately when state updates occur, ensuring no data loss on unexpected application termination.
