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
│       ├── dtos.py      # Frozen dataclasses for thread-safe sidebar/series data (B7-2)
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
All EPG time functions (`now_utc`, `fmt_time`, `remaining_str`, `minutes_away`, `progress_pct`, `fmt_duration`, `epg_is_stale`) live in `metatv/core/epg_utils.py`. Never redefine these inline. Import from there: `from metatv.core.epg_utils import now_utc, fmt_time, ...`. `epg_is_stale(epg_data_end)` is the single staleness boundary (a provider feed serving year-old guide data) — used by the EPG view notice, the provider editor's EPG line, and the fetch-time warning; the EPG view's banner list comes from `ProviderRepository.get_stale_epg_providers()`.

### Styles — two-layer `theme.py`; tokens for all palette values, role-named constants
Two layers, respect the split (full rationale: [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) →
"Theming & style tokens"):

1. **Design tokens** — `COLOR_*`, `FONT_*`, `OVERLAY_*`: the **only** place a raw hex/rgba literal or a
   font *size* may appear. Names may be appearance-based (`FONT_MD`, `COLOR_MUTED`) — they *are* the palette.
2. **Semantic constants** — full stylesheet strings composed *from tokens*, named by **role**
   (`STATUS_OK`, `LOADING_TEXT`), never by appearance (no `TEXT_SM`/`GREY_11`).

Strict vs. conventional (this is what the audit checks):
- **Colors are strict — never inline a hex/rgba literal** (widget code *or* a semantic constant); always
  a `COLOR_*`/`OVERLAY_*` token, including dynamic styles (`f"color: {_theme.COLOR_WARN};"`). Codebase has
  zero stray color literals — keep it that way.
- **Font sizes use `FONT_*` tokens — never `font-size: Npx`.** (Pre-rule inline px literals are migrating
  debt — B10-3 — not a license to add more.)
- **Structural-spacing `px` is fine inline** — `padding`/`margin`/`border-radius`/`setFixedWidth` have no
  token. Only colors and font-sizes must be tokens.
- A stylesheet string used by **>1 widget** must be a named role-based constant in `theme.py` (import
  `from metatv.gui import theme as _theme`; never copy-paste between files). Name by role so unrelated
  widgets don't couple; need a variant → add a new role constant, don't widen an existing one.

### Channel name processing — ingestion-only, never at render time
All name-derived fields (`detected_prefix`, `detected_quality`, `detected_region`, `detected_title`, `detected_year`) are computed at ingestion time by `update_detected_prefixes()` in `metatv/core/repositories/channel.py` and stored in the DB. **Never call `parse_channel_name()` in render-time display code** — read the `channel.detected_*` fields directly. The display layer must be a pure DB read.

```python
# Correct — render-time display uses stored fields
bare = channel.detected_title or channel.name   # fallback for channels not yet re-parsed
year_str = f" · {channel.detected_year}" if channel.detected_year else ""

# Wrong — parsing at render time
_p = parse_channel_name(channel.name)
year_str = f" · {_p.year}" if _p.year else ""
```

**Documented exception:** `_make_recommendation_item` (and `_make_channel_item`) in
`gui/epg_watchlist_mixin.py` (the EPG Discover / My-Channels cards) still call `parse_channel_name`
at render — they derive audio/lang chips, and
audio/lang have **no stored `detected_*` field** to read. This is the one accepted render-time parse;
the audit should not flag it. Every other surface reads stored fields (the EPG On-Now render was
migrated off `parse_channel_name` for exactly this rule).

### Lookup tables — single source of truth, no duplicates
Region/country codes, quality tokens, audio format maps, and similar lookup data must live in exactly one place. The canonical location for channel-name parsing data is `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, etc.). All other modules (GUI, details pane, sidebar) must import from there — never define their own parallel dicts.

If you need to add a new code or alias, add it to `channel_name_utils.py` only. Never copy the dict into a second file.

### Tags/facets — capture generously, label confidence + provenance, never suppress (DR-0006)
In the guessing zone, **bias to recall: capture more, not less** — a false negative is invisible +
unfixable; a false positive is visible + one-click-correctable (and teaches the system). Witness, not
cage. Full rationale + the worked example set: DESIGN_RATIONALE **DR-0006**. The enforceable rules:
- A feeder yields the facet it **denotes** (high confidence) **plus** any *real* adjacent guess (low) —
  both captured, never withheld, never asserted as fact (`FR` → `language:French` high + `region:France`
  low). But a **real candidate must exist**: `EN` → `language:English` only (no place "EN" to guess). A
  confident signal **overrides** a prior; `LAT` = `language:Latin American Spanish` (distinct, never
  merged into `Spanish`).
- **Confidence = ranking + prune-priority, NEVER a suppression gate** — low-confidence tags still surface.
- **Every tag records its feeder + read-vs-inference**; the UI distinguishes source-given vs
  ingestion-inferred — those labels ship *with* the capture, not someday.
- **Hierarchy is rollup, not auto-tagging:** `LAT` ⊂ `Spanish` is certain containment; a `region:Mexico`
  channel never silently gains `language:Spanish`.

The decomposer (`tag_decomposer.py`) is the chokepoint; curated code→facet + base-confidence data lives in
`channel_name_utils.py` (single source of truth).

### Icons — always from `metatv/gui/icons.py`, never hardcoded
Every icon, emoji, or symbol displayed in the UI must come from `metatv/gui/icons.py`, never a literal in widget or layout code. This includes media-type icons, action icons (play, close, delete, hide), section header icons, folder/season indicators, status badges — everything.

```python
# Correct
from metatv.gui import icons as _icons
rm_btn = QPushButton(_icons.close_icon)

# Wrong — hardcoded literals or old Config references
rm_btn = QPushButton("×")
rm_btn = QPushButton(self.config.close_icon)
```

If you need an icon that doesn't exist yet, add it to `icons.py` first, then reference it. **Never add icon glyphs to `Config`** — Config is for user-configurable settings, not presentation constants.

**Note:** existing code still uses `config.<name>_icon` — that is legacy being migrated incrementally. New code must use `icons.*`.

**Collapse/expand buttons specifically:** use `icons.expand_icon` (collapsed state) and `icons.collapse_icon` (expanded state) — never `icons.move_up_icon` / `icons.move_down_icon`, which are list-ordering arrows. For top-level collapsibles, subclass `CollapsibleSection` — it handles the button, state, and persistence automatically. For inner/nested collapsibles:
```python
from metatv.gui import icons as _icons
btn = QPushButton(_icons.collapse_icon)  # start expanded
# on toggle:
btn.setText(_icons.expand_icon if collapsed else _icons.collapse_icon)
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

### ORM objects must not outlive their session — cross the boundary with a DTO
**Intent, not taboo:** an ORM object (`ChannelDB`, …) is a *live handle* bound to its session — it
lazy-loads or raises the instant that session closes. A **DTO** (frozen `@dataclass` in
`core/repositories/dtos.py`) is an immutable *value* — no session, no behavior — so it severs the
dependency, and **keeps the schema free to evolve** (add a `relationship()`/`deferred()` column)
without breaking the UI. Mechanically: `session_scope()` exits with `expire_on_commit=True`, so any
still-attached object's next attribute access raises `DetachedInstanceError`.

- **Cross the boundary with a DTO.** Map ORM → frozen dataclass/dict *inside* the block and return that
  (`_run_query` enforces "never return ORM objects"). Hot paths done: play/details
  (`PlayableChannelDTO`/`PlayableEpisodeDTO`, B10-1), channel list (`ChannelListDTO`, B10-5). No ORM
  crosses worker→main anymore — keep it that way for every new cross-boundary read.
- **`session.expunge(obj)` is a fragile fallback, not a default** — only safe while the model has no
  `relationship()`/`deferred()` column (add one and every expunge site silently regresses). Reach for a
  DTO; if you keep an expunge site, you own auditing it.
- **`_apply_favorite_toggle` is the documented exception** — legacy `try/finally` because
  `toggle_favorite()` commits internally and `session.refresh()` repopulates *before* close;
  `session_scope`'s exit-commit would re-expire after the refresh. Don't "modernize" it blindly.

### SQLite JSON columns — use `JSONEncoded`, assign plain Python objects
JSON-like columns use `Column(JSONEncoded)` (defined in `database.py`), a `TypeDecorator` over `Text` that serializes transparently. Assign and read plain Python objects — no `json.dumps/loads` needed:

```python
metadata.cast = result.cast          # assign a list — JSONEncoded handles serialization
cast = metadata.cast or []           # read back a list — no json.loads needed
```

Never do `json.dumps(value)` before assigning to a `JSONEncoded` column — that double-encodes.

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

### EPG times — single conversion boundary in `epg_utils.py`
`EpgProgramDB.start_time` / `stop_time` are stored as UTC-naive datetimes. **Never open-code timezone conversions inline.** Use the helpers from `metatv/core/epg_utils.py`:

```python
from metatv.core.epg_utils import to_local, is_local_today, local_weekday, local_day_window, now_utc

# Display: convert to local tz-aware datetime
local = to_local(prog.start_time)         # tz-aware local datetime

# Today check (correct for any timezone)
if is_local_today(prog.start_time): ...   # replaces .date() == date.today()

# Weekday label (correct for any timezone)
day = local_weekday(prog.start_time)      # replaces .strftime('%a')

# Date-picker window (EPG browse)
day_start, day_end = local_day_window(target_date, tz=_local_tz())

# Current time for arithmetic comparisons
now = now_utc()                           # replaces datetime.now(timezone.utc).replace(tzinfo=None)
```

**Never compare `.date()` directly against `date.today()`** — the naive date is UTC-anchored and wrong for non-UTC users. Never open-code `.replace(tzinfo=timezone.utc).astimezone()` outside `epg_utils.py`.

For arithmetic (remaining time, progress bars), compare UTC-naive against `now_utc()` — no conversion needed.

### EPG concurrent fetches — one worker at a time
`EpgManager` uses `ThreadPoolExecutor(max_workers=1)`. Running two XMLTV fetches concurrently causes SQLite `database is locked` errors because each fetch does a bulk-delete + bulk-insert. Providers are fetched sequentially; the second queues behind the first.

### Per-provider EPG configuration — `epg_enabled`, `epg_refresh_interval`, `epg_url_override`
Each `ProviderDB` row carries three EPG columns: `epg_enabled` (bool; when `False` the provider is
skipped by the fetcher, excluded from EPG/watchlist surfaces via `get_epg_active_provider_ids()`,
and its programmes are purged via `EpgManager.purge_provider_epg()`), `epg_refresh_interval`
(String enum; `"default"` inherits `Config.epg_default_refresh_interval` which defaults to `"3d"`;
throttle logic lives in `EpgManager.needs_refresh()`), and `epg_url_override` (optional XMLTV URL;
the effective fetch URL is resolved by `EpgManager.effective_epg_url(provider)` = override-or-auto).
Never read `provider.epg_url` directly as the fetch URL — always go through `effective_epg_url`.

### Context filter chips — details-pane metadata clicks → strict channel list filter
When a user clicks a metadata value in the details pane (genre, cast, director, etc.) a
temporary "context filter" activates. This uses a **strict SQL filter** — not the filter
panel's inclusive genre logic (which has a no-data passthrough). The full pattern is in
[docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md). Key rules:
- Never route details-pane clicks through `filter_panel.select_only_genre()` or similar — the filter panel is inclusive, context chips are strict.
- At most one context filter is active at a time; activating any chip clears all others.
- Text search and an active chip coexist — typing narrows *within* the chip filter; it does NOT dismiss the chip.
- All chip styles come from `theme.CONTEXT_FILTER_CHIP*` constants — no inline hex.
- State lives in `_details_*_filter` vars on `MainWindow`; passed through `load_channels()` params → `get_all()`.

### Channel context menus — compose through `channel_menu.py`, never hand-roll a `QMenu`
Every channel context menu (the channel list, History, Favorites, sidebar Queue/Recommended/Alerts/
Retry, multi-select, and EPG On-Now/Browse) is built by the **unified registry** in
`metatv/gui/channel_menu.py`: `ChannelMenuContext` + the `ACTIONS` registry + `SURFACE_LAYOUTS` +
`build_channel_menu(ctx, handlers, parent)`. This replaced ~9 hand-rolled, drifting menus — **do not
regrow them.**

- To add an action: define it once in `ACTIONS` (label/icon/tooltip/`applies`) and list its id in the
  relevant `SURFACE_LAYOUTS` entry; supply a handler in the call site's `handlers` dict. An action id
  absent from a site's `handlers` is silently skipped — that is how surfaces opt in/out.
- The MainWindow family gathers context **off-thread** through the single `_show_channel_menu` seam
  (`_bg_fetch_ctx_data` → `_ctx_data_ready` → `_on_ctx_data_ready`). New MainWindow-family menus go
  through it, not a bespoke `executor.submit` + inline `QMenu`.
- EPG/Preferences views build locally via `build_channel_menu` and delegate **core** handlers (play /
  favorite / queue / rate) to the MainWindow host (`self.window()`), supplying their own extras.
- Never construct a `QMenu` of channel actions by hand. (Non-channel menus — filter dropdowns, column
  headers, details chips — are out of scope and stay as-is.)

### Player instance keying — thread `provider_id`; never bypass `PlayerManager`
mpv runs as a **per-source instance registry** (Split Streams). `PlayerManager.play(url, title,
provider_id=…, force_new_window=…)` resolves the instance key — `"__shared__"` when split is off, the
`provider_id` when `config.split_streams_by_source` is on or when `force_new_window=True` — and
`MPVPlayer` owns the `dict[key → _Inst]`.

- Every play path **must thread the channel's `provider_id`** through: `play_media(channel, …)` →
  `_bg_validate_and_play` → the `_stream_ready` payload → `_on_stream_ready` →
  `player_manager.play(provider_id=…)`. A play path that drops `provider_id` breaks Split Streams.
- `is_running` / `stop` / `get_properties` / `active_keys` all go through `PlayerManager(..., key=…)`.
  Never reach into `MPVPlayer`'s process/socket directly or hardcode an instance.
- `force_new_window=True` is how "Play in New Window" opens a per-source window regardless of the
  toggle. `config.split_streams_by_source` is the only user toggle.

### EPG `channel_name` must be populated at fetch — the relink depends on it
`EpgProgramDB.channel_name` stores each programme's XMLTV **display-name**, written at fetch time
(`_fetch_worker` builds `chan_name_map` from the parsed channels). The DB-only
`EpgManager.relink_all()` re-matches existing rows against the current channel table — using this name
for the **fuzzy** match tiers — which is what makes the watchlist / Watch-Alerts populate **without a
manual Refresh** (channel matching is rebuilt on EPG activation + after channel loads).

- **Never stop populating `channel_name`** at fetch. Without it the relink loses fuzzy matching and
  the "watchlist empty until you click Refresh" bug returns.
- Legacy rows lacking a name trigger a one-time re-fetch via
  `EpgRepository.has_unmatched_unnamed_epg()`; relink reuses `_build_match_map` (all three tiers) and
  emits `refresh_finished` so the views reload.

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

### Modal/overlay views driven by sidebar actions must hide on all view switches
When creating a new modal/overlay view (e.g., provider analytics, settings) that is stacked in `_list_layout` and **triggered by sidebar buttons (not chip navigation)**, you must:
1. Add the view to `_hide_all_content_views()` to call `on_deactivate()` if visible, then hide it
2. Check for the view's existence using `"view_name" in self.__dict__` (safe for mocked test objects)
3. Wire an entry method (e.g., `enter_analytics_mode()`) that calls `_hide_all_content_views()`, shows the view, and calls `on_activate()`
4. Wire an exit method that calls `on_deactivate()` and returns to list view

This ensures the view clears when users navigate away via chips (Search, EPG, Discover) or other views, preventing the modal from lingering on screen and consuming async loads.

### Dialog/editor views must notify dependent views when data changes
When a modal dialog or editor view modifies data that's displayed in other parts of the UI (e.g., sidebar, list, details pane), emit a signal that triggers those views to refresh their display. This prevents stale, out-of-sync visualizations.

**Pattern:**
```python
# In the editor view:
account_info_updated = pyqtSignal(str)  # provider_id

def _persist_changes(self, data):
    # ... update database ...
    self.account_info_updated.emit(self._provider_id)  # notify dependents

# In MainWindow:
self.editor.account_info_updated.connect(self._on_account_info_updated)

def _on_account_info_updated(self, provider_id: str):
    sidebar_section = self.sidebar_sections.get("sources")
    if sidebar_section:
        sidebar_section.refresh()  # refresh display
```

**Example:** ProviderEditorView refreshes the account info from the API and persists it; emits `account_info_updated` so the Sources sidebar can update its color-coded subscription status display.

### Provider/source mutations → one canonical refresh, never hand-pick views
Every view derived from the provider/channel corpus must be refreshed through the
**single** method `MainWindow._refresh_provider_dependent_views()`. It refreshes the full
set: sidebar Sources/Favorites/History/Queue/Recommended, the main channel list/search
(which also rebuilds `provider_icon_map`), and the lazy Discover/Preferences overlay views.

**All** provider mutations funnel through it — add (`on_provider_refresh_finished`), edit
(`_on_provider_saved`), delete (`_on_provider_deleted`), toggle active
(`toggle_provider_active`) / visibility (`toggle_provider_visibility`). **Never** re-implement
a partial refresh at a call site (e.g. `load_providers()` alone). That hand-picking is a
recurring bug class: it repeatedly left views stale — most visibly, editing a source's icon
refreshed the sidebar but not the main list, so a new source showed its content with no icon
badge. If you add a new provider-mutation path or a new corpus-derived view, wire it through
(or into) this method — don't grow a new partial path. The account-info poll
(`_on_account_info_updated`) is the one deliberate exception: it changes only the Sources
display, not the channel set, so a sidebar-only refresh is correct there.

### Active-source scoping → one helper, never hand-pick (history/engaged are the exception)
Content from **inactive (toggled-off) or expired** sources must never appear in a
forward-looking view. The single source of truth is
`ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired). Every "what can I
watch" query passes it as `excluded_provider_ids`: the channel list (`_bg_load_channels`),
Discover shelves + See-All (`discover_workers`), and recommendations
(`preference_engine.score_candidates`, called from the Recommended sidebar section and the
Preferences dashboard). EPG scopes equivalently (`is_active=True` + expired) in
`_load_provider_ids`.

The **include-list sibling for EPG/watchlist surfaces** is
`ProviderRepository.get_epg_active_provider_ids()` (= `is_active` ∧ not-expired ∧ has
`epg_url` ∧ `epg_enabled`). Used by the Alerts "WATCH NOW" group and
`epg_view._load_provider_ids` — pass its result as `provider_ids` to watchlist and EPG
programme queries; never hand-roll this filter at a call site.

Do **not** rebuild this set ad-hoc at a call site (e.g. `get_expired_provider_ids()` alone —
that was the bug: disabled-but-unexpired sources leaked into Discover and recommendations).
If you add a new content-surfacing view or a new query in the engine, thread
`excluded_provider_ids=get_hidden_provider_ids()` through it.

**The exception is record/engaged views — History, Favorites, Watch Queue — which show prior
engagement regardless of a source's current state** (you watched it; the source going
inactive doesn't erase that). This mirrors the engaged-content prune rule (a different
source going away keeps its favorites/queue/history as context). Recommendation
*weights* likewise still learn from engaged items on now-inactive sources; only the candidate
*pool that gets surfaced* is scoped to active sources.

### The data engine is preference-free — assumptions live in the control layer (DR-0007)
Three layers, one-way dependency: **engine ← control ← view.** The **engine** (faceted/aggregate query
primitives) is **completely agnostic** — scoped inputs in, data out, no assumptions about what's
visible or how data is encoded. Every "what should be visible / what `##` means" decision is a
human-factor assumption (**view preference**: `is_hidden`, exclusions, adult mode; or **content
preference**: provider-encoding convention) and lives in the **data-aware control layer**, never the
engine. *Full why + the split: DR-0007.*
- **Never re-inline a visibility/scoping predicate.** Be scope-agnostic like
  `get_channel_ids_by_tag_facets` (caller supplies `base_channel_ids`); use the shared
  `visible_channel_filter` / `get_hidden_provider_ids()`. A copied WHERE-fragment is a missing
  chokepoint; a *subset* copy mis-counts. *(Live debt — `is_hidden`/`##%`/`NO EVENT` smeared across
  channel/stats/analytics/tag; don't widen it. Task #59; audit lens #4 greps the predicate fragment.)*
- **Content-format guesses are ingestion-only** — resolve `##`/placeholder at ingest into a stored
  field; never re-pattern-match in queries (same violation as render-time `parse_channel_name`).

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

### `_run_query` — the required pattern for new background DB reads
`_AsyncMixin` (`metatv/gui/main_window_async.py`) is the single reusable async-read seam on
`MainWindow`. **All new background DB reads use it** — never ad-hoc `executor.submit` + manual signals.

```python
self._my_token: list[int] = [0]   # optional: lets later calls supersede earlier ones

def _load_something(self) -> None:
    self._run_query(
        lambda repos: repos.channels.get_favorites_dto(),   # off-thread; returns plain data
        self._on_something_loaded,                           # main thread
        token_ref=self._my_token,                            # optional stale-drop guard
    )

def _on_something_loaded(self, rows: list) -> None:          # MAIN THREAD — widget access safe
    self._populate_list(rows)
```

- `query_fn(repos)` **must return plain data** (frozen DTOs / primitives / dicts), never ORM objects
  (see the ORM→DTO rule). It runs in a **read-only** `session_scope(commit=False)` — writes are
  discarded, not persisted.
- `token_ref` cancels superseded in-flight calls (e.g. view switches); omit for order-independent fetches.
- If the caller shows a placeholder, pass `on_error` (main thread, gets the exception) — your only
  chance to clear it, else the spinner hangs forever. Always reuse `self.executor`, never a per-call pool.

**Sidebar `CollapsibleSection`s can't reach the seam — compose `BackgroundRefreshMixin`** instead
(`metatv/gui/sidebar/background_refresh.py`, B8-5). Don't hand-roll the executor/signal/`_bg_refresh`/
`_on_data_ready`, and don't invent a third shape:

```python
class MySection(BackgroundRefreshMixin, CollapsibleSection):
    _data_ready = pyqtSignal(object)          # list[DTO] | None   (None = load failed)

    def __init__(self, ...):
        super().__init__(...)
        self._init_background_refresh()       # owns _executor + signal wiring
    def _refresh_list(self):       return self._list          # the QListWidget
    def _load_error_message(self): return "Couldn't load …"
    def _load_rows(self):                                      # worker — NO widget access
        with self.db.session_scope() as session:
            return build_dtos(RepositoryFactory(session))
    def _populate_rows(self, data): ...                        # main thread, list pre-cleared
```

The mixin owns `refresh()` / `_bg_refresh()` (→ `emit(None)` on failure) / `_on_data_ready()` (clear →
`None` shows `show_load_error`, else `_populate_rows`).
- `max_workers=1` is required (SQLite-lock rule) and makes rapid `refresh()`es converge (FIFO +
  clear-first = last-write-wins) — so **no `token_ref` needed**. `MainWindow` auto-registers each
  section's `_executor` by that exact name for shutdown — don't rename it.
- **`RecommendedSection` is the documented exception** — its `None` is a valid empty state, not a
  failure, and it emits a `(recs, year_by_id)` tuple.

### Background refresh failure must be visible — never silently blank a list
A background DB read that backs a list/section **must not** make failure indistinguishable from an
empty result. On the `None`/error branch of `_on_data_ready`, render a distinct, non-selectable
error row — use `CollapsibleSection.show_load_error(list_widget, "Couldn't load …")` (it adds an
`icons.notification_warning_icon` row and keeps the section expanded). Never just `clear(); return`
on failure: an empty styled "you have nothing here" state is a lie when the query actually threw.
This mirrors the `on_error` placeholder rule for `_run_query` (e.g. EPG's "count unavailable").

### Async-read tests — pin the main-thread half, and never claim coverage you didn't write
For any off-thread read (`_run_query` or the sidebar sibling pattern), the worker half (`_bg_refresh`
/ `query_fn`) is the *boring* half — a try/except around a repo call. The half that regresses is the
**main-thread `on_result` / `_on_data_ready`**: sorting, the continue-vs-never split, icon mapping,
episode-code rendering, the empty state, and the failure row. Test it directly — construct the
widget via `__new__`, hand it a real `QListWidget` (the module `qapp` fixture makes this headless)
or a `_FakeLabel`, call the slot, assert the rendered rows. A test docstring must not list an
invariant (e.g. "`_on_data_ready` populates correctly") that no assert actually checks — describing
unwritten coverage is worse than silence, because the next reader trusts it and the gap calcifies.

### Tests must prove behavior, not shape — no zero-result busy work
A test that asserts a string exists in source (`"session_scope" in func`, `"session.expunge" in
src`), that a method is named a certain way, or that an attribute is present, proves *shape*. Shape
tests are cheap insurance against a careless edit, but **a green shape suite is not coverage** — it
will stay green through the exact regression it appears to guard. The rule:

- **Every behavior-changing PR must include at least one test that executes the changed code path
  and asserts the outcome that would actually break.** For the B7-6 session migration that is:
  drive the real handler against a real in-memory `Database` (`create_tables()` on a `tmp_path`
  file — not `:memory:`, whose pooled connections each get an empty DB), let the scope close, then
  assert a detached column is still readable. The substring/AST tests may stay *alongside* it; they
  may not stand *in place of* it.
- **Never write a test (or a docstring) whose only effect is to look like coverage.** If you cannot
  articulate the concrete regression a test would catch, the test is busy work — delete it or
  replace it with one that can. Padding a count ("11 new tests") with shape assertions that pin
  nothing is the failure mode this rule exists to stop.
- This generalizes the async-read rule above: find the half that regresses and execute it.

### Tests must never write the real user config — isolation is enforced in conftest
`Config.config_dir` / `data_dir` / `cache_dir` default to `Path.home()/…` and `Config.load()` /
`Config.save()` read/write `~/.config/metatv/config.yaml`. A test that builds a **default** `Config()`
and saves (directly, or via a handler that calls `config.save()` — e.g. the On-Now header-state test)
therefore **overwrites the developer's real config**, silently wiping Global Exclusions, the
What's-New cursor, and the migration version fields. The running app then re-runs migrations,
re-shows old What's New, and loses curation. This was a real, repeated bug — it looked like flaky
data loss but was the test suite clobbering live config.

The guard: the **autouse `_isolate_user_config` fixture in `tests/conftest.py`** monkeypatches
`Path.home()` to a throwaway tmp dir for **every** test, so touching the real config is structurally
impossible. Rules:
- **Never remove or weaken that fixture**, and never `monkeypatch.undo()` it inside a test.
  `tests/test_config_isolation.py` fails if it regresses — keep it green.
- A test that genuinely needs a config on disk passes `config_dir=tmp_path` explicitly (belt **and**
  braces); it must never rely on — or write to — the default home path.
- More broadly: **no test may write outside its tmp dirs.** Anything deriving a path from
  `Path.home()` and writing to it is suspect; route it through a fixture-provided tmp location.

### Scope discipline & curiosity — ask before generating debt
The Critical Rules and the active Refactor Plan (`docs/REFACTOR_PLAN_BAND*.md`) define the
architecture and the scope of each task. They override convenience. Before you reach for a shortcut
that sidesteps an established pattern (returning an ORM object instead of a DTO, hand-rolling an
async path instead of the seam, hardcoding a literal instead of a token, tightening a heuristic the
docs call a deliberate compromise):

- **Re-read the relevant rule and the plan item first.** Most "I'll just…" shortcuts are already
  ruled out in writing. If a rule's premise has drifted from the code, say so and adapt — don't
  silently ignore it.
- **Stay inside the task's scope.** One concern per PR. If you discover a larger problem mid-task,
  do **not** expand the PR to fix it and do **not** paper over it — record it in the Band plan as a
  new item and keep moving. Quietly accreting unrelated changes or tech debt is worse than a
  focused PR that names what it deferred.
- **When the correct path is genuinely unclear, ask.** A short "the rule says DTOs but this handler
  passes an ORM object across the boundary — convert it, or is there a reason it's exempt?" is
  always preferable to inventing a third pattern. Curiosity and a clarifying question cost one
  message; an undiscussed architectural shortcut costs a review cycle and a follow-up band.

### Reuse before reinvent — find the existing path before adding a sibling
**The proactive form of the chokepoint rules.** Before writing a new function / handler / view / play
path, **search for code that already does the same or an overlapping operation** and route through (or
extend) it. Add a parallel path only with a real, durable difference named — and even then factor the
shared core into one place both call. *(War story + the redundancy audit lens live in
`docs/AUDIT_2026-06-19.md` + memory `feedback_reuse_before_reinvent`: `play_special_event` was a
strictly-worse duplicate of `play_media` that silently dropped failover / buffering / the health
readout, then rotted as every fix landed only on the canonical path.)*

- **Grep the verb-cluster AND the primitive** (`play_*`/`load_*`/`refresh_*`/`fetch_*`/`_on_*_ready`,
  plus the repo/manager method or `session_scope`/seam you're about to call) before writing a new one.
- **A core primitive called from >1 UI site is a chokepoint smell** — one entry, every caller gets the
  full behavior. `play_media` + its thin `*_id` wrappers is the model; the episode path is the one
  justified exception and still *shares* the play side-effects.
- **Need a variant? Share the core** (one helper both call), never copy-paste-and-trim. Must reinvent?
  Make the case in the PR.
- **Semantic duplication is invisible to syntactic greps** — read behavior; the audit runs a redundancy
  lens (cluster by verb, list each primitive's call sites, ask "is one a subset?").

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) must save to config and restore on startup. Pattern: save immediately on change, restore during `__init__`. See `DESIGN.md` for the full pattern.

## Metadata Provider Chain

Providers tried in priority order until sufficient data found:
1. `ProviderMetadataProvider` — extracts from Xtream `raw_data` (always try first, zero latency)
2. `TMDbProvider` — not yet implemented
3. `OMDbProvider` — not yet implemented

`MetadataResult.merge()` uses confidence scores (0.0–1.0) to prefer higher-quality data per field.

### Year derivation happens at ingestion — read `.year` directly everywhere else

`MetadataDB.year` is populated at write time by `MetadataManager._derive_year()` — at ingestion
(`_save_metadata_cache`, extracting from `release_date` when `year` is absent) and again on read
(`_metadata_db_to_result`, backfilling pre-fix rows). So **read `metadata.year` directly everywhere**
(display, dedup, scoring) — no runtime parsing, no fallback outside `metadata_manager.py`. `release_date`
keeps the full ISO string (e.g. "2024-07-03").

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
- User-facing changes must add a **new file** `metatv/whats_new/entries/NNNN_slug.py` (zero-padded id, e.g. `0016_my_feature.py`) with `ENTRY = WhatsNewEntry(...)` — never edit the shared list. Run `python -c "from metatv.whats_new import latest_id; print(latest_id() + 1)"` to confirm the next id. See `metatv/whats_new/entries/README` for the full format. This zero-conflict pattern replaces the old single-file append.

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
| **Product vision & direction (north star)** | [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) |
| UI/UX interaction patterns | [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) |
| Qt threading deep dive | [docs/THREADING_PATTERNS.md](docs/THREADING_PATTERNS.md) |
| Metadata system architecture | [docs/METADATA_SYSTEM.md](docs/METADATA_SYSTEM.md) |
| Filtering design | [docs/FILTERING_DESIGN.md](docs/FILTERING_DESIGN.md) |
| Context filter chips (genre/person/future) | [docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md) |
| Details pane design | [docs/DETAILS_PANE_DESIGN.md](docs/DETAILS_PANE_DESIGN.md) |
| Xtream API schema | [docs/xtream_api_schema.md](docs/xtream_api_schema.md) |
| UI state persistence patterns | [DESIGN.md](DESIGN.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Refactor / dedup / cleanup plan | [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md) |
| Band 6 plan (P3 remainder + P4 + PR #6 review follow-ups) | [docs/REFACTOR_PLAN_BAND6.md](docs/REFACTOR_PLAN_BAND6.md) |
| Band 7 plan (responsiveness seam + finish decomposition) | [docs/REFACTOR_PLAN_BAND7.md](docs/REFACTOR_PLAN_BAND7.md) |
| Sonnet execution prompt for Band 7 | [docs/SONNET_EXECUTION_PROMPT_BAND7.md](docs/SONNET_EXECUTION_PROMPT_BAND7.md) |
| Band 8 plan (seam cleanup + BackgroundRefreshMixin + deferred items) | [docs/REFACTOR_PLAN_BAND8.md](docs/REFACTOR_PLAN_BAND8.md) |
| Band 9 plan (load_channels seam + expunge→DTO + EPG cosmetics) | [docs/REFACTOR_PLAN_BAND9.md](docs/REFACTOR_PLAN_BAND9.md) |
