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

One directive per rule below. Code examples, every-call-site enumerations, exceptions, and rationale live in the linked deep-dive — read it before working in that area. Catch-all detail for rules without a dedicated doc: [docs/CRITICAL_RULES.md](docs/CRITICAL_RULES.md).

### EPG time & timezone — always via `epg_utils.py`
All EPG time/timezone helpers (`now_utc`, `to_local`, `is_local_today`, `local_weekday`, `epg_is_stale`, …) live in `metatv/core/epg_utils.py`; never redefine inline or open-code conversions. `start_time`/`stop_time` are UTC-naive: display via `to_local`, "today"/weekday via `is_local_today`/`local_weekday` (never `.date() == date.today()`), arithmetic against `now_utc()`. Detail: [docs/CRITICAL_RULES.md#epg-time-and-timezone](docs/CRITICAL_RULES.md#epg-time-and-timezone).

### Styles — two-layer `theme.py`; tokens for every palette/font-size value
Design tokens (`COLOR_*`/`FONT_*`/`OVERLAY_*`) are the only place a hex/rgba literal or font *size* may appear; semantic constants are role-named stylesheet strings composed from tokens. Never inline a color literal (even in `f"…{_theme.COLOR_WARN}"`) or `font-size: Npx`; a stylesheet used by >1 widget is a shared role constant, never copy-pasted. Structural-spacing px inline is fine. Detail: [docs/UI_UX_GUIDELINES.md](docs/UI_UX_GUIDELINES.md) → "Theming & style tokens" · [docs/CRITICAL_RULES.md#styles-and-theme-tokens](docs/CRITICAL_RULES.md#styles-and-theme-tokens).

### Channel-name fields — computed at ingestion, read at render
`detected_*` fields (`detected_prefix/quality/region/title/year`) are computed at ingestion by `update_detected_prefixes()` (`core/repositories/channel.py`) and stored; render code reads `channel.detected_*` directly and **never calls `parse_channel_name()`**. Detail + the one accepted `epg_watchlist_mixin.py` exception: [docs/CRITICAL_RULES.md#channel-name-detected-fields](docs/CRITICAL_RULES.md#channel-name-detected-fields).

### Content identity — one stored `content_key`, computed at ingestion, collapsed at read
Cross-source dedup has one identity field: `content_key`, computed at ingestion by `content_identity.content_key_for()` and stored (indexed) on `ChannelDB`. Every collapse surface reads the stored key (Browse/tag counts via `tag.py` `collapse_variants`, Discover via `_dedup_cards`, details "Other Versions" via `content_key ==`) — never a parallel heuristic; group on `COALESCE(content_key, 'id:' || id)`. Spec: [docs/CONTENT_IDENTITY.md](docs/CONTENT_IDENTITY.md); rationale DR-0009; detail incl. the Phase-2 runtime-fingerprint layer (recommendations/Similar) and its known compromises: [docs/CRITICAL_RULES.md#content-identity](docs/CRITICAL_RULES.md#content-identity), [#content-dedup-compromises](docs/CRITICAL_RULES.md#content-dedup-compromises).

### Lookup tables — single source of truth
Region/country codes, quality tokens, audio-format maps, and channel-name parsing data live only in `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, …). Import from there; never define parallel dicts. A new code or alias goes in `channel_name_utils.py` only.

### Tags/facets — capture generously, label confidence + provenance
In the guessing zone, bias to recall: capture the facet a feeder denotes (high confidence) plus any *real* adjacent guess (low) — confidence is ranking/prune-priority, never a suppression gate; every tag records its feeder + read-vs-inference; hierarchy is rollup, not auto-tagging. Chokepoint: `tag_decomposer.py` (curated data: `channel_name_utils.py`). Rationale DR-0006; detail + worked examples: [docs/CRITICAL_RULES.md#tags-and-facets](docs/CRITICAL_RULES.md#tags-and-facets).

### Icons — always from `metatv/gui/icons.py`
Every icon/emoji/symbol comes from `icons.py`, never a literal in widget code; add a new icon there first, never glyphs to `Config`. Collapse/expand uses `icons.expand_icon`/`icons.collapse_icon` (not the list-ordering arrows). Detail (collapsible nesting pattern): [docs/CRITICAL_RULES.md#icons](docs/CRITICAL_RULES.md#icons).

### Logging — always loguru
`from loguru import logger`; never `import logging`.

### Database sessions — `session_scope()` for new code
New code uses `Database.session_scope()` (commits on success, rolls back on exception, always closes); a bare `with session:` manages only the transaction, not cleanup — never use it. Legacy `get_session()` + `try/finally` is migration debt. Detail: [docs/CRITICAL_RULES.md#database-sessions](docs/CRITICAL_RULES.md#database-sessions).

### ORM objects must not outlive their session — cross the boundary with a DTO
`session_scope()` expires on commit, so a detached ORM object's next attribute access raises `DetachedInstanceError`; map ORM → frozen DTO (`core/repositories/dtos.py`) inside the block and return that. Prefer a DTO over `session.expunge`. Detail + the `_apply_favorite_toggle` exception: [docs/CRITICAL_RULES.md#orm-to-dto-boundary](docs/CRITICAL_RULES.md#orm-to-dto-boundary).

### SQLite JSON columns — `JSONEncoded`, assign plain Python objects
`Column(JSONEncoded)` serializes transparently — assign and read plain objects; never `json.dumps()` before assigning (double-encodes). Detail: [docs/CRITICAL_RULES.md#sqlite-json-columns](docs/CRITICAL_RULES.md#sqlite-json-columns).

### Qt threading — signals only; QPixmap on the main thread
Qt widgets aren't thread-safe: workers emit signals, only the main thread touches widgets. **QPixmap is a GUI object** — never build it in a worker; emit the path string cross-thread and construct the pixmap in the main-thread slot. Deep dive: [docs/THREADING_PATTERNS.md](docs/THREADING_PATTERNS.md).

### Signal blocking during UI state restoration
Block signals before programmatically setting widget state (`blockSignals(True)` → set every widget → `blockSignals(False)`), then `.connect()` handlers in a separate pass — so restoring one widget doesn't fire another's slot. See [docs/THREADING_PATTERNS.md](docs/THREADING_PATTERNS.md) → "Blocking Signals During State Restoration".

### EPG manager internals — worker-thread & fetch rules
Inside `EpgManager`/the fetch path: worker notifications go through private signals, never `NotificationManager` directly (it makes a main-thread `QTimer`); fetches run one at a time (`ThreadPoolExecutor(max_workers=1)`, else SQLite `database is locked`); resolve the fetch URL via `EpgManager.effective_epg_url(provider)`, never `provider.epg_url`; and `channel_name` **must** be populated at fetch (`relink_all()` re-matches on it — else the watchlist needs a manual Refresh). Detail: [docs/CRITICAL_RULES.md#epg-manager-internals](docs/CRITICAL_RULES.md#epg-manager-internals).

### Context filter chips — strict SQL filter, not the inclusive panel
A details-pane metadata click (genre/cast/director) activates a temporary **strict** SQL filter — never route through `filter_panel.select_only_genre()`; at most one chip active; text search narrows within it. Full pattern: [docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md); state details: [docs/CRITICAL_RULES.md#context-filter-chips](docs/CRITICAL_RULES.md#context-filter-chips).

### Channel context menus — compose via `channel_menu.py`, never hand-roll a QMenu
Every channel menu is built by the registry in `metatv/gui/channel_menu.py` (`ACTIONS` + `SURFACE_LAYOUTS` + `build_channel_menu`); MainWindow-family menus gather context off-thread through the single `_show_channel_menu` seam. Don't regrow per-surface menus. Detail: [docs/CRITICAL_RULES.md#channel-context-menus](docs/CRITICAL_RULES.md#channel-context-menus).

### Player instance keying — thread `provider_id`, never bypass `PlayerManager`
Every play path threads the channel's `provider_id` through to `player_manager.play(provider_id=…)` (resolves the per-source mpv instance key for Split Streams); `is_running`/`stop`/`get_properties` go through `PlayerManager(..., key=…)`, never `MPVPlayer` directly. Detail: [docs/CRITICAL_RULES.md#player-instance-keying](docs/CRITICAL_RULES.md#player-instance-keying).

### View lifecycle & modal hiding — symmetric activate/deactivate
A view with `on_activate()` (timers/loads) must have a matching `on_deactivate()` (stop/cancel); the host calls them on switch, safest from `_hide_all_content_views()`. A sidebar-triggered modal in `_list_layout` must *also* register in `_hide_all_content_views()`, guard existence via `"view_name" in self.__dict__`, and pair enter/exit with activate/deactivate — else it lingers and keeps consuming async loads. Sibling: dialogs/editors emit a signal so the host refreshes dependent views. Detail: [docs/CRITICAL_RULES.md#view-lifecycle](docs/CRITICAL_RULES.md#view-lifecycle) · [#modal-and-overlay-views](docs/CRITICAL_RULES.md#modal-and-overlay-views).

### Provider/source mutations → one canonical refresh
Every view derived from the provider/channel corpus refreshes through the single `MainWindow._refresh_provider_dependent_views()`; all mutations (add/edit/delete/toggle-active/visibility) funnel through it — never a partial per-call-site refresh (e.g. `load_providers()` alone leaves views stale). The account-info poll is the one sidebar-only exception. Detail: [docs/CRITICAL_RULES.md#provider-mutations-refresh](docs/CRITICAL_RULES.md#provider-mutations-refresh).

### Engine/control/view layering & active-source scoping (DR-0007)
Three layers, one-way: **engine ← control ← view.** The engine takes scoped inputs and returns data with no visibility/encoding assumptions; every "what's visible / what `##` means" decision lives in the control layer (never re-inline a visibility predicate; resolve content-format guesses at ingest, not in queries). Scope forward-looking views via `ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired) as `excluded_provider_ids`, never an ad-hoc set; EPG sibling `get_epg_active_provider_ids()`. Record/engaged views (History/Favorites/Queue) are exempt. Full split DR-0007; detail: [docs/CRITICAL_RULES.md#active-source-scoping](docs/CRITICAL_RULES.md#active-source-scoping).

### Resource cleanup in closeEvent — use the cleanup registry
Register each new background manager's shutdown right after construction via `self._register_cleanable("name", mgr.shutdown)` — never hand-edit `closeEvent` or add a `hasattr` block. Background pools/threads are owned once per object and stopped in the owner's cleanup path. Detail: [docs/CRITICAL_RULES.md#closeevent-cleanup-registry](docs/CRITICAL_RULES.md#closeevent-cleanup-registry).

### Background DB reads — offload, route through the async seam, surface failure
Any query scanning/aggregating large tables (channels, EPG — 240k+ rows) runs in an executor, never on the UI thread. New `MainWindow` reads go through the single `_run_query` seam (`_AsyncMixin`); sidebar `CollapsibleSection`s compose `BackgroundRefreshMixin`. `query_fn` returns plain data (DTOs), never ORM objects. On the `None`/error branch, render a visible error row via `show_load_error()` — never `clear(); return`. Detail: [docs/CRITICAL_RULES.md#async-background-db-reads](docs/CRITICAL_RULES.md#async-background-db-reads).

### Tests — prove behavior, never write real config
A green shape suite (`"x" in func`, attribute checks) is not coverage: every behavior-changing PR adds ≥1 test that executes the changed path and asserts the outcome that would break (DB-session work → real `Database` on a `tmp_path` file, not `:memory:`; async reads → the main-thread slot). Never write a test/docstring whose only effect is to look like coverage. And never touch the real user config — the autouse `_isolate_user_config` fixture (`tests/conftest.py`) patches `Path.home()` to a tmp dir (guards a real data-loss bug); never weaken it, keep `tests/test_config_isolation.py` green, pass `config_dir=tmp_path` if a test needs config on disk. Detail: [docs/CRITICAL_RULES.md#tests](docs/CRITICAL_RULES.md#tests).

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) saves to config and restores on startup: save immediately on change, restore during `__init__`. Full pattern: [DESIGN.md](DESIGN.md).

### Architecture discipline — chokepoints, scope, ask early
Before adding a sibling function, grep the verb-cluster (`play_*`/`load_*`/`refresh_*`/`fetch_*`/`_on_*_ready`) for the existing chokepoint and share it; one concern per PR. Detail + cautionary case: [docs/CRITICAL_RULES.md#architecture-discipline](docs/CRITICAL_RULES.md#architecture-discipline).

## Metadata — year derived at ingestion

Read `metadata.year` everywhere (`MetadataManager._derive_year()` populates it at write from `release_date`, backfills pre-fix rows on read; no runtime parsing outside `metadata_manager.py`). Provider chain, `merge()` confidence scoring, and dedup compromises: [docs/METADATA_SYSTEM.md](docs/METADATA_SYSTEM.md), [docs/CONTENT_IDENTITY.md](docs/CONTENT_IDENTITY.md).

## Coding Standards

- Python 3.11+ type hints on all signatures; Google-style docstrings on public APIs.
- Imports: stdlib → third-party → local, separated by blank lines.
- Files under 1000 lines; one class per file (helper classes excepted).
- `ThreadPoolExecutor` for blocking I/O; `asyncio` for async providers; `QTimer.singleShot(0, ...)` for deferred main-thread execution.
- **Every PR with user-visible behavior adds `metatv/whats_new/entries/NNNN_slug.py`** (zero-padded next id via `python -c "from metatv.whats_new import latest_id; print(latest_id() + 1)"`) with `ENTRY = WhatsNewEntry(...)` including a **non-empty `test_steps`** tuple — the dev-QA smoke test (`METATV_DEV=1`), each step an action + expected outcome covering the changed path. `test_steps` is the default; omit (with a one-line PR note) only for no-behavior refactors or dev-only tooling. Never edit the shared list. Format + examples: `metatv/whats_new/entries/README`.

## Session Wrap SOP

On "let's wrap up" / "wrap this session", follow [docs/SESSION_WRAP.md](docs/SESSION_WRAP.md) in order: tests (`pytest tests/ -x -q`) → commit everything → update stale docs → update CLAUDE.md → refresh memory (`project_session_handoff.md`) → `git push origin main` → confirm what landed.

## Migration Status

These legacy forms coexist with the rules above — new code follows the rule, don't extend the debt: `config.<name>_icon` → `icons.*`; `get_session()`+`try/finally` → `session_scope()`; inline `font-size: Npx` → `FONT_*`; `session.expunge` → DTO.

## Reference Docs

| Topic | File |
|---|---|
| **Critical Rules — full detail (code, exceptions, rationale)** | [docs/CRITICAL_RULES.md](docs/CRITICAL_RULES.md) |
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
| Current audit + **Band 10** remediation plan | [docs/AUDIT_2026-06-19.md](docs/AUDIT_2026-06-19.md) |