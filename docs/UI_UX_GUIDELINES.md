# MetaTV UI/UX Guidelines

This document defines standard UI/UX behaviors maintained throughout the application to ensure consistency. Follow these patterns when implementing new features or modifying existing ones.

## Interaction Patterns

### Double-Click Behaviors

**Tree Widgets (Series/Season/Episode hierarchy)**
- Double-clicking a **season item** → expands/collapses to show/hide episodes
- Double-clicking an **episode item** → plays the episode
- Implementation: Custom handler `play_series_item()` checks item type and routes accordingly
- **Important**: Do NOT use `setExpandsOnDoubleClick(True)` when using custom double-click handlers (causes conflict)

**List Widgets (Channels, Favorites, History)**
- Double-clicking a **series channel** → drills into series view (loads seasons/episodes)
- Double-clicking a **movie channel** → plays the movie
- Double-clicking a **live stream** → plays the stream
- Double-clicking **history item** → plays the last watched episode

### Single-Click Behaviors

**Selection Only**
- Single-click on any list or tree item → selects the item (no action)
- Enables keyboard navigation and context menus

### Context Menus (Right-Click)

**Channels/Series**
- Add to Favorites / Remove from Favorites
- Refresh metadata
- Edit custom filters (future)

**Episodes**
- Mark as watched / unwatched
- Add to favorites
- Queue next episodes (future)

## Notification System

### Progress Notifications

**Loading Series/Movies**
- Title format: `"Loading {series_name}"` (e.g., "Loading EN - Star Trek (1966)")
- Shows progress during data fetch
- Auto-dismisses after 5 seconds when complete

**Provider Refresh**
- Title format: `"Refreshing {provider_name}"`
- Shows progress with channel count
- Auto-dismisses on completion

### Notification Timing
- Progress notifications: visible until complete
- Success notifications: auto-dismiss after 5 seconds
- Error notifications: remain until user dismisses
- Info notifications: auto-dismiss after 3 seconds

### Notification Architecture
- `NotificationManager` (core/notifications.py) owns QTimer instances
- `NotificationWidget` is pure display layer, no business logic
- Timers managed centrally for clean lifecycle management

## Status Bar

**Persistent Status**
- Shows current action or last completed action
- Examples:
  - "Playing: {episode_title}"
  - "Loaded {channel_count} channels"
  - "{series_name} added to favorites"

## Sidebar Sections

### Collapsible Sections
- Click section header → expands/collapses content
- State and **expanded height** persist across app restarts (`sidebar_section_states[id]`)
- Minimum expanded height: 80px (`_MIN_EXPANDED` in `sidebar/base.py`) — the splitter enforces this so the user cannot drag an expanded section below header + ~2 rows
- **Collapsing**: freed pixels are distributed proportionally to all other visible sections; no dead gap appears
- **Expanding**: section restores to its last saved expanded height by stealing proportionally from neighbors; each neighbor's floor is respected (26px if collapsed, 80px if expanded)

### History Section
- Shows recently played series/movies
- Format: `{icon} {name}\n   → S{season:02d}E{episode:02d}` (for series)
- Double-click → plays last watched episode
- ">> Play Next" button → plays next unwatched episode (future)

### Favorites Section
- Shows favorited channels (series/movies/streams)
- Star icon indicates favorite status
- Double-click → loads/plays content

## Media Player Integration

### Single-Instance mpv
- One mpv instance manages all playback
- IPC via Unix socket: `/tmp/mpv-metatv-socket`
- Commands sent via JSON-RPC protocol
- Window remains persistent across episodes

### Episode Queueing (Future)
- When `autoplay_season_episodes` enabled (default: true)
- Playing an episode queues remaining episodes in season
- Uses mpv `append-play` mode
- Shows "Queued N episodes" notification

## Search & Filtering

### Real-Time Search
- Search input filters as you type (debounced)
- Searches across: name, description, category
- Case-insensitive
- Clear button (×) resets search

### Text-entry inputs — inline clear standard
All editable single-line `QLineEdit` widgets — search boxes, filter inputs, and free-text entry
fields (name, URL, username, password, API key, pattern, prefix, etc.) — call
**`setClearButtonEnabled(True)`** immediately after construction. Qt renders the inline × button
automatically when the box has text. Do **not** add a bespoke external `QPushButton` for this
purpose. Read-only fields (`setReadOnly(True)`) are exempt. Clearing via the inline button sets
text to `""`, which emits `textChanged` — existing handlers work without modification.
This rule is enforced by the source-scan test in `tests/test_clear_button_standard.py`
(`test_every_qlineedit_has_clear_button_or_readonly`).

### Category Organization
- Channels organized by `## Header` format
- Expandable/collapsible category groups
- Shows channel count per category

### Filter Presets (Future)
- Language filters: All, English Only, Spanish Only, etc.
- Quality filters: 4K, HD, SD
- Genre filters: parsed from metadata
- Stored in: `config.yaml` → `filters.presets`

## Data Loading

### Progressive Loading
- UI remains responsive during background operations
- Background threads for:
  - Provider channel list refresh
  - Series season/episode loading
  - Metadata fetching
- Progress shown in notifications and status bar

### Caching Strategy
- Series/episode data cached in SQLite
- Instant display on subsequent loads
- Manual refresh available via context menu

## Error Handling

### User-Facing Errors
- Error notifications with clear, actionable messages
- Examples:
  - "Error: No stream URL for episode"
  - "Failed to connect to provider: check credentials"
  - "Player not found: install mpv or VLC"

### Developer Errors
- Detailed logging via loguru
- Log location: `~/.config/metatv/logs/`
- Debug level for development, INFO for production

## Accessibility

### Keyboard Navigation
- Arrow keys: navigate lists and trees
- Enter: activate selected item (same as double-click)
- Space: toggle selection
- Ctrl+F: focus search box (future)
- Escape: clear search / close dialogs

### Visual Feedback
- Hover states on clickable elements
- Selected item highlight
- Loading indicators for async operations
- Icon states: favorite (★), watched (✓), etc.

## Configuration Persistence

### Saved State
- Window size and position
- Sidebar section collapsed states
- Selected provider
- Search/filter presets
- Favorites list

### Location
- Config: `~/.config/metatv/config.yaml`
- Database: `~/.local/share/metatv/metatv.db`
- Logs: `~/.config/metatv/logs/`

### Auto-Save Behavior
- Configuration saves immediately on user action
- No save during programmatic state restoration
- Use `save=False` parameter when restoring state

## Design Principles

1. **Immediate Feedback**: Every user action provides immediate visual or audio feedback
2. **Non-Blocking UI**: Long operations run in background threads
3. **Consistent Interactions**: Same gesture = same outcome across the app
4. **Progressive Disclosure**: Show common actions first, advanced features in menus
5. **Error Recovery**: Always provide clear next steps when errors occur
6. **State Persistence**: Remember user preferences and UI state across sessions
7. **Performance First**: Handle 100,000+ channels without lag
8. **Clean Architecture**: Separate business logic from UI, avoid circular dependencies

## Theming & style tokens

All Qt stylesheets are centralized in `metatv/gui/theme.py`, which is deliberately **two layers**.
The split exists because an earlier pass extracted duplicate stylesheet strings into named
constants but left two latent problems: raw color/size literals were scattered across ~40 constants
(so "make muted text lighter" meant editing six near-identical greys), and some constants were
named by *appearance* (`TEXT_SM`, `GREY_11`) rather than role, which invites two unrelated widgets
to couple to the same string just because they look alike. The token layer fixes both.

**Layer 1 — design tokens** (`COLOR_*`, `FONT_*`, `OVERLAY_*`): the single source of truth for
palette values. The *only* place a raw hex / rgba color literal may live, and the home of every font
*size* (`FONT_*`). Token names may be appearance-based (`FONT_MD = "11px"`, `COLOR_MUTED = "#888"`)
because they *are* the design scale. Change the palette in one place and it propagates everywhere.

**Layer 2 — semantic constants**: complete stylesheet strings composed from tokens (by string
concatenation, which keeps literal `{...}` Qt selectors readable), named by the **role** they play —
`STATUS_OK`, `SECTION_HINT`, `LOADING_TEXT`, `EMPTY_LABEL`. A role name localizes design intent: if
"status warning" should change, you edit `STATUS_WARN` without touching every amber thing in the app.

**Conventions** (enforced in CLAUDE.md → "Styles"):
- **Colors strict**: never inline a hex / rgba literal — always a `COLOR_*` / `OVERLAY_*` token
  (dynamic styles too: interpolate the token, never the hex). **Font sizes**: use `FONT_*` tokens,
  never `font-size: Npx`. **Structural-spacing px** (`padding`, `margin`, `border-radius`,
  `border-width`, fixed sizes) is acceptable inline — there are no spacing tokens. Only colors and
  font-sizes must be tokens.
- Any stylesheet used by more than one widget → a role-named constant in `theme.py`. Single-use
  inline styles are allowed but should still build from tokens.
- Status colors come as a cohesive set (`STATUS_OK` / `STATUS_WARN` / `STATUS_ERR`); extract the
  whole set even if only one is currently used, so the next usage doesn't reintroduce an inline literal.
- Behavior-preservation: extracting/refactoring styles must not change rendered output. When moving
  many strings at once, assert byte-equality of each constant against its prior value (a throwaway
  comparison script) — the test suite does **not** cover stylesheet values, so this is the only
  safety net against a silent visual regression.

## Future Enhancements

### Browse vs Search Modes
- **Browse Mode**: Hierarchical category navigation, expandable groups
- **Search Mode**: Real-time filtering across all content
- Toggle between modes via toolbar button

### Metadata Display
- Preview/detail pane showing:
  - Cover art, description, release date
  - Cast, crew, ratings
  - Related content suggestions
  - Watch alerts for new episodes

### Smart Features
- Resume playback from last position
- "Continue Watching" section
- Recommendations based on watch history
- Custom collections and playlists

---

## Coding Standards

### Code Organization

**Self-Documenting Structure**
- File paths and directory structure should be intuitive without reading code
- One class per file (exceptions: small related classes like enums)
- Parallel structure for similar patterns (e.g., `repositories/` matches `players/`)
- File names match class names: `ChannelRepository` → `channel.py`

**Package Structure**
```
metatv/
├── core/
│   ├── repositories/        # Data access layer - one repo per file
│   │   ├── channel.py
│   │   ├── provider.py
│   │   └── ...
│   ├── players/             # Player plugins - one player per file  
│   │   ├── mpv.py
│   │   └── base.py
│   └── providers/           # Provider plugins
│       ├── xtream.py
│       └── base.py
└── gui/                     # UI layer
    ├── main_window.py
    └── sidebar_sections.py
```

**File Size Guidelines**
- Target: 50-200 lines per file
- Warning threshold: 300 lines
- Refactor threshold: 500+ lines (God object alert)
- Exception: Main window can be larger but extract concerns into separate classes

### Architecture Patterns

**Separation of Concerns**
- **Repository Pattern**: All database queries go through repositories, never raw `session.query()` in GUI
- **Plugin Pattern**: Use ABC base classes for extensibility (PlayerPlugin, ProviderPlugin)
- **Facade Pattern**: Simplify complex subsystems (PlayerManager wraps player details)
- **Factory Pattern**: Centralized object creation (RepositoryFactory, ProviderRegistry)

**Layer Boundaries**
```
GUI Layer (PyQt6 widgets)
    ↓ uses
Business Layer (Managers, Services)
    ↓ uses  
Data Layer (Repositories)
    ↓ uses
Database (SQLAlchemy ORM)
```

**Never**:
- Database queries in GUI code
- Business logic in widgets
- UI code in core modules
- Circular dependencies between layers

### Dependency Injection

**Constructor Injection**
```python
class ChannelRepository:
    def __init__(self, session: Session):
        self.session = session  # Injected dependency
```

**Factory Pattern**
```python
class RepositoryFactory:
    def __init__(self, session: Session):
        self.session = session  # Shared session
    
    @property
    def channels(self) -> ChannelRepository:
        # Lazy-loaded, shares session
        if self._channels is None:
            self._channels = ChannelRepository(self.session)
        return self._channels
```

### Type Hints

**Always Use Type Hints**
```python
def get_by_id(self, channel_id: str) -> Optional[ChannelDB]:
    """Get channel by ID"""
    return self.session.query(ChannelDB).filter_by(id=channel_id).first()
```

**Generic Types**
```python
from typing import List, Optional, Dict, Callable

def get_all(self, filters: Optional[Dict[str, Any]] = None) -> List[ChannelDB]:
    pass
```

### Error Handling

**Specific Exceptions**
```python
try:
    channel = repos.channels.get_by_id(channel_id)
    if not channel:
        logger.error(f"Channel not found: {channel_id}")
        self.status_bar.showMessage("Error: Channel not found")
        return
except Exception as e:
    logger.error(f"Error loading channel: {e}")
    self.status_bar.showMessage(f"Error: {e}")
```

**User-Facing Messages**
- Clear, actionable error messages
- Log technical details, show user-friendly summary
- Always provide next steps or recovery options

### Logging

**Use loguru for structured logging**
```python
from loguru import logger

logger.info(f"Loaded {len(channels)} channels")
logger.debug(f"Channel details: {channel.name} ({channel.id})")
logger.warning(f"Missing stream URL for: {channel.name}")
logger.error(f"Failed to connect to provider: {e}")
```

**Log Levels**
- `DEBUG`: Detailed technical info for debugging
- `INFO`: General operations (user actions, loading data)
- `WARNING`: Recoverable issues (missing optional data)
- `ERROR`: Failures that need attention

### Documentation

**Docstrings for Public APIs**
```python
def mark_played(self, channel_id: str) -> None:
    """Mark channel as played - updates last_played and increments play_count
    
    Args:
        channel_id: Unique identifier for the channel
        
    Side Effects:
        - Updates channel.last_played to current time
        - Increments channel.play_count
        - Commits to database
    """
```

**Comments for Complex Logic**
- Explain WHY, not WHAT (code shows what)
- Document workarounds and gotchas
- Reference issue numbers when applicable

### Testing

**Repository Layer (Future)**
- Mock database session
- Test CRUD operations
- Verify business logic

**UI Layer (Future)**
- Use pytest-qt for widget testing
- Mock repositories and services
- Test user interactions

### Code Review Checklist

- [ ] File structure is intuitive (would a new dev find it easily?)
- [ ] No God objects (files >500 lines should be split)
- [ ] Layer boundaries respected (no DB queries in GUI)
- [ ] Type hints on all public methods
- [ ] Error handling with user-friendly messages
- [ ] Logging at appropriate levels
- [ ] No circular dependencies
- [ ] Repository pattern used for all database access
- [ ] Plugin pattern used for extensible features

### Refactoring Triggers

**When to Refactor**
- File exceeds 500 lines
- Class has more than 3 responsibilities (God object)
- Method exceeds 50 lines
- Code duplicated in 3+ places
- Adding new feature requires modifying many files
- Tests become difficult to write

**How to Refactor**
1. Identify single responsibility
2. Extract to new file/class
3. Update imports
4. Verify no errors
5. Test functionality
6. Update documentation

**Recent Refactoring Examples**
- Split 526-line `repositories.py` → 7 files (channel.py, provider.py, etc.)
- Extracted player logic from MainWindow → `players/` package
- Separated notification timer management → NotificationManager
