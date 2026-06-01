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

### Styles — no duplicated stylesheet strings; share via `theme.py`
Any Qt stylesheet string used by more than one widget must live in `metatv/gui/theme.py` as a named constant. Import with `from metatv.gui import theme as _theme` and reference by name (`_theme.PLAY_BTN`, `_theme.CARD_BG`, etc.). Never copy-paste a stylesheet string between files; if you need a variant, add a new constant to `theme.py`. A genuinely single-use style may stay inline — the rule targets **duplication**, not the existence of inline styles.

### Lookup tables — single source of truth, no duplicates
Region/country codes, quality tokens, audio format maps, and similar lookup data must live in exactly one place. The canonical location for channel-name parsing data is `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, etc.). All other modules (GUI, details pane, sidebar) must import from there — never define their own parallel dicts.

If you need to add a new code or alias, add it to `channel_name_utils.py` only. Never copy the dict into a second file.

### Icons — always from the central icon registry, never hardcoded
Every icon, emoji, or symbol displayed in the UI must come from the central icon registry, never a literal in widget or layout code. This includes media-type icons, action icons (play, close, delete, hide), section header icons, folder/season indicators, status badges — everything.

<!-- target: icons currently live as fields on `Config` (metatv/core/config.py). A settings/persistence model is the wrong home for presentation constants — REFACTOR_PLAN moves them to a dedicated `metatv/gui/icons.py` registry. Until that lands, the registry IS `Config`: reference `self.config.<name>_icon` and add new glyphs there first. -->

```python
# Correct (current registry = Config)
rm_btn = QPushButton(self.config.close_icon)
section_icon = config.favorite_icon

# Wrong — hardcoded literals
rm_btn = QPushButton("×")
super().__init__("Favorites", "★", config, parent)
```

If you need an icon that doesn't exist yet, add it to the registry first, then reference it.

**Collapse/expand buttons specifically:** use `config.expand_icon` (collapsed state) and `config.collapse_icon` (expanded state) — never `move_up_icon` / `move_down_icon`, which are list-ordering arrows with different semantics. For top-level collapsibles, subclass `CollapsibleSection` (in `sidebar_sections.py`) — it handles the button, state, and persistence automatically. For inner/nested collapsibles (e.g. Stream Monitoring sub-section), follow the same convention:
```python
btn = QPushButton(self.config.collapse_icon)  # start expanded
btn.setFixedSize(20, 20)
btn.setFlat(True)
# on toggle:
btn.setText(self.config.expand_icon if collapsed else self.config.collapse_icon)
```

### Logging — always loguru, never stdlib
```python
from loguru import logger   # correct
import logging              # NEVER use this
```

### Database sessions — use `session_scope()` for new code
`Database.session_scope()` is a context manager that commits on success, rolls back on exception, and always closes the session. **Use it for all new code:**

```python
# Preferred — commits/rollback/close are automatic
with self.db.session_scope() as session:
    repos = RepositoryFactory(session)
    # ... use session ...
```

A bare `with session:` only manages the *transaction*, not cleanup — never use that form. The legacy `try/finally` pattern remains in existing code:
```python
# Legacy — still acceptable, being migrated incrementally
session = self.db.get_session()
try:
    # ... use session ...
finally:
    session.close()
```

### SQLite + SQLAlchemy JSON — serialize explicitly
SQLAlchemy's native JSON column type has SQLite compatibility issues, so JSON columns are plain `Text` and serialization is done by hand:
```python
metadata.cast = json.dumps(result.cast)   # saving
cast = json.loads(metadata.cast) if metadata.cast else []  # loading
```

<!-- target: manual dumps/loads at every call site is the *cause* of the
recurring "stored a Python list instead of a JSON string" bug below.
REFACTOR_PLAN proposes a `JSONEncoded` TypeDecorator (process_bind_param /
process_result_value) so columns become `Column(JSONEncoded)` and you
assign/read plain Python objects — the discipline below becomes unnecessary.
Until that lands, follow the manual rule exactly. -->

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
<!-- target: UTC-naive storage is the root cause of this whole cluster of
defensive rules (and bug P0-2 in REFACTOR_PLAN). The long-term fix is
tz-aware UTC storage, or routing *every* conversion through `epg_utils.py`
so no view ever touches a raw `start_time`. Until then, follow the rules below. -->
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

### Resource cleanup in closeEvent — use the cleanup registry
`MainWindow` owns a `self._cleanables: list[tuple[str, callable]]` registry. Every new background manager **must** register its shutdown callable immediately after construction — do not add it manually to `closeEvent`:

```python
# After creating the manager:
self.my_manager = MyManager(...)
self._register_cleanable("my_manager", self.my_manager.shutdown)
```

`closeEvent` iterates `_cleanables` automatically; exceptions are caught per-entry so a failing cleanup never blocks the rest. Never add a new `hasattr(self, "manager_name")` block to `closeEvent` — use the registry instead. `db.close()` and the view-deactivation loop remain explicit in `closeEvent` because they require sequencing/visibility logic the registry does not handle.

### Background pools/threads — owned, long-lived, and shut down
Create a `ThreadPoolExecutor` / `QThread` **once per owning object**, never per call. A pool created inside a method that runs more than once is a thread leak (see `main_window.py` metadata-fetch path). Every pool/thread must be stopped in its owner's cleanup path — `closeEvent` for managers, `on_deactivate` for views (per the rules above). Reuse the owner's shared executor (`self.executor`) for one-off background work rather than spinning up a throwaway pool.

### No unbounded DB work on the UI thread
The Qt-threading rule above governs *widget* access from worker threads; this is the inverse. Queries that can scan, filter, aggregate, or count over large tables (channels, EPG) must run in an executor and marshal results back via signal — never block the main thread. Trivial primary-key lookups inline are fine; anything that grows with library size (240k+ channels) must be offloaded. Offenders to watch: startup stat initialization, sidebar `refresh()`, context-menu lookups.

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
| Sonnet execution prompt for the plan | [docs/SONNET_EXECUTION_PROMPT.md](docs/SONNET_EXECUTION_PROMPT.md) |
