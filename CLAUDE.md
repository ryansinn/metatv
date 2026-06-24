# MetaTV — Claude Code Project Guide

## What This Is

MetaTV is a Python/PyQt6 IPTV client. It connects to Xtream API providers, caches channel data in SQLite, and plays streams via mpv. UI: three-panel layout — sidebar (sources/favorites/history), channel list, details pane.

**Run it:** `./run.sh` or `venv/bin/python -m metatv`

## Architecture

`core/` business logic (no UI deps) · `gui/` PyQt6 widgets · `providers/` IPTV source plugins · `metadata_providers/` enrichment plugins. Full directory map + per-file responsibilities: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Data locations:** config `~/.config/metatv/config.yaml` · db `~/.local/share/metatv/metatv.db` · logs `~/.config/metatv/logs/` · image cache `~/.cache/metatv/images/`.

## Governing Principles

Most Critical Rules below are instances of two ideas. When a rule states one of these, it's applying the principle — not re-deriving it.

1. **Single chokepoint / one source of truth.** For any recurring operation (play, refresh, async DB read, name parsing, scoping filters) and any palette/lookup data (colors, icons, region codes), there is one canonical path or definition. Route through it; never hand-roll a parallel one. Need a variant → extend the shared core (one helper both call), don't copy-and-trim.
2. **Compute once at ingestion, read everywhere else.** Name-derived fields, year, and content-format guesses are resolved at write time into stored fields. Display, query, and scoring code reads the stored field — never re-parses at runtime.

If a rule's premise has drifted from the code, say so and adapt — don't silently ignore it. When the correct path is genuinely unclear, ask: a one-line clarifying question beats inventing a third pattern.

## Critical Rules

### EPG time & timezone — always via `epg_utils.py`
All EPG time helpers (`now_utc`, `fmt_time`, `remaining_str`, `minutes_away`, `progress_pct`, `fmt_duration`, `epg_is_stale`, `to_local`, `is_local_today`, `local_weekday`, `local_day_window`) live in `metatv/core/epg_utils.py`. Never redefine inline; never open-code timezone conversions.

- `EpgProgramDB.start_time` / `stop_time` are UTC-naive. Display → `to_local`. "Today"/weekday → `is_local_today` / `local_weekday` (never `.date() == date.today()`, which is UTC-anchored and wrong for non-UTC users). Arithmetic (remaining, progress) → compare UTC-naive against `now_utc()`.
- `epg_is_stale(epg_data_end)` is the single staleness boundary (a feed serving year-old guide data). The EPG view's banner list comes from `ProviderRepository.get_stale_epg_providers()`.

### Styles — two-layer `theme.py`; tokens for every palette/font-size value
Full rationale: [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) → "Theming & style tokens". Two layers:

1. **Design tokens** (`COLOR_*`, `FONT_*`, `OVERLAY_*`) — the only place a raw hex/rgba literal or a font *size* may appear.
2. **Semantic constants** — full stylesheet strings composed from tokens, named by **role** (`STATUS_OK`, `LOADING_TEXT`), never by appearance.

- **Colors strict:** never inline a hex/rgba literal anywhere, including dynamic styles (`f"color: {_theme.COLOR_WARN};"`); always a `COLOR_*`/`OVERLAY_*` token. The codebase has zero stray color literals — keep it that way.
- **Font sizes:** `FONT_*` tokens, never `font-size: Npx`.
- **Structural-spacing px is fine inline** — `padding`/`margin`/`border-radius`/`setFixedWidth` have no token.
- A stylesheet string used by **>1 widget** must be a named role-based constant (`from metatv.gui import theme as _theme`); never copy-paste between files. Need a variant → add a new role constant, don't widen an existing one.

### Channel-name fields — computed at ingestion, read at render
All `detected_*` fields (`detected_prefix`, `detected_quality`, `detected_region`, `detected_title`, `detected_year`) are computed at ingestion by `update_detected_prefixes()` in `metatv/core/repositories/channel.py` and stored. **Never call `parse_channel_name()` in render-time display code** — read `channel.detected_*` directly.

```python
# Correct — render reads stored fields
bare = channel.detected_title or channel.name
year_str = f" · {channel.detected_year}" if channel.detected_year else ""

# Wrong — parsing at render time
_p = parse_channel_name(channel.name)
```

**One accepted exception:** `_make_recommendation_item` / `_make_channel_item` in `gui/epg_watchlist_mixin.py` still parse at render to derive audio/lang chips — there is no stored `detected_*` field for those. The audit does not flag this; every other surface reads stored fields.

### Content identity — one stored `content_key`, computed at ingestion, collapsed at read (DR-0009)
Cross-source dedup has **one identity field**, not a per-surface heuristic. `content_key` is computed at ingestion by `content_identity.content_key_for()` inside `update_detected_prefixes()` and stored (indexed) on `ChannelDB`. Full spec: [docs/CONTENT_IDENTITY.md](docs/CONTENT_IDENTITY.md); rationale: DR-0009.

- **Compute once, read everywhere** (same rule as `detected_*`): the key is `{norm_title}|{media_type}` for series/live (year dropped — provider year labels are noisy) and `{norm_title}|movie|{start_year}` for movies. Director + metadata-year are excluded (unavailable at ingest). Never re-derive a dedup key at query/render time.
- **Collapse reads the stored key — never a parallel heuristic.** Browse/Recipe Show-All + tag counts collapse via `tag.py`'s `collapse_variants` path (`_build_collapsed_sample_query` window functions / `COUNT(DISTINCT …)`); Discover via `discovery_engine._dedup_cards`; details "Other Versions" via `content_key ==`. Adding a new browse/shelf/count surface → route through one of these, don't write a third dedup.
- **NULL-guard is mandatory:** group on `COALESCE(content_key, 'id:' || id)`. A bare `PARTITION BY content_key` merges every un-backfilled NULL row into one phantom group.
- **Phase 2 exception:** Recommendations + the Similar lightbox still use the richer runtime fingerprint in `content_dedup.py` (includes director) — don't "unify" them onto `content_key` without the deliberate re-base wave (DR-0009).

### Lookup tables — single source of truth
Region/country codes, quality tokens, audio-format maps, and channel-name parsing data live only in `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, …). All other modules import from there — never define parallel dicts. A new code or alias goes in `channel_name_utils.py` only.

### Tags/facets — capture generously, label confidence + provenance (DR-0006)
In the guessing zone, bias to recall: a false negative is invisible and unfixable; a false positive is visible and one-click-correctable (and teaches the system). Full rationale + worked examples: DESIGN_RATIONALE **DR-0006**. Enforceable rules:

- A feeder yields the facet it **denotes** (high confidence) **plus** any *real* adjacent guess (low) — both captured, never withheld (`FR` → `language:French` high + `region:France` low). A real candidate must exist: `EN` → `language:English` only. A confident signal overrides a prior (`LAT` = `language:Latin American Spanish`, never merged into `Spanish`).
- **Confidence = ranking + prune-priority, never a suppression gate** — low-confidence tags still surface.
- **Every tag records its feeder + read-vs-inference**; the UI ships source-given vs ingestion-inferred labels *with* the capture.
- **Hierarchy is rollup, not auto-tagging:** `LAT ⊂ Spanish` is certain containment; a `region:Mexico` channel never silently gains `language:Spanish`.

Chokepoint: `tag_decomposer.py`. Curated code→facet + base-confidence data: `channel_name_utils.py`.

### Icons — always from `metatv/gui/icons.py`
Every icon/emoji/symbol in the UI comes from `icons.py`, never a literal in widget code (media-type, action, header, status — everything).

```python
from metatv.gui import icons as _icons
rm_btn = QPushButton(_icons.close_icon)   # not "×", not self.config.close_icon
```

Need a new icon → add it to `icons.py` first. Never add glyphs to `Config` (settings, not presentation constants).

**Collapse/expand specifically:** `icons.expand_icon` (collapsed) / `icons.collapse_icon` (expanded) — never the `move_up_icon`/`move_down_icon` list-ordering arrows. Top-level collapsibles: subclass `CollapsibleSection` (handles button/state/persistence). Inner/nested collapsibles toggle the button text manually:
```python
btn = QPushButton(_icons.collapse_icon)  # start expanded
btn.setText(_icons.expand_icon if collapsed else _icons.collapse_icon)
```

### Logging — always loguru
```python
from loguru import logger   # correct
import logging              # never
```

### Database sessions — `session_scope()` for new code
`Database.session_scope()` commits on success, rolls back on exception, always closes:
```python
with self.db.session_scope() as session:
    repos = RepositoryFactory(session)
```
A bare `with session:` manages only the *transaction*, not cleanup — never use it. (Legacy `get_session()` + `try/finally` remains in old code — see Migration Status.)

### ORM objects must not outlive their session — cross the boundary with a DTO
`session_scope()` exits with `expire_on_commit=True`, so a still-attached ORM object's next attribute access raises `DetachedInstanceError`. A frozen DTO (`core/repositories/dtos.py`) is a session-free *value* — it severs the dependency and keeps the schema free to add a `relationship()`/`deferred()` column without breaking the UI.

- Map ORM → DTO/dict *inside* the block and return that (`_run_query` enforces "never return ORM objects"). No ORM crosses worker→main.
- `session.expunge(obj)` is a fragile fallback (regresses the instant a `relationship()`/`deferred()` column is added) — prefer a DTO; if you keep an expunge site you own auditing it.
- `_apply_favorite_toggle` is the documented exception: `toggle_favorite()` commits internally and `session.refresh()` repopulates *before* close, so `session_scope`'s exit-commit would re-expire. Don't "modernize" it blindly.

### SQLite JSON columns — `JSONEncoded`, assign plain Python objects
`Column(JSONEncoded)` (defined in `database.py`) serializes transparently. Assign and read plain objects — no `json.dumps/loads`. Never `json.dumps(value)` before assigning (double-encodes).
```python
metadata.cast = result.cast      # assign a list
cast = metadata.cast or []       # read a list back
```

### Qt threading — signals only; QPixmap on the main thread
Qt widgets are not thread-safe. Workers emit signals; only the main thread touches widgets.
```python
class MyWidget(QWidget):
    data_ready = pyqtSignal(object)
    def _worker(self):                 # thread — NO widget access
        self.data_ready.emit(fetch())
    def _on_data_ready(self, result):  # main thread — safe
        self.label.setText(result)
```
**QPixmap is a GUI object — create it only on the main thread.** Never `QPixmap(path)` in a `ThreadPoolExecutor`/`QThread` worker. Emit the *path string* cross-thread; build the pixmap in the main-thread slot.

### Signal blocking during UI state restoration
Block signals before programmatically setting widget state, then `.connect()` handlers in a separate pass — set every widget first (`blockSignals(True)` → set → `blockSignals(False)`), wire all handlers after, so restoring one widget doesn't fire another's slot.

### EPG notifications — never call NotificationManager from a worker thread
`NotificationManager.show()` creates an auto-dismiss `QTimer` — main thread only. In `EpgManager`, all worker notifications go through private signals (`_notify`, `_progress_update`, `_progress_done`, `_progress_error`) that Qt queues to the main thread.

### EPG concurrent fetches — one worker at a time
`EpgManager` uses `ThreadPoolExecutor(max_workers=1)`. Two concurrent XMLTV fetches cause SQLite `database is locked` (each does bulk-delete + bulk-insert). Providers fetch sequentially.

### Per-provider EPG config — `epg_enabled`, `epg_refresh_interval`, `epg_url_override`
Each `ProviderDB` row carries three EPG columns:
- `epg_enabled` (bool) — `False` skips the provider in the fetcher, excludes it via `get_epg_active_provider_ids()`, and purges its programmes via `EpgManager.purge_provider_epg()`.
- `epg_refresh_interval` (String enum) — `"default"` inherits `Config.epg_default_refresh_interval` (default `"3d"`); throttle logic in `EpgManager.needs_refresh()`.
- `epg_url_override` (optional XMLTV URL).

Resolve the fetch URL only via `EpgManager.effective_epg_url(provider)` — never read `provider.epg_url` directly.

### EPG `channel_name` must be populated at fetch
`EpgProgramDB.channel_name` stores the XMLTV display-name, written at fetch (`_fetch_worker` builds `chan_name_map`). `EpgManager.relink_all()` re-matches existing rows by this name (fuzzy tiers) — which is what makes the watchlist/Watch-Alerts populate without a manual Refresh. **Never stop populating it** or the "watchlist empty until you click Refresh" bug returns. Legacy nameless rows trigger a one-time re-fetch via `EpgRepository.has_unmatched_unnamed_epg()`.

### Context filter chips — strict SQL filter, not the inclusive panel
Clicking a details-pane metadata value (genre/cast/director) activates a temporary context filter using a **strict** SQL filter — not `filter_panel`'s inclusive genre logic (which has a no-data passthrough). Full pattern: [docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md).

- Never route details-pane clicks through `filter_panel.select_only_genre()` or similar.
- At most one context filter is active; activating one clears the others.
- Text search coexists — typing narrows *within* the chip; it does not dismiss it.
- Chip styles from `theme.CONTEXT_FILTER_CHIP*`. State in `_details_*_filter` on `MainWindow`, passed through `load_channels()` → `get_all()`.

### Channel context menus — compose via `channel_menu.py`, never hand-roll a QMenu
Every channel context menu is built by the registry in `metatv/gui/channel_menu.py` (`ChannelMenuContext` + `ACTIONS` + `SURFACE_LAYOUTS` + `build_channel_menu`). Do not regrow the old per-surface menus.

- Add an action: define it once in `ACTIONS` (label/icon/tooltip/`applies`), list its id in the relevant `SURFACE_LAYOUTS` entry, supply a handler at the call site. An id absent from a site's `handlers` is silently skipped — that's how surfaces opt in/out.
- MainWindow-family menus gather context **off-thread** through the single `_show_channel_menu` seam (`_bg_fetch_ctx_data` → `_ctx_data_ready` → `_on_ctx_data_ready`) — not bespoke `executor.submit` + inline `QMenu`.
- EPG/Preferences views build locally via `build_channel_menu`, delegating core handlers (play/favorite/queue/rate) to the MainWindow host.
- Non-channel menus (filter dropdowns, column headers, details chips) are out of scope.

### Player instance keying — thread `provider_id`, never bypass `PlayerManager`
mpv runs as a per-source instance registry (Split Streams). `PlayerManager.play(url, title, provider_id=…, force_new_window=…)` resolves the instance key — `"__shared__"` when split is off, the `provider_id` when `config.split_streams_by_source` is on or `force_new_window=True`.

- Every play path **threads the channel's `provider_id`**: `play_media` → `_bg_validate_and_play` → `_stream_ready` payload → `_on_stream_ready` → `player_manager.play(provider_id=…)`. Dropping it breaks Split Streams.
- `is_running`/`stop`/`get_properties`/`active_keys` go through `PlayerManager(..., key=…)`. Never touch `MPVPlayer`'s process/socket directly.

### Early returns must clean up acquired state
Any resource or set membership acquired before a guard check must be released on every early-return path.
```python
self.refreshing_providers.add(pid)
provider = repos.get(pid)
if not provider:
    self.refreshing_providers.discard(pid)   # release before returning
    return
```
Applies to locks, sets, progress trackers — anything set before a validation check.

### View lifecycle — `on_activate`/`on_deactivate` must be symmetric
If a view has `on_activate()` (starts timers, loads data) it must have `on_deactivate()` (stops timers, cancels pending work). The host (`main_window.py`) calls `on_deactivate` for the departing view and `on_activate` for the arriving one. Safest: call `on_deactivate()` inside `_hide_all_content_views()` for any currently-visible view.

### Modal/overlay views (sidebar-triggered) must hide on all view switches
A modal/overlay stacked in `_list_layout` and triggered by sidebar buttons (not chip nav) must:
1. Be added to `_hide_all_content_views()` (calls `on_deactivate()` if visible, then hides).
2. Check existence via `"view_name" in self.__dict__` (safe for mocked test objects).
3. Have an enter method that hides others, shows the view, calls `on_activate()`.
4. Have an exit method that calls `on_deactivate()` and returns to list view.

Otherwise the modal lingers when users navigate away via chips and keeps consuming async loads.

### Dialog/editor views must notify dependents when data changes
When a dialog/editor mutates data shown elsewhere (sidebar, list, details), emit a signal the host connects to a refresh of the affected view (e.g. the editor's `account_info_updated = pyqtSignal(str)` → MainWindow refreshes the Sources section) — prevents stale, out-of-sync views.

### Provider/source mutations → one canonical refresh
Every view derived from the provider/channel corpus refreshes through the single `MainWindow._refresh_provider_dependent_views()` (sidebar Sources/Favorites/History/Queue/Recommended; main list/search incl. `provider_icon_map`; lazy Discover/Preferences overlays). All mutations funnel through it — add/edit/delete/toggle-active/toggle-visibility. Never re-implement a partial refresh at a call site (e.g. `load_providers()` alone — that recurring shortcut left views stale, most visibly a new source showing content with no icon badge). The account-info poll (`_on_account_info_updated`) is the one exception: it changes only the Sources display, so a sidebar-only refresh is correct.

### Active-source scoping → one helper
Content from inactive (toggled-off) or expired sources must never appear in a forward-looking view. Single source of truth: `ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired), passed as `excluded_provider_ids` by the channel list (`_bg_load_channels`), Discover shelves/See-All (`discover_workers`), and recommendations (`preference_engine.score_candidates`). Never rebuild this set ad-hoc (e.g. `get_expired_provider_ids()` alone leaked disabled-but-unexpired sources into Discover).

- EPG/watchlist include-list sibling: `get_epg_active_provider_ids()` (= active ∧ not-expired ∧ has `epg_url` ∧ `epg_enabled`), passed as `provider_ids`.
- **Exception — record/engaged views (History, Favorites, Watch Queue)** show prior engagement regardless of current source state (you watched it; the source going inactive doesn't erase that). Recommendation *weights* still learn from engaged items on inactive sources; only the surfaced candidate *pool* is scoped to active sources.

### The data engine is preference-free (DR-0007)
Three layers, one-way dependency: **engine ← control ← view.** The engine (faceted/aggregate query primitives) is agnostic — scoped inputs in, data out, no assumptions about what's visible or how data is encoded. Every "what should be visible / what `##` means" decision (`is_hidden`, exclusions, adult mode, provider-encoding convention) lives in the data-aware control layer. Full split: DR-0007.

- Never re-inline a visibility/scoping predicate. Be scope-agnostic like `get_channel_ids_by_tag_facets` (caller supplies `base_channel_ids`); scope with `get_hidden_provider_ids()`. *(A single shared `visible_channel_filter` predicate is the target — tracked as task #59, not yet built; until it lands, match the file's existing convention and don't widen the inline `is_hidden`/`##` smear.)*
- Content-format guesses are ingestion-only — resolve `##`/placeholders at ingest into a stored field; never re-pattern-match in queries (same violation class as render-time `parse_channel_name`).

### Resource cleanup in closeEvent — use the cleanup registry
`MainWindow` owns `self._cleanables: list[tuple[str, callable]]`. Register every new background manager's shutdown immediately after construction — `self._register_cleanable("my_manager", self.my_manager.shutdown)` — never add it to `closeEvent` by hand. `closeEvent` iterates `_cleanables` (exceptions caught per-entry, so one failure never blocks the rest); never add a `hasattr(self, "manager_name")` block. (`db.close()` and the view-deactivation loop stay explicit — they need sequencing/visibility logic.)

### Background pools/threads — owned, long-lived, shut down
Create a `ThreadPoolExecutor`/`QThread` once per owning object, never per call (a pool inside a method that runs more than once is a thread leak). Stop every pool/thread in its owner's cleanup path — `closeEvent` for managers, `on_deactivate` for views. Prefer the owner's shared `self.executor` for one-off background work over a throwaway pool.

### No unbounded DB work on the UI thread
Inverse of the Qt-threading rule. Any query that scans/filters/aggregates/counts over large tables (channels, EPG — 240k+ rows) runs in an executor and marshals results back via signal. Trivial primary-key lookups inline are fine; anything that grows with library size must be offloaded. Watch: startup stat initialization, sidebar `refresh()`, context-menu lookups.

### `_run_query` — required pattern for new background DB reads
`_AsyncMixin` (`metatv/gui/main_window_async.py`) is the single async-read seam on `MainWindow`. All new background reads use it — never ad-hoc `executor.submit` + manual signals.
```python
def _load_something(self):
    self._run_query(
        lambda repos: repos.channels.get_favorites_dto(),  # off-thread; returns plain data
        self._on_something_loaded,                          # main thread
        token_ref=self._my_token,                           # optional stale-drop guard
    )
```
- `query_fn(repos)` must return plain data (DTOs/primitives/dicts), never ORM objects. Runs in read-only `session_scope(commit=False)`.
- `token_ref` cancels superseded in-flight calls (e.g. view switches); omit for order-independent fetches.
- If the caller shows a placeholder, pass `on_error` (main thread, gets the exception) or the spinner hangs forever. Always reuse `self.executor`.

**Sidebar `CollapsibleSection`s can't reach the seam — compose `BackgroundRefreshMixin`** (`metatv/gui/sidebar/background_refresh.py`). Don't hand-roll the executor/signal wiring or invent a third shape. `__init__` calls `self._init_background_refresh()`; also implement `_refresh_list()`→the QListWidget and `_load_error_message()`→str. The two halves that matter are which thread each runs on:
```python
class MySection(BackgroundRefreshMixin, CollapsibleSection):
    _data_ready = pyqtSignal(object)        # list[DTO] | None  (None = load failed)
    def _load_rows(self):                   # worker thread — NO widget access
        with self.db.session_scope() as session:
            return build_dtos(RepositoryFactory(session))
    def _populate_rows(self, data): ...     # main thread, list pre-cleared
```
- `max_workers=1` is required (SQLite-lock rule) and makes rapid `refresh()`es converge (FIFO + clear-first = last-write-wins) — so no `token_ref` needed. MainWindow auto-registers each section's `_executor` by that exact name for shutdown — don't rename it.
- `RecommendedSection` is the documented exception — its `None` is a valid empty state, not a failure, and it emits a `(recs, year_by_id)` tuple.

### Background refresh failure must be visible — never silently blank a list
A background read backing a list/section must not make failure indistinguishable from an empty result. On the `None`/error branch of `_on_data_ready`, render a distinct, non-selectable error row via `CollapsibleSection.show_load_error(list_widget, "Couldn't load …")` (adds a warning row, keeps the section expanded). Never `clear(); return` on failure — an empty "you have nothing here" state is a lie when the query actually threw.

### Tests must prove behavior, not shape
Shape tests (`"session_scope" in func`, attribute-present checks, name checks) are cheap insurance against a careless edit, but a green shape suite is **not coverage** — it stays green through the exact regression it appears to guard.

- Every behavior-changing PR includes ≥1 test that executes the changed path and asserts the outcome that would actually break. For DB-session work: drive the real handler against a real `Database` (`create_tables()` on a `tmp_path` file — not `:memory:`, whose pooled connections each get an empty DB), let the scope close, then assert a detached column is still readable.
- For async reads, the regressing half is the **main-thread `on_result`/`_on_data_ready`** (sorting, continue-vs-never split, icon mapping, episode-code rendering, empty state, failure row) — not the boring worker half. Construct the widget via `__new__`, hand it a real `QListWidget` (headless via the module `qapp` fixture) or a `_FakeLabel`, call the slot, assert the rendered rows.
- Never write a test (or docstring) whose only effect is to look like coverage. A docstring must not claim an invariant that no assert actually checks.

### Tests must never write the real user config
`Config` paths default to `Path.home()/…`; a default `Config()` that saves (directly or via a handler calling `config.save()`) overwrites the developer's real `~/.config/metatv/config.yaml`, wiping Global Exclusions, the What's-New cursor, and migration version fields — a real, repeated bug that looked like flaky data loss. The autouse `_isolate_user_config` fixture in `tests/conftest.py` monkeypatches `Path.home()` to a throwaway tmp dir for every test.

- Never remove/weaken it or `monkeypatch.undo()` it. `tests/test_config_isolation.py` guards it — keep it green.
- A test that genuinely needs config on disk passes `config_dir=tmp_path` explicitly. No test writes outside its tmp dirs.

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) saves to config and restores on startup. Pattern: save immediately on change, restore during `__init__`. Full pattern: [DESIGN.md](DESIGN.md).

### Architecture discipline — chokepoints, scope, ask early
The proactive form of the Governing Principles.

- **Find the existing path before adding a sibling.** Grep the verb-cluster (`play_*`/`load_*`/`refresh_*`/`fetch_*`/`_on_*_ready`) and the repo/manager method or seam you're about to call before writing a new one. A core primitive called from >1 UI site is a chokepoint — one entry, every caller gets the full behavior. Need a variant → share the core (one helper both call), never copy-paste-and-trim. Semantic duplication is invisible to syntactic greps — read behavior. (Cautionary case: a duplicate play path that silently dropped failover/buffering and rotted as fixes landed only on the canonical path — see [docs/AUDIT_2026-06-19.md](docs/AUDIT_2026-06-19.md).)
- **One concern per PR.** Discover a larger problem mid-task → record it in the backlog (task tracker, or the active `docs/REFACTOR_PLAN_BAND*.md`) as a new item; don't expand the PR and don't paper over it.
- **When the correct path is unclear, ask.** A one-line clarifying question beats inventing a third pattern.

## Metadata Provider Chain

Providers tried in priority order until sufficient data found:
1. `ProviderMetadataProvider` — extracts from Xtream `raw_data` (always first, zero latency)
2. `TMDbProvider` — not yet implemented
3. `OMDbProvider` — not yet implemented

`MetadataResult.merge()` uses confidence scores (0.0–1.0) to prefer higher-quality data per field.

**Year is derived at ingestion — read `metadata.year` directly everywhere.** `MetadataManager._derive_year()` populates `MetadataDB.year` at write (`_save_metadata_cache`, from `release_date` when `year` is absent) and backfills pre-fix rows on read (`_metadata_db_to_result`). No runtime parsing or fallback outside `metadata_manager.py`. `release_date` keeps the full ISO string (e.g. "2024-07-03").

## Content Dedup — Known Compromises

> **Two dedup layers coexist (see DR-0009 + [docs/CONTENT_IDENTITY.md](docs/CONTENT_IDENTITY.md)).** Browse / Recipe Show-All / Discover / details "Other Versions" / tag counts collapse on the **stored `content_key`** (coarse: no director). The runtime fingerprint below is the **richer** key still used only by **Recommendations + the Similar lightbox** (Phase 2 will re-base those onto `content_key`). When metadata lands, a canonical TMDb/IMDb id replaces the `content_key` string in place.

`content_dedup.py` groups same-production channels across providers by a `(norm_title, media_type, year, director)` fingerprint — a heuristic stopgap until TMDb/IMDb canonical IDs are wired up (ROADMAP). Deliberate trade-offs:

- **Director excluded for series.** Many episode directors / inconsistent attribution cause false splits (same show appearing twice). Movies keep director — a single director is reliably credited and distinguishes remakes.
- **Null-year absorption.** A candidate with no year (in name or MetadataDB) is suppressed if a year-bearing engaged variant with the same `(norm, media_type)` exists (e.g. a no-year `Rick and Morty` when `Rick And Morty (2013)` is queued). Risk: a genuinely different same-name no-year series could be suppressed — accepted as rare.

Net effect: the recommendations list may occasionally hide a legitimate alternative or surface an unexpected variant. Don't tighten these without first checking the failing case isn't better fixed by improving metadata completeness (year in channel name, consistent director field). Canonical-ID primary key and a dedup-transparency toggle are tracked in ROADMAP.

## Image Cache

MD5(url) as filename in `~/.cache/metatv/images/`, LRU cleanup at 500MB. Always load images async via `ImageCache.get_image_async()` + signals — never block the main thread.

## Coding Standards

- Python 3.11+ type hints on all signatures; Google-style docstrings on public APIs.
- Imports: stdlib → third-party → local, separated by blank lines.
- Files under 1000 lines; one class per file (helper classes excepted).
- `ThreadPoolExecutor` for blocking I/O; `asyncio` for async providers; `QTimer.singleShot(0, ...)` for deferred main-thread execution.
- **Every PR with user-visible behavior (feature OR bug-fix) adds a new file** `metatv/whats_new/entries/NNNN_slug.py` (zero-padded id, e.g. `0016_my_feature.py`) with `ENTRY = WhatsNewEntry(...)` **including a non-empty `test_steps` tuple** — the smoke test the tester/user steps through in the dev QA checklist (`METATV_DEV=1`). Each step is one action + its expected outcome, together covering the changed path end-to-end so there is always a concrete set of tasks to verify the change. `test_steps` is the **default, not optional**. Omit it (with a one-line PR note saying why) only for changes with nothing to test by hand — pure internal refactors with no behavior change, or dev-only tooling like the checklist window itself. Never edit the shared list. Confirm the next id: `python -c "from metatv.whats_new import latest_id; print(latest_id() + 1)"`. Format + examples: `metatv/whats_new/entries/README`.

## Session Wrap SOP

On "let's wrap up" / "wrap this session", do all of the following in order:

1. **Tests** — `venv/bin/python -m pytest tests/ -x -q`; confirm all pass. If new behavior was added, note missing coverage in the FILTERING_DESIGN / ROADMAP test-coverage sections.
2. **Commit** everything uncommitted with a descriptive message; never leave working changes untracked.
3. **Docs** — update any now-stale design/reference docs: `docs/FILTERING_DESIGN.md`, `ROADMAP.md`, `docs/UI_UX_GUIDELINES.md` (if interaction patterns changed).
4. **CLAUDE.md** — update if new critical rules, architecture patterns, or file locations were established.
5. **Memory** — refresh `~/.claude/projects/…/memory/`: `project_session_handoff.md` (branch/commit/open work) and relevant pattern/decision files.
6. **Push** — `git push origin main`; confirm no errors.
7. **Confirm** — report what was committed, pushed, and written to memory; call out anything that couldn't be done and why.

## Migration Status (incremental — follow the rule in new code, don't extend the debt)

These legacy patterns coexist with the rules above and are being migrated. New code follows the rule; don't add to the old form.

- **Icons:** existing `config.<name>_icon` references → migrate to `icons.*`.
- **Sessions:** legacy `get_session()` + `try/finally` → migrate to `session_scope()`.
- **Styles:** a few pre-rule inline `font-size: Npx` literals remain → use `FONT_*` tokens.
- **ORM→DTO:** `session.expunge` sites remain where no DTO exists yet → prefer a DTO (only safe while the model has no `relationship()`/`deferred()` column).

## Reference Docs

| Topic | File |
|---|---|
| **Product vision & direction (north star)** | [docs/PRODUCT_VISION.md](docs/PRODUCT_VISION.md) |
| UI/UX interaction patterns | [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) |
| Qt threading deep dive | [docs/THREADING_PATTERNS.md](docs/THREADING_PATTERNS.md) |
| Metadata system architecture | [docs/METADATA_SYSTEM.md](docs/METADATA_SYSTEM.md) |
| Filtering design | [docs/FILTERING_DESIGN.md](docs/FILTERING_DESIGN.md) |
| Context filter chips | [docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md) |
| Details pane design | [docs/DETAILS_PANE_DESIGN.md](docs/DETAILS_PANE_DESIGN.md) |
| Xtream API schema | [docs/xtream_api_schema.md](docs/xtream_api_schema.md) |
| UI state persistence patterns | [DESIGN.md](DESIGN.md) |
| Roadmap | [ROADMAP.md](ROADMAP.md) |
| Refactor / dedup / cleanup plan | [docs/REFACTOR_PLAN.md](docs/REFACTOR_PLAN.md) |
| Refactor audit + current remediation (Band 10) | [docs/AUDIT_2026-06-19.md](docs/AUDIT_2026-06-19.md) |