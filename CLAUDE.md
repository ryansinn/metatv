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
Cross-source dedup has one identity field: `content_key`, computed at ingestion by `content_identity.content_key_for()` and stored (indexed) on `ChannelDB`. Every collapse surface reads the stored key (Browse/tag counts via `tag.py` `collapse_variants`, Discover via `_dedup_cards`, details "Other Versions" via `content_key ==`) — never a parallel heuristic; group on `COALESCE(content_key, 'id:' || id)`. Spec: [docs/CONTENT_IDENTITY.md](docs/CONTENT_IDENTITY.md); rationale DR-0009; detail (incl. Phase-2 fingerprint exception): [docs/CRITICAL_RULES.md#content-identity](docs/CRITICAL_RULES.md#content-identity).

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

### EPG notifications — never call NotificationManager from a worker thread
`NotificationManager.show()` creates an auto-dismiss `QTimer` (main thread only); in `EpgManager` all worker notifications go through private signals (`_notify`, `_progress_*`) that Qt queues to the main thread.

### EPG concurrent fetches — one worker at a time
`EpgManager` uses `ThreadPoolExecutor(max_workers=1)`; two concurrent XMLTV fetches cause SQLite `database is locked` (each does bulk-delete + bulk-insert). Providers fetch sequentially.

### Per-provider EPG config — `epg_enabled`, `epg_refresh_interval`, `epg_url_override`
Each `ProviderDB` row carries these three EPG columns; resolve the fetch URL only via `EpgManager.effective_epg_url(provider)` — never read `provider.epg_url` directly. Per-column semantics: [docs/CRITICAL_RULES.md#per-provider-epg-config](docs/CRITICAL_RULES.md#per-provider-epg-config).

### EPG `channel_name` must be populated at fetch
`EpgProgramDB.channel_name` (the XMLTV display-name, written by `_fetch_worker`) is what `EpgManager.relink_all()` re-matches on, so the watchlist populates without a manual Refresh. **Never stop populating it.** Detail: [docs/CRITICAL_RULES.md#epg-channel-name-at-fetch](docs/CRITICAL_RULES.md#epg-channel-name-at-fetch).

### Context filter chips — strict SQL filter, not the inclusive panel
A details-pane metadata click (genre/cast/director) activates a temporary **strict** SQL filter — never route through `filter_panel.select_only_genre()`; at most one chip active; text search narrows within it. Full pattern: [docs/CONTEXT_FILTER_CHIPS.md](docs/CONTEXT_FILTER_CHIPS.md); state details: [docs/CRITICAL_RULES.md#context-filter-chips](docs/CRITICAL_RULES.md#context-filter-chips).

### Channel context menus — compose via `channel_menu.py`, never hand-roll a QMenu
Every channel menu is built by the registry in `metatv/gui/channel_menu.py` (`ACTIONS` + `SURFACE_LAYOUTS` + `build_channel_menu`); MainWindow-family menus gather context off-thread through the single `_show_channel_menu` seam. Don't regrow per-surface menus. Detail: [docs/CRITICAL_RULES.md#channel-context-menus](docs/CRITICAL_RULES.md#channel-context-menus).

### Player instance keying — thread `provider_id`, never bypass `PlayerManager`
Every play path threads the channel's `provider_id` through to `player_manager.play(provider_id=…)` (resolves the per-source mpv instance key for Split Streams); `is_running`/`stop`/`get_properties` go through `PlayerManager(..., key=…)`, never `MPVPlayer` directly. Detail: [docs/CRITICAL_RULES.md#player-instance-keying](docs/CRITICAL_RULES.md#player-instance-keying).

### Early returns must clean up acquired state
Any resource or set membership acquired before a guard check (locks, sets, progress trackers) must be released on every early-return path. Example: [docs/CRITICAL_RULES.md#early-returns-cleanup](docs/CRITICAL_RULES.md#early-returns-cleanup).

### View lifecycle — `on_activate`/`on_deactivate` must be symmetric
A view with `on_activate()` (starts timers/loads) must have `on_deactivate()` (stops timers/cancels work); the host calls them on switch, safest from `_hide_all_content_views()`. Detail: [docs/CRITICAL_RULES.md#view-lifecycle](docs/CRITICAL_RULES.md#view-lifecycle).

### Modal/overlay views (sidebar-triggered) must hide on all view switches
A sidebar-triggered modal stacked in `_list_layout` must register in `_hide_all_content_views()`, guard existence via `"view_name" in self.__dict__`, and pair enter/exit with `on_activate`/`on_deactivate` — else it lingers and keeps consuming async loads. Sibling: dialogs/editors emit a signal so the host refreshes dependent views. Steps: [docs/CRITICAL_RULES.md#modal-and-overlay-views](docs/CRITICAL_RULES.md#modal-and-overlay-views).

### Provider/source mutations → one canonical refresh
Every view derived from the provider/channel corpus refreshes through the single `MainWindow._refresh_provider_dependent_views()`; all mutations (add/edit/delete/toggle-active/visibility) funnel through it — never a partial per-call-site refresh (e.g. `load_providers()` alone leaves views stale). The account-info poll is the one sidebar-only exception. Detail: [docs/CRITICAL_RULES.md#provider-mutations-refresh](docs/CRITICAL_RULES.md#provider-mutations-refresh).

### Active-source scoping → one helper
Content from inactive/expired sources never appears in a forward-looking view; scope via `ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired) as `excluded_provider_ids`, never an ad-hoc set. EPG sibling: `get_epg_active_provider_ids()`. Record/engaged views (History/Favorites/Queue) are exempt. Engine stays scope-agnostic (DR-0007). Detail: [docs/CRITICAL_RULES.md#active-source-scoping](docs/CRITICAL_RULES.md#active-source-scoping).

### The data engine is preference-free (DR-0007)
Three layers, one-way: **engine ← control ← view.** The engine takes scoped inputs and returns data with no visibility/encoding assumptions; every "what's visible / what `##` means" decision lives in the control layer. Never re-inline a visibility predicate; resolve content-format guesses at ingest, never in queries. Full split: DR-0007 · [docs/CRITICAL_RULES.md#active-source-scoping](docs/CRITICAL_RULES.md#active-source-scoping).

### Resource cleanup in closeEvent — use the cleanup registry
Register each new background manager's shutdown right after construction via `self._register_cleanable("name", mgr.shutdown)` — never hand-edit `closeEvent` or add a `hasattr` block. Background pools/threads are owned once per object and stopped in the owner's cleanup path. Detail: [docs/CRITICAL_RULES.md#closeevent-cleanup-registry](docs/CRITICAL_RULES.md#closeevent-cleanup-registry).

### Background DB reads — offload, route through the async seam, surface failure
Any query scanning/aggregating large tables (channels, EPG — 240k+ rows) runs in an executor, never on the UI thread. New `MainWindow` reads go through the single `_run_query` seam (`_AsyncMixin`); sidebar `CollapsibleSection`s compose `BackgroundRefreshMixin`. `query_fn` returns plain data (DTOs), never ORM objects. On the `None`/error branch, render a visible error row via `show_load_error()` — never `clear(); return`. Detail: [docs/CRITICAL_RULES.md#async-background-db-reads](docs/CRITICAL_RULES.md#async-background-db-reads).

### Tests must prove behavior, not shape
A green shape suite (`"x" in func`, attribute checks) is not coverage. Every behavior-changing PR adds ≥1 test that executes the changed path and asserts the outcome that would break — for DB-session work, drive the real handler against a real `Database` on a `tmp_path` file (not `:memory:`); for async reads, test the main-thread slot. Never write a test or docstring whose only effect is to look like coverage. Detail: [docs/CRITICAL_RULES.md#tests](docs/CRITICAL_RULES.md#tests).

### Tests must never write the real user config
The autouse `_isolate_user_config` fixture (`tests/conftest.py`) patches `Path.home()` to a tmp dir so tests can't overwrite `~/.config/metatv/config.yaml` (a real, repeated data-loss bug); never remove/weaken it, and `tests/test_config_isolation.py` must stay green. A test needing config on disk passes `config_dir=tmp_path`. Detail: [docs/CRITICAL_RULES.md#tests](docs/CRITICAL_RULES.md#tests).

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) saves to config and restores on startup: save immediately on change, restore during `__init__`. Full pattern: [DESIGN.md](DESIGN.md).

### Architecture discipline — chokepoints, scope, ask early
The proactive form of the Governing Principles: find the existing path before adding a sibling (grep the verb-cluster + the seam you're about to call; a primitive called from >1 site is a chokepoint — share the core, never copy-and-trim); one concern per PR (record larger problems in the backlog); when the correct path is unclear, ask. Detail + cautionary case: [docs/CRITICAL_RULES.md#architecture-discipline](docs/CRITICAL_RULES.md#architecture-discipline).

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
| Refactor audit + current remediation (Band 10) | [docs/AUDIT_2026-06-19.md](docs/AUDIT_2026-06-19.md) |