# MetaTV — Claude Code Project Guide

## What This Is

MetaTV is a Python/PyQt6 IPTV client. It connects to Xtream API providers, caches channel data in SQLite, and plays streams via mpv. The UI has a three-panel layout: sidebar (sources/favorites/history), channel list, and a details pane.

**Run it:** `./run.sh` or `venv/bin/python -m metatv`

## Architecture

```
metatv/
├── core/               # Business logic (no UI dependencies)
│   ├── config.py            # Pydantic config (~/.config/metatv/config.yaml)
│   ├── database.py          # SQLAlchemy models + connection
│   ├── preference_engine.py # Attribute-weight + TF-IDF recommendation scoring
│   ├── discovery_engine.py  # SQL queries for Discovery shelves (genre/decade/actor/director)
│   ├── content_dedup.py     # Cross-source title normalization + deduplication
│   ├── epg_manager.py       # EPG fetch/parse/store + watchlist notification timer
│   ├── image_cache.py       # Async image cache, MD5-keyed, LRU cleanup at 500MB
│   ├── metadata_manager.py  # Metadata provider chain + caching
│   ├── notifications.py     # Toast notification system
│   ├── provider_loader.py   # Background channel loading
│   ├── special_content.py   # PPV/Events/Sports detection + classification
│   ├── stream_retry_manager.py  # URL failover + retry logic
│   ├── xmltv_parser.py      # Streaming XMLTV parser (iterparse, 140MB+)
│   └── repositories/
│       ├── channel.py   # Channel queries (hidden_only, prefix filters, search)
│       ├── epg.py       # EPG programme queries (current, watchlist, browse, search)
│       ├── queue.py     # Watch queue CRUD (QueueEntry, WatchQueueRepository)
│       └── provider.py  # Provider queries
├── gui/                # PyQt6 UI components
│   ├── main_window.py        # Three-panel main window + chip nav
│   ├── details_pane.py       # Right panel — metadata, play, favorite, hide/unhide
│   ├── discover_view.py      # Discovery view orchestration (glue layer, ~290 lines)
│   ├── discover_card.py      # Content card widget + flow layout helper
│   ├── discover_shelf.py     # Horizontal scroll shelf row widget
│   ├── discover_browse.py    # See-all drill-down view + search/grid
│   ├── discover_workers.py   # Background shelf-loading QThread workers
│   ├── similar_lightbox.py   # Similar Titles modal lightbox
│   ├── preferences_view.py   # Recommendations dashboard (attribute weights + exclusions)
│   ├── epg_view.py           # EPG view — Watchlist / On Now / Browse tabs
│   ├── global_filter_dialog.py  # Global content filter (prefix groups + Other expandable)
│   ├── events_view.py        # Live events view
│   ├── sports_view.py        # Sports events view
│   ├── sports_filter_bar.py  # Sport/league filter chips
│   ├── provider_editor.py    # Provider add/edit form
│   ├── settings_dialog.py    # App settings
│   ├── sidebar_sections.py   # CollapsibleSection base + sections (queue, recs, alerts, favorites, history)
│   └── notification_widget.py
├── providers/          # IPTV source plugins
│   ├── base.py         # ProviderPlugin abstract base
│   └── xtream.py       # Xtream API client
└── metadata_providers/ # Metadata enrichment plugins
    ├── base.py         # MetadataProviderPlugin + MetadataResult
    └── provider.py     # Extracts from Xtream raw_data (zero-latency)
```

**Data locations:**
- Config: `~/.config/metatv/config.yaml`
- Database: `~/.local/share/metatv/metatv.db`
- Logs: `~/.config/metatv/logs/`
- Image cache: `~/.cache/metatv/images/`

## Critical Rules

### EPG time utilities — always from `epg_utils.py`
All EPG time functions (`now_utc`, `fmt_time`, `remaining_str`, `minutes_away`, `progress_pct`, `fmt_duration`) live in `metatv/core/epg_utils.py`. Never redefine these inline. Import from there: `from metatv.core.epg_utils import now_utc, fmt_time, ...`.

### Collapse/expand buttons — always `expand_icon` / `collapse_icon`, never other arrow icons
Any button that toggles a collapsible section must use `config.expand_icon` (collapsed state) and `config.collapse_icon` (expanded state). Never use `move_up_icon` / `move_down_icon` for this — those are list-ordering arrows with different semantics.

For top-level collapsibles, subclass `CollapsibleSection` (in `sidebar_sections.py`) — it handles the button, state, and persistence automatically. For inner/nested collapsibles (e.g. Stream Monitoring sub-section), follow the same button convention:
```python
btn = QPushButton(self.config.collapse_icon)  # start expanded
btn.setFixedSize(20, 20)
btn.setFlat(True)
# on toggle:
btn.setText(self.config.expand_icon if collapsed else self.config.collapse_icon)
```

### Styles — use `theme.py`, never inline duplicates
All Qt stylesheet strings shared across more than one widget must live in `metatv/gui/theme.py` as named constants. Import with `from metatv.gui import theme as _theme` and reference by name (`_theme.PLAY_BTN`, `_theme.CARD_BG`, etc.). Never copy-paste a stylesheet string between files. If you need a variant, add a new constant to `theme.py`.

### Lookup tables — single source of truth, no duplicates
Region/country codes, quality tokens, audio format maps, and similar lookup data must live in exactly one place. The canonical location for channel-name parsing data is `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, etc.). All other modules (GUI, details pane, sidebar) must import from there — never define their own parallel dicts.

If you need to add a new code or alias, add it to `channel_name_utils.py` only. Never copy the dict into a second file.

### Icons — always from Config, never hardcoded
Every icon, emoji, or symbol displayed in the UI must be defined as a field on `Config` (`metatv/core/config.py`) and referenced through it. This includes media-type icons, action icons (play, close, delete, hide), section header icons, folder/season indicators, status badges — everything. Never write a literal emoji or symbol string directly in widget or layout code.

```python
# Correct
rm_btn = QPushButton(self.config.close_icon)
section_icon = config.favorite_icon

# Wrong — hardcoded literals
rm_btn = QPushButton("×")
super().__init__("Favorites", "★", config, parent)
```

If you need an icon that doesn't exist in Config yet, add it there first, then reference it.

### Logging — always loguru, never stdlib
```python
from loguru import logger   # correct
import logging              # NEVER use this
```

### Database sessions — try/finally, never `with session`
`with session` only manages transactions, not cleanup. Always:
```python
session = self.db.get_session()
try:
    # ... use session ...
finally:
    session.close()
```

### SQLite + SQLAlchemy JSON — manual serialization only
SQLAlchemy's JSON column type has SQLite compatibility issues. Use:
```python
metadata.cast = json.dumps(result.cast)   # saving
cast = json.loads(metadata.cast) if metadata.cast else []  # loading
```

This applies to **every assignment** to a JSON column — including after modifying a previously-deserialized list or dict in-place. If you read with `json.loads()`, you must write back with `json.dumps()`.

```python
# Wrong — assigning a Python object back without re-serializing
raw = json.loads(db_obj.urls)
raw[0]['count'] += 1
db_obj.urls = raw          # ← BUG: stores a Python list, not JSON string

# Correct
db_obj.urls = json.dumps(raw)
```

### Qt threading — signals only, never direct widget access from threads
Qt widgets are NOT thread-safe. Worker threads must emit signals; only the main thread updates widgets.
```python
class MyWidget(QWidget):
    data_ready = pyqtSignal(object)   # signal defined at class level

    def start_work(self):
        self.executor.submit(self._worker)

    def _worker(self):                 # runs in thread — NO widget access
        result = fetch()
        self.data_ready.emit(result)   # marshal to main thread

    def _on_data_ready(self, result):  # runs on main thread — safe
        self.label.setText(result)
```

**QPixmap must be created on the main thread.** It is a GUI object and is not thread-safe. Never call `QPixmap(path)` inside a `ThreadPoolExecutor` or `QThread` worker. The pattern for async image loading:
```python
# Private signal carries the path string (safe cross-thread)
_image_ready = pyqtSignal(str, str)   # url, cache_path

def _worker(self, url):               # in thread pool
    path = download_and_save(url)
    self._image_ready.emit(url, path)  # emit path, NOT QPixmap

def _on_image_ready(self, url, path): # on main thread — safe to create QPixmap
    pixmap = QPixmap(path)
    self.image_loaded.emit(url, pixmap)
```

### Signal blocking during UI state restoration
Block signals before programmatically setting state, connect signals after:
```python
for chip in self.chips:
    chip.blockSignals(True)
    chip.set_enabled(config.is_enabled(chip.type))
    chip.blockSignals(False)
for chip in self.chips:
    chip.toggled.connect(self.on_toggled)
```

### EPG notifications — never call NotificationManager from worker threads
`NotificationManager.show()` creates a `QTimer` for auto-dismiss and must only be called from the main thread. In `EpgManager`, all notification calls from `ThreadPoolExecutor` workers go through private signals (`_notify`, `_progress_update`, `_progress_done`, `_progress_error`) that Qt queues to the main thread automatically.

### EPG times — stored as UTC-naive, display as local
`EpgProgramDB.start_time` / `stop_time` are stored as UTC-naive datetimes (the XMLTV parser normalises all timestamps to UTC). For display, convert with:
```python
local = dt.replace(tzinfo=timezone.utc).astimezone()  # → machine local tz
```
For arithmetic (remaining time, progress bars), compare UTC-naive against `_now_utc()` — no conversion needed.

**Never compare `.date()` directly against `date.today()`.** `date.today()` returns the local calendar date; EPG datetimes are UTC-naive. For users outside UTC, this produces wrong Today/Tomorrow labels. Always convert first:
```python
# Wrong
if prog.start_time.date() == date.today():  # UTC date vs local date — mismatch

# Correct
local_date = prog.start_time.replace(tzinfo=timezone.utc).astimezone().date()
if local_date == date.today():
```

### EPG concurrent fetches — one worker at a time
`EpgManager` uses `ThreadPoolExecutor(max_workers=1)`. Running two XMLTV fetches concurrently causes SQLite `database is locked` errors because each fetch does a bulk-delete + bulk-insert. Providers are fetched sequentially; the second queues behind the first.

### Early returns must clean up acquired state
Any resource or set membership acquired before a guard check must be released on every early return path — not just the happy path.

```python
# Wrong — pid stays in the set forever if lookup fails
self.refreshing_providers.add(pid)
provider = repos.get(pid)
if not provider:
    return                             # ← BUG: pid never removed

# Correct
self.refreshing_providers.add(pid)
provider = repos.get(pid)
if not provider:
    self.refreshing_providers.discard(pid)
    return
```

Apply this to locks, sets, progress trackers, and any other state set before a validation check.

### View lifecycle — on_activate / on_deactivate must be symmetric
If a view has `on_activate()` (starts timers, loads data), it must also have `on_deactivate()` (stops timers, cancels pending work). Both must be called by the host (`main_window.py`) at view switch time — `on_deactivate` for the departing view, `on_activate` for the arriving one. The safest pattern: call `on_deactivate()` inside `_hide_all_content_views()` for any view that is currently visible.

### Resource cleanup in closeEvent
Any background manager with a `stop()` or `shutdown()` method must be called explicitly in `MainWindow.closeEvent`. Relying on garbage collection or QObject parent destruction is not sufficient for threads. Pattern:
```python
def closeEvent(self, event):
    self.player_manager.cleanup()
    if hasattr(self, "stream_retry_manager"):
        self.stream_retry_manager.stop()
    self.db.close()
    event.accept()
```

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) must save to config and restore on startup. Pattern: save immediately on change, restore during `__init__`. See `DESIGN.md` for the full pattern.

## Metadata Provider Chain

Providers tried in priority order until sufficient data found:
1. `ProviderMetadataProvider` — extracts from Xtream `raw_data` (always try first, zero latency)
2. `TMDbProvider` — not yet implemented
3. `OMDbProvider` — not yet implemented

`MetadataResult.merge()` uses confidence scores (0.0–1.0) to prefer higher-quality data per field.

## Content Dedup — Known Compromises

`content_dedup.py` uses a `(norm_title, media_type, year, director)` fingerprint to group same-production channels across providers. This is a **heuristic stopgap** until TMDb/IMDb canonical IDs are wired up. Known trade-offs baked in by deliberate choice:

- **Director excluded for series.** TV series have many episode directors; metadata providers attribute the same show to different people (creator, showrunner, first-episode director). Including director caused false splits (same show appearing twice in recommendations). Movies keep director because a single director is reliably credited and helps distinguish remakes.

- **Null-year absorption.** When a candidate has no year in either the channel name or MetadataDB, it is suppressed if a year-bearing engaged variant with the same `(norm, media_type)` exists. This fixes cases like `EAR ★ Rick and Morty` (no year) appearing in recommendations when `EN - Rick And Morty (2013)` is already queued. Risk: a genuinely different series with the same name and no year metadata could be incorrectly suppressed — acceptable given the rarity of that combination.

- **These compromises mean the recommendations list may occasionally hide a legitimate alternative or surface an unexpected variant.** The long-term fix is `tmdb_id`/`imdb_id` as the primary key (ROADMAP). A "dedup transparency toggle" for advanced/debug use is also tracked in ROADMAP.

Do not tighten these heuristics without first checking that the specific failing case isn't better fixed by improving metadata completeness (year in channel name, consistent director field).

## Image Cache

MD5(url) as filename in `~/.cache/metatv/images/`. LRU cleanup at 500MB. Always load images async via `ImageCache.get_image_async()` + signals — never block the main thread.

## Coding Standards

- Python 3.11+ type hints on all function signatures
- Google-style docstrings on public APIs
- Imports: stdlib → third-party → local, separated by blank lines
- Keep files under 1000 lines; one class per file (helper classes excepted)
- Use `ThreadPoolExecutor` for blocking I/O; use `asyncio` for async providers
- `QTimer.singleShot(0, ...)` for deferred main-thread execution

## Session Wrap SOP

When the user says "let's wrap up" or "wrap this session", do ALL of the following in order:

1. **Tests** — run `venv/bin/python -m pytest tests/ -x -q` and confirm all pass; if any new behaviour was added, note what test coverage is still missing and add items to the FILTERING_DESIGN / ROADMAP test-coverage sections
2. **Commit anything uncommitted** — stage and commit all modified files with a descriptive message; never leave working changes untracked
3. **Docs** — update any design/reference docs that are now stale: `docs/FILTERING_DESIGN.md` (implementation status table + roadmap), `ROADMAP.md` (new items, completed items), `docs/UI_UX_GUIDELINES.md` if interaction patterns changed
4. **CLAUDE.md** — update if any new critical rules, architecture patterns, or file locations were established this session
5. **Memory** — update persistent memory files in `~/.claude/projects/…/memory/`: refresh `project_session_handoff.md` with current branch/commit/open work, update `project_filter_system.md` or other relevant memory files with anything that changed; write new memory files for new patterns or decisions
6. **Push** — `git push origin main`; confirm no errors
7. **Confirm** — tell the user what was committed, pushed, and written to memory; call out anything that couldn't be done and why

## Reference Docs

| Topic | File |
|---|---|
| UI/UX interaction patterns | [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) |
| Qt threading deep dive | [docs/THREADING_PATTERNS.md](docs/THREADING_PATTERNS.md) |
| Metadata system architecture | [docs/METADATA_SYSTEM.md](docs/METADATA_SYSTEM.md) |
| Filtering design | [docs/FILTERING_DESIGN.md](docs/FILTERING_DESIGN.md) |
| Details pane design | [docs/DETAILS_PANE_DESIGN.md](docs/DETAILS_PANE_DESIGN.md) |
| Xtream API schema | [docs/xtream_api_schema.md](docs/xtream_api_schema.md) |
| UI state persistence patterns | [DESIGN.md](DESIGN.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Refactor / dedup / cleanup plan | [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md) |
