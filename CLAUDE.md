# MetaTV — Claude Code Project Guide

## What This Is

MetaTV is a Python/PyQt6 IPTV client. It connects to Xtream API providers, caches channel data in SQLite, and plays streams via mpv. UI: three-panel layout — sidebar (sources/favorites/history), channel list, details pane.

**Run it:** `./run.sh` or `venv/bin/python -m metatv`

## Architecture

`core/` business logic (no UI deps) · `gui/` PyQt6 widgets · `providers/` IPTV source plugins · `metadata_providers/` enrichment plugins.

**There is deliberately no directory map.** `docs/ARCHITECTURE.md` was one — 76 hand-written lines describing 621 files — and it decayed to covering ~17% of `gui/` and 35% of `core/`, naming deleted modules and omitting whole subsystems (the sidebar package, the token layer, playback, the migration framework, ten of fifteen repositories). It was deleted rather than rewritten: a hand-maintained enumeration of a tree this size cannot stay true, and a map that is confidently wrong is worse than none — it was the file this guide sent newcomers to first.

This is the same failure the code keeps hitting in other clothes (the `refresh_theme()` sweep, hand-listed test config stubs, `_SETTINGS_APPLIED_HOOKS`): **an enumeration never sees what nobody remembered to add.** If a structural map is wanted, GENERATE it from the import graph so it cannot drift. Read the code for structure; read `docs/DESIGN_RATIONALE.md` for why it is shaped that way — decisions do not go stale, descriptions do.

**Data locations:** config `~/.config/metatv/config.yaml` · db `~/.local/share/metatv/metatv.db` · logs `~/.config/metatv/logs/` · image cache `~/.cache/metatv/images/`.

## Governing Principles

Most Critical Rules below are instances of two ideas. When a rule states one of these, it's applying the principle — not re-deriving it.

1. **Single chokepoint / one source of truth.** For any recurring operation (play, refresh, async DB read, name parsing, scoping filters) and any palette/lookup data (colors, icons, region codes), there is one canonical path or definition. Route through it; never hand-roll a parallel one. Need a variant → extend the shared core (one helper both call), don't copy-and-trim.
2. **Compute once at ingestion, read everywhere else.** Name-derived fields, year, and content-format guesses are resolved at write time into stored fields. Display, query, and scoring code reads the stored field — never re-parses at runtime.

If a rule's premise has drifted from the code, say so and adapt — don't silently ignore it. When the correct path is genuinely unclear, ask: a one-line clarifying question beats inventing a third pattern.

## Critical Rules

One directive per rule below. Code examples, every-call-site enumerations, exceptions, and rationale live in the linked deep-dive — read it before working in that area. Catch-all detail for rules without a dedicated doc: docs/CRITICAL_RULES.md.

### EPG time & timezone — always via `epg_utils.py`
All EPG time/timezone helpers (`now_utc`, `to_local`, `is_local_today`, `local_weekday`, `epg_is_stale`, …) live in `metatv/core/epg_utils.py`; never redefine inline or open-code conversions. `start_time`/`stop_time` are UTC-naive: display via `to_local`, "today"/weekday via `is_local_today`/`local_weekday` (never `.date() == date.today()`), arithmetic against `now_utc()`. Detail: docs/CRITICAL_RULES.md#epg-time-and-timezone.

### Styles — two-layer `theme.py`; tokens for every palette/font-size value
Design tokens (`COLOR_*`/`FONT_*`/`OVERLAY_*`) are the only place a hex/rgba literal or font *size* may appear; semantic constants are role-named stylesheet strings composed from tokens. Never inline a color literal (even in `f"…{_theme.COLOR_WARN}"`) or `font-size: Npx`; a stylesheet used by >1 widget is a shared role constant, never copy-pasted. Structural-spacing px inline is fine. Detail: docs/UI_UX_GUIDELINES.md → "Theming & style tokens" · docs/CRITICAL_RULES.md#styles-and-theme-tokens.

### Theme application — the QPalette floor catches what no sweep can see
A widget with **no** stylesheet can't be found by an enumeration sweep, so `theme.qt_palette()` builds a `QPalette` from the active tokens and `apply_theme()` pushes it onto the whole `QApplication` (also at cold launch in `__main__.py`) — that floor, not `refresh_theme()`, is what themes unstyled widgets. A token drawn on a *fill* needs its own on-fill token: `COLOR_ON_ACCENT` is the foreground for anything on a solid `COLOR_ACCENT` (selection highlight, the Sources Add CTA), never the `COLOR_TEXT_HI` on-background ramp. New palette key → add it to all three palettes in `theme_palettes.py`. Detail: docs/UI_UX_GUIDELINES.md → "Theming & style tokens".

### Styling a widget — `theme.style()`, never raw `setStyleSheet`
Qt caches the *rendered* stylesheet string, so `w.setStyleSheet(theme.ROLE)` renders once and goes stale on every theme switch. Use **`theme.style(w, "ROLE")`** (or `theme.style_fn(w, builder)` for a composed/f-string sheet): it applies the style AND registers the widget weakly, so `apply_theme()` re-applies it. The drift guard is an **AST walk**, not a line regex: ANY `setStyleSheet` argument that reads the theme module is drift whatever expression wraps it — ternary, `.format()` template, builder call, `style or theme.ROLE` fallback. The regex it replaced knew one shape and eleven real sites had sailed past it. F-string sheets composed inline are the pre-registry population, capped by a shrink-only `COMPOSED_BUDGET`; use `style_fn` for new ones. This replaced the hand-maintained `refresh_theme()` sweep, which could not work — 838 call sites against 22 sweep methods, and an enumeration never sees what nobody remembered to add (#253/#261 both "completed" it and both left it broken). Detail: docs/UI_UX_GUIDELINES.md → "Theming & style tokens".

### The fixed-dark "cinema" surface — its own token family, never a palette-tuned one
The preview overlay and Explore trail-map are the SAME dark panel in all three palettes (`COLOR_LIGHTBOX_BG`/`_HEADER` are identical by design), so a foreground painted on them cannot come from a palette-tuned token — Daylight's are chosen for a LIGHT app background and collapse there (Back button 1.06:1, the trail's "here" tag white-on-white at 1.03:1, poster wells and keyboard chips as white boxes). Anything with a `LIGHTBOX_*`/`TRAILMAP_*`/`EXPLORE_*` prefix takes its colour from the fixed `COLOR_LIGHTBOX_*` family (`_MUTED`/`_FAINT`/`_LINK`/`_SUNKEN`/`_LINE`/`_BORDER`/`_ACCENT`/`_FILL`/`_GOLD`/`_OK`/`_WARN`), carried across palettes by `theme_palettes.is_theme_invariant` — the same predicate that keeps them out of the palette-distinctness measure, since a token identical on purpose is not evidence two palettes are too alike. `tests/test_cinema_surface_contrast.py` sweeps **by prefix**, so a new role is covered without anyone opting in.

### Text on a solid fill — `theme.on_fill(fill)`, never a hardcoded colour
A fill carries the palette (a `COLOR_OK` chip is mint in the dark themes and forest in Daylight), so the legible foreground flips with the FILL, not the theme; `on_fill()` picks between two fixed on-fill tokens by measured contrast and composes with runtime colours (provider hues, quality colours). Hardcoded `white` measured 1.88-2.51:1 on the mint/orange fills and 1.59-1.75:1 on the row badges — and a NAMED colour was invisible to the literal guard, which only hunted hex/rgba until it was widened. `COLOR_ON_ACCENT` is for a solid `COLOR_ACCENT` specifically and fails (1.57-3.25:1) on the other status fills. A translucent tint OF the app surface is a different case: use the surface's own ramp (`COLOR_TEXT_HI`), not `on_fill`. Guard: `tests/test_widget_composed_contrast.py`, which reconstructs the ~285 sheets built inside widget modules from the AST — the population no theme-layer test can see.

### Test doubles that skip `MainWindow.__init__` — wire them from `tests/conftest.py`
Skeleton hosts (`MainWindow.__new__`, a bare `_NavMixin`, a hand-rolled `_FakeHost`) miss whatever a cross-cutting method touches, and PyQt raises `RuntimeError` — not the `AttributeError` `hasattr` absorbs — so the guard itself explodes. Repair at the **shared factory** (`wire_channel_banner_widgets`, `wire_hide_channel_banners`), never with defensive `getattr`/`hasattr` in production, which masks real bugs. Three separate batches have gone red this way; each time the fix was one conftest helper, not N copies. Detail: docs/CRITICAL_RULES.md#tests.

### Tests must not pin an exact px/enum an improvement will move
A test asserting `minimumHeight() == 24` or "padding is symmetric" (satisfied by `0 == 0`) turns a deliberate improvement into a red gate, or passes on the broken state it was named to prevent. Assert the **floor plus the property that would break** — `>= 24`; equal *and* non-zero. Same family as the v0.21.0 `test_quality_chip_hugs_title_no_stretch` case that encoded the stretched geometry it was supposed to forbid.

### Channel-name fields — computed at ingestion, read at render
`detected_*` fields (`detected_prefix/quality/region/title/year`) are computed at ingestion by `update_detected_prefixes()` (`core/repositories/channel.py`) and stored; render code reads `channel.detected_*` directly and **never calls `parse_channel_name()`**. Detail + the one accepted `epg_watchlist_mixin.py` exception: docs/CRITICAL_RULES.md#channel-name-detected-fields.

### Content identity — one stored `content_key`, computed at ingestion, collapsed at read
Cross-source dedup has one identity field: `content_key`, computed at ingestion by `content_identity.content_key_for()` and stored (indexed) on `ChannelDB`. Every collapse surface reads the stored key (Browse/tag counts via `tag.py` `collapse_variants`, Discover via `_dedup_cards`, details "Other Versions" via `content_key ==`) — never a parallel heuristic; group on `COALESCE(content_key, 'id:' || id)`. The key is **tmdb-first**: `tmdb:{id}|{media_type}` when the ingested `detected_tmdb_id` (harvested from the provider's `raw_data.tmdb`) is present, else the normalized title/year key (#317, DR-0011). Spec: docs/CONTENT_IDENTITY.md; rationale DR-0009 + DR-0011; detail incl. the Phase-2 runtime-fingerprint layer (recommendations/Similar) and its known compromises: docs/CRITICAL_RULES.md#content-identity, docs/CRITICAL_RULES.md#content-dedup-compromises.

### Lookup tables — single source of truth
Region/country codes, quality tokens, audio-format maps, and channel-name parsing data live only in `metatv/core/channel_name_utils.py` (`REGION_FULL_NAMES`, `normalize_region_code`, …). Import from there; never define parallel dicts. A new code or alias goes in `channel_name_utils.py` only.

### Tags/facets — capture generously, label confidence + provenance
In the guessing zone, bias to recall: capture the facet a feeder denotes (high confidence) plus any *real* adjacent guess (low) — confidence is ranking/prune-priority, never a suppression gate; every tag records its feeder + read-vs-inference; hierarchy is rollup, not auto-tagging. Chokepoint: `tag_decomposer.py` (curated data: `channel_name_utils.py`). Rationale DR-0006; detail + worked examples: docs/CRITICAL_RULES.md#tags-and-facets.

### Icons — always from `metatv/gui/icons.py`
Every icon/emoji/symbol comes from `icons.py`, never a literal in widget code; add a new icon there first, never glyphs to `Config`. Collapse/expand uses `icons.expand_icon`/`icons.collapse_icon` (not the list-ordering arrows). Detail (collapsible nesting pattern): docs/CRITICAL_RULES.md#icons.

### Cursors — never `setCursor` directly; route through `metatv/gui/cursor_affordance.py`
Every clickable widget's pointing-hand cursor comes from `cursor_affordance.py` (`set_clickable()`; buttons qualify automatically; checkboxes/radio buttons excluded by convention) — a drift-guard test fails the suite on any other `PointingHandCursor` reference.

### Logging — always loguru
`from loguru import logger`; never `import logging`.

### Database sessions — `session_scope()` for new code
New code uses `Database.session_scope()` (commits on success, rolls back on exception, always closes); a bare `with session:` manages only the transaction, not cleanup — never use it. Legacy `get_session()` + `try/finally` is migration debt. Detail: docs/CRITICAL_RULES.md#database-sessions.

### ORM objects must not outlive their session — cross the boundary with a DTO
`session_scope()` expires on commit, so a detached ORM object's next attribute access raises `DetachedInstanceError`; map ORM → frozen DTO (`core/repositories/dtos.py`) inside the block and return that. Prefer a DTO over `session.expunge`. Detail + the `_apply_favorite_toggle` exception: docs/CRITICAL_RULES.md#orm-to-dto-boundary.

### SQLite JSON columns — `JSONEncoded`, assign plain Python objects
`Column(JSONEncoded)` serializes transparently — assign and read plain objects; never `json.dumps()` before assigning (double-encodes). Detail: docs/CRITICAL_RULES.md#sqlite-json-columns.

### Qt threading — signals only; QPixmap on the main thread
Qt widgets aren't thread-safe: workers emit signals, only the main thread touches widgets. **QPixmap is a GUI object** — never build it in a worker; emit the path string cross-thread and construct the pixmap in the main-thread slot. Deep dive: docs/THREADING_PATTERNS.md.

### Signal blocking during UI state restoration
Block signals before programmatically setting widget state (`blockSignals(True)` → set every widget → `blockSignals(False)`), then `.connect()` handlers in a separate pass — so restoring one widget doesn't fire another's slot. See docs/THREADING_PATTERNS.md → "Blocking Signals During State Restoration".

### EPG manager internals — worker-thread & fetch rules
Inside `EpgManager`/the fetch path: worker notifications go through private signals, never `NotificationManager` directly (it makes a main-thread `QTimer`); fetches run one at a time (`ThreadPoolExecutor(max_workers=1)`, else SQLite `database is locked`); resolve the fetch URL via `EpgManager.effective_epg_url(provider)`, never `provider.epg_url`; and `channel_name` **must** be populated at fetch (`relink_all()` re-matches on it — else the watchlist needs a manual Refresh). Detail: docs/CRITICAL_RULES.md#epg-manager-internals.

### Context filter chips — strict SQL filter, not the inclusive panel
A details-pane metadata click (genre/cast/director) activates a temporary **strict** SQL filter — never route through `filter_panel.select_only_genre()`; at most one chip active; text search narrows within it. Full pattern: docs/CONTEXT_FILTER_CHIPS.md; state details: docs/CRITICAL_RULES.md#context-filter-chips.

### Channel context menus — compose via `channel_menu.py`, never hand-roll a QMenu
Every channel menu is built by the registry in `metatv/gui/channel_menu.py` (`ACTIONS` + `SURFACE_LAYOUTS` + `build_channel_menu`); MainWindow-family menus gather context off-thread through the single `_show_channel_menu` seam. Don't regrow per-surface menus. Detail: docs/CRITICAL_RULES.md#channel-context-menus.

### Player instance keying — thread `provider_id`, never bypass `PlayerManager`
Every play path threads the channel's `provider_id` through to `player_manager.play(provider_id=…)` (resolves the per-source mpv instance key for Split Streams); `is_running`/`stop`/`get_properties` go through `PlayerManager(..., key=…)`, never `MPVPlayer` directly. Detail: docs/CRITICAL_RULES.md#player-instance-keying.

### Provider URL cycling — always `UrlCycler`, and always record the outcome
Trying a provider's alternate hosts has one path: `UrlCycler(provider, operation).candidates()` (`core/url_cycle.py`), with `record_success`/`record_failure` (latency included) after every attempt and `persist_url_stats()` to flush — never a bare `for base in provider.ordered_urls()`, which a drift-guard test (AST-based, so comments are fine) fails the suite on. Cycling without recording is the bug that shipped: five of seven paths cycled silently, so a 10-12s host stayed top-ranked forever — and then latency was accepted but passed by *nobody*, so the ranker's latency term sorted every host at `0` until #307 wired it. Record latency only on small, size-comparable requests: `fetch_channels` is deliberately excluded because it downloads the whole catalog and `median_latency_ms()` pools all attempts per URL, so a multi-minute bulk fetch mixed with ~300ms info calls makes the median meaningless. Ranking knobs come from the frozen `UrlRankingPolicy` (`core/url_policy.py`) resolved once at startup — low-level code holds no `Config`, same as `VisibilityScope`. Don't route through `ConnectionTracker` (async + a network call per attempt).

### Sidebar height — `MIN_ROWS` is a PREFERENCE, never a floor
A section has two limits: `preferred_expanded_height()` (what it asks for; honoured by automatic redistribution) and `min_expanded_height()` (the hard floor — header + border, for user dragging only). They were one value and the splitter enforced it as a wall, which pinned Watch Alerts at 367px. Under pressure a section folds its groups via `pressure_groups()`; `_auto_folded` is what makes auto-unfold safe — it may only re-open what it closed, never a group the user collapsed. Detail: docs/UI_UX_GUIDELINES.md → "Sidebar vertical space".

### View lifecycle & modal hiding — symmetric activate/deactivate
A view with `on_activate()` (timers/loads) must have a matching `on_deactivate()` (stop/cancel); the host calls them on switch, safest from `_hide_all_content_views()`. A sidebar-triggered modal in `_list_layout` must *also* register in `_hide_all_content_views()`, guard existence via `"view_name" in self.__dict__`, and pair enter/exit with activate/deactivate — else it lingers and keeps consuming async loads. Sibling: dialogs/editors emit a signal so the host refreshes dependent views. Detail: docs/CRITICAL_RULES.md#view-lifecycle · docs/CRITICAL_RULES.md#modal-and-overlay-views.

### Provider/source mutations → one canonical refresh
Every view derived from the provider/channel corpus refreshes through the single `MainWindow._refresh_provider_dependent_views()`; all mutations (add/edit/delete/toggle-active/visibility) funnel through it — never a partial per-call-site refresh (e.g. `load_providers()` alone leaves views stale). The account-info poll is the one sidebar-only exception. Detail: docs/CRITICAL_RULES.md#provider-mutations-refresh.

### Per-channel state mutations → `channel_state_bus.publish()`, never a hand-listed refresh tail
A mutation of one channel's user-state (rating/favorite/suppressed/hidden) ends in `self.channel_state_bus.publish(channel_id, **delta)` (`gui/channel_state_bus.py`) — never a hand-picked list of views to refresh, which is the enumeration that left the details pane's buttons frozen after a dislike (#311). Subscribers **self-register weakly**; tier 1 echoes synchronously with the delta, tier 2 always re-reads authoritatively off-thread. **List-membership** refreshes (`load_favorites()`, `_remove_sidebar_row()`, `_refresh_recommended_section()`) are a different grain — don't force them through `publish(channel_id)`. A test double driving a real mutation gets its bus from `tests/conftest.py`'s `attach_channel_state_bus()`, never a `hasattr` guard in production. Sibling of the provider-mutation rule above.

### Judgment applies to the title — collapse at read, never re-key `UserRatingDB`
Like/dislike/not-interested are stored one row per `channel_id`, but a title usually spans several rows, so taste is collapsed **at read** on the stored `content_key` (fallback `id:<channel_id>`) — `compute_weights()` emits one signal per title, not per row, else genre weights scale by variant count and `actor_support` defeats its own corroboration gate (#310). Never re-key `UserRatingDB` on `content_key` (it flips to the `tmdb:` form when enrichment lands, orphaning the row) and never migrate user rating rows. Do **not** widen `disliked_ids` to siblings: `build_engaged_normalized()` already suppresses them, and widening would bypass `dedupe_overrides`, hiding the very versions "Other Versions" exists to reveal.

### Engine/control/view layering & active-source scoping (DR-0007)
Three layers, one-way: **engine ← control ← view.** The engine takes scoped inputs and returns data with no visibility/encoding assumptions; every "what's visible / what `##` means" decision lives in the control layer (resolve content-format guesses at ingest, not in queries). Scope forward-looking views via `ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired) as `excluded_provider_ids`, never an ad-hoc set; EPG sibling `get_epg_active_provider_ids()`. Record/engaged views (History/Favorites/Queue) are exempt. Full split DR-0007; detail: docs/CRITICAL_RULES.md#active-source-scoping.

### Channel visibility — one predicate, `core/channel_visibility.py`
"Which channels are visible" has exactly one definition: build a `VisibilityScope` (a frozen bag of *already-resolved* exclusion sets — the control layer resolves them, the scope holds no `Config`) and call `apply(query, scope)`. Never hand-thread an exclusion axis onto a channel query, and never add an axis to one caller — add it to `VisibilityScope` so every surface gets it at once. All four legacy paths (`_apply_channel_filters`, `discovery_engine`, `preference_engine`, `tag.py`) are migrated. Detail + the authoritative migration table (the module's own docstring): docs/CRITICAL_RULES.md#channel-visibility.

### Resource cleanup in closeEvent — use the cleanup registry
Register each new background manager's shutdown right after construction via `self._register_cleanable("name", mgr.shutdown)` — never hand-edit `closeEvent` or add a `hasattr` block. Background pools/threads are owned once per object and stopped in the owner's cleanup path. Detail: docs/CRITICAL_RULES.md#closeevent-cleanup-registry.

### Background DB reads — offload, route through the async seam, surface failure
Any query scanning/aggregating large tables (channels, EPG — 240k+ rows) runs in an executor, never on the UI thread. New `MainWindow` reads go through the single `_run_query` seam (`_AsyncMixin`); sidebar `CollapsibleSection`s compose `BackgroundRefreshMixin`. `query_fn` returns plain data (DTOs), never ORM objects. On the `None`/error branch, render a visible error row via `show_load_error()` — never `clear(); return`. Detail: docs/CRITICAL_RULES.md#async-background-db-reads.

### Tests — prove behavior, never write real config
A green shape suite (`"x" in func`, attribute checks) is not coverage: every behavior-changing PR adds ≥1 test that executes the changed path and asserts the outcome that would break (DB-session work → real `Database` on a `tmp_path` file, not `:memory:`; async reads → the main-thread slot). Never write a test/docstring whose only effect is to look like coverage. **A green *unit* suite that never boots `MainWindow` is not proof the app launches** — a v0.14.1 init-order crash (wiring a signal to `_poster_lightbox` before it was created) passed the full suite green because nothing constructed `setup_ui()`; `tests/test_mainwindow_launch_smoke.py` now boots the real window in a subprocess to catch that class, so keep it green when touching `__init__`/`setup_ui` construction order. And never touch the real user config — the autouse `_isolate_user_config` fixture (`tests/conftest.py`) patches `Path.home()` to a tmp dir (guards a real data-loss bug); never weaken it, keep `tests/test_config_isolation.py` green, pass `config_dir=tmp_path` if a test needs config on disk. Detail: docs/CRITICAL_RULES.md#tests.

### UI state persistence — all sections must remember state
Every UI section (splitter size, collapse state, filter selections) saves to config and restores on startup: save immediately on change, restore during `__init__`. Full pattern: DESIGN.md.

### Architecture discipline — chokepoints, scope, ask early
Before adding a sibling function, grep the verb-cluster (`play_*`/`load_*`/`refresh_*`/`fetch_*`/`_on_*_ready`) for the existing chokepoint and share it; one concern per PR. Detail + cautionary case: docs/CRITICAL_RULES.md#architecture-discipline.

### A duplicate you find is fixed or LOGGED — never dropped
The three greps above keep finding real duplication mid-task: one quality→colour map shadowed by a flat role, three sub-group heading mechanisms in one section, two progress-bar painters with four hardcoded literals between them. Every one is found while building something else, which is exactly why it evaporates. **Fix it in the slice when it is mechanical and in scope; otherwise add a row to the ledger in docs/REFACTOR_PLAN.md ("Running duplication ledger") saying where the copies are and what actually DIFFERS** — a pure duplicate and a policy difference need different fixes, and calling a policy difference a duplicate is how a silent behaviour change ships. Never leave it only in a PR body or a commit message. Owner: "this will improve the codebase dramatically if we keep finding these."

### Naming anything new — grep FIRST, three greps, before you write it
The rule above says *function*; every miss is a **role, a config field, a signal handler, a widget on a dialog, an icon key**. Before adding any named thing: (1) grep for siblings of the same shape — a theme role, an icon role, a settings widget; (2) grep for who else CONSTRUCTS the object you are adding to, tests included, and add it to that shared factory in the same edit; (3) grep for the registry it must be listed in (`_SETTINGS_APPLIED_HOOKS`, `VECTOR_KEYS`, `wire_settings_*`). Seconds each, and they are the only form of this that has held — the fluent answer (`hasattr`, a fresh role, a hand-rolled layout) is usually correct Python and wrong *here*, so nothing prompts you to stop. One session produced six of these: `SIDEBAR_TOGGLE_BTN` beside `SIDEBAR_SUBSECTION_TOGGLE` nine lines away, a settings combo missing from the factory whose docstring promises it (43 tests red), a handler missing from `_SETTINGS_APPLIED_HOOKS`, `hasattr` on a `__new__`'d QObject (which raises `RuntimeError`, so the guard explodes), a hand-rolled form row, and an icon key already owned by another role. Detail: docs/CRITICAL_RULES.md#architecture-discipline.

## Metadata — year derived at ingestion

Read `metadata.year` everywhere (`MetadataManager._derive_year()` populates it at write from `release_date`, backfills pre-fix rows on read; no runtime parsing outside `metadata_manager.py`). Provider chain, `merge()` confidence scoring, and dedup compromises: docs/METADATA_SYSTEM.md, docs/CONTENT_IDENTITY.md.

## Coding Standards

- Python 3.11+ type hints on all signatures; Google-style docstrings on public APIs.
- Imports: stdlib → third-party → local, separated by blank lines.
- Files under 1000 lines; one class per file (helper classes excepted). **1000 is a round number, not a finding** — it is a good place to STOP AND LOOK at what a file is actually doing, not a verdict that it is wrong. The guard's value is its *direction* (`limit = max(1000, baseline)`: shrink freely, never grow), which needs no theory of correct file size; and a breach is answered by cohesion, not arithmetic — "split by isolation, not the line count" (docs/AUDIT_2026-06-19.md). A 1400-line file doing one job needs no split; a 600-line file doing three does.
- `ThreadPoolExecutor` for blocking I/O; `asyncio` for async providers; `QTimer.singleShot(0, ...)` for deferred main-thread execution.
- **Every PR with user-visible behavior adds `metatv/whats_new/entries/NNNN_slug.py`** (zero-padded next id via `python -c "from metatv.whats_new import latest_id; print(latest_id() + 1)"`) with `ENTRY = WhatsNewEntry(...)` including a **non-empty `test_steps`** tuple — the dev-QA smoke test (`METATV_DEV=1`), each step an action + expected outcome covering the changed path. `test_steps` is the default; omit (with a one-line PR note) only for no-behavior refactors or dev-only tooling. Never edit the shared list. Format + examples: `metatv/whats_new/entries/README`.

## Agent & Test Operations (Claude Code — binding, owner-mandated)

One directive per rule; violations here have burned real money and real trust. No exceptions without the owner saying so in the moment.

### CI tests every pull request — the local gate is now a fast pre-check
`.github/workflows/ci.yml` runs the FULL suite on Linux and macOS for every PR. That is the
authoritative gate; `--quick` is a local pre-check to catch the obvious before pushing, not a
substitute. The rule below was written when no CI existed and the local gate was all there was.

**Why it exists, so nobody removes it:** `--quick` runs only a PR's OWN changed test files, so a
cross-cutting change breaks files the PR never touched and nothing reports it. That is not
hypothetical — 58 failures accumulated across five merges in one week, and the macOS release build
failed on every push for three weeks with eight failures that pre-dated all of it.

### One gate, no double-testing
Feature-work merges gate with **`--quick`** (launch smoke + the PR's own changed test files, seconds); the **full** suite runs before a release and at session wrap. Owner's call, and the reason is rhythm: a 10-minute gate per PR turns an hour of building into an afternoon of waiting. `--quick` keeps the one failure that is expensive to miss mid-session — the app not launching — because `main` ships to `rolling` on every push and that is the owner's own build.
Each implementer agent runs its OWN new/changed test files ONCE — that is the slice's verification. The coordinator runs **exactly one full-suite gate per merge batch**, on the final integration tree **with the release chore already applied** (one green covers integration + release). A red gate → fix → one new gate; nothing else ever triggers a rerun. Never: per-PR verify runs, interim pytest batches after conflict resolutions or inline fixes, separate release-chore test runs, or re-running an agent's tests.

### A verified slice gets merged, not resumed
Once an agent's brief is satisfied and the work is verified, **merge it**. A new want is a NEW slice with its own brief and budget — never a resume. Each resume compounds on the agent's whole prior context, so a "small" follow-up can cost more than the original slice; a finished theme slice resumed twice burned ~600k tokens and sprawled across 10+ unbriefed files before being killed and discarded wholesale. Resume ONLY to fix something wrong with the delivered work, never to add scope. **If the follow-up would touch files the original brief never named, that is the signal it is a new slice.** Watch the agent's token counter as the tell: past ~2× the <100k target, end the engagement rather than extend it.

### UI slices must assert rendered appearance
A UI test that checks parsed data, cell ORDER, or token existence passes for infinitely many wrong-looking renderings — order ≠ position, token-defined ≠ token-correct. Every UI slice adds ≥1 assertion on **rendered appearance** (painted `QRect` geometry via a captured `_paint_cell`/`_draw_text`; palette luminance/contrast/distinctness), and it must be proven to FAIL against the pre-fix code. Two v0.21.0 defects shipped through a green suite this way, incl. a test *named* `test_quality_chip_hugs_title_no_stretch` that asserted the stretched-box geometry — a spec-named test encoding implementation behaviour is worse than no test, because it looks like coverage and blocks the fix. Templates: `tests/test_category_marker_row_layout.py` (geometry), `tests/test_palette_completeness.py` (palette).

### Subagent dispatch
The coordinator PLANS COMPLETELY; agents only execute. Model ladder: **Haiku + `effort: "low"`** for prescriptive work (the brief names the files, the edits, and the test cases — the agent types, it doesn't think); **Sonnet + low** only when a slice genuinely requires local judgment; medium and above only with the owner's per-case blessing. **A brief that says "pick an approach" or "decide X" is under-planned — the coordinator makes every design decision IN the brief.** One concern per slice (<100k target; Haiku slices should land well under 50k). Briefs inline the 3-5 applicable rule bullets (never doc-reading assignments) and always carry: pre-assigned What's New id(s), "run only your new/changed test files once — no adjacent-file batteries; the merge gate covers integration", worktree isolation, rebase-before-PR, do-not-merge.

### The owner's checkout is sacred
The owner UX-tests via `./run.sh` from this checkout — it always rests on the current release tree. ALL coordinator branch work happens in temp worktrees; never `git checkout` a work branch here.

### Local Python 3.14 hides annotation errors that CI's 3.12 catches
This machine runs Python 3.14, where annotations are evaluated lazily (PEP 649); CI runs 3.12, which evaluates them eagerly. A function annotated with a name the module never imports passes the local gate and fails CI at import time. When a slice moves code between modules, verify every annotation's name is imported in its new home — the local suite will not tell you.

### Shell discipline for gates
Never pipe a test run through `tail`/`head`/`grep` in the same command that decides success — the pipe eats the exit code (this has shipped a red PR). Redirect to a log, capture `$?`, decide on it.

### Design work
Mockups start from a faithful inventory of the CURRENT app (code transcription with file:line anchors); proposals render side-by-side vs current with **every delta a numbered question** (Q-tags). Roadmap concepts are never pre-applied as settled layout.

## Releases — rolling by default

**Every push to `main` builds and publishes to one moving release tagged `rolling`** (`.github/workflows/release.yml`). There is no per-release chore and no version to choose: the tester bookmarks one URL and always gets the newest build. A `v*` tag still cuts an immutable release when a milestone genuinely warrants one — the two paths coexist.

The identifier is derived, never hand-chosen: `<version>+<UTC date>.<short sha>`, stamped into `metatv/_build_id.py` (gitignored) before PyInstaller so a packaged app's title bar names the exact commit. `metatv/__init__.py`'s `__version__` survives only as the What's New batch label. **Because a push ships to the tester, `main` must always be green** — run the full suite before pushing, not after.

## Session Wrap SOP

On "let's wrap up" / "wrap this session", follow docs/SESSION_WRAP.md in order: tests (`pytest tests/ -x -q`) → commit everything → **roadmap reconciliation gate** → **release-claims audit** → update stale docs → update CLAUDE.md → refresh memory (`project_session_handoff.md`) → `git push origin main` → confirm what landed.

### Shipped means proven, never planned
A wave/release scope list is intent, not evidence. **A claimed item with no What's New entry did not ship** — record it NOT BUILT (or cite a `file.py:line` anchor for genuinely invisible work), and never promote a plan, a brief, or an agent's self-report into a memory of delivered work. Ten releases drifted and three phantom Wave-7 items entered memory as fact before this was mechanical. Gates: `scripts/roadmap_audit.py` (+ `--version X.Y.Z`); detail: docs/SESSION_WRAP.md steps 3-4.

Dev/manager scripts live in `scripts/` (config via optional repo-root `.devscripts.conf`, docs in `scripts/README.md`): `verify_pr.sh <PR#>` = full-suite gate that tests the merge result with a GREEN/RED verdict (`--quick` = launch smoke + the PR's own changed test files, for feature work — never for a release), `merge_pr.sh <PR#>` = verify→merge→prune in one command (takes `--quick` too), `prune_merged.sh` = safe merged-worktree/branch cleanup, `roadmap_audit.py` = roadmap reconciliation watermark + per-release claims audit.

## Migration Status

These legacy forms coexist with the rules above — new code follows the rule, don't extend the debt: `config.<name>_icon` → `icons.*`; `get_session()`+`try/finally` → `session_scope()`; inline `font-size: Npx` → `FONT_*`; `session.expunge` → DTO.

## Reference Docs

| Topic | File |
|---|---|
| **Critical Rules — full detail (code, exceptions, rationale)** | docs/CRITICAL_RULES.md |
| **Product vision & direction (north star)** | docs/PRODUCT_VISION.md |
| UI/UX interaction patterns | docs/UI_UX_GUIDELINES.md |
| Qt threading deep dive | docs/THREADING_PATTERNS.md |
| Metadata system architecture | docs/METADATA_SYSTEM.md |
| Filtering design | docs/FILTERING_DESIGN.md |
| Context filter chips | docs/CONTEXT_FILTER_CHIPS.md |
| Details pane design | docs/DETAILS_PANE_DESIGN.md |
| Xtream API schema | docs/xtream_api_schema.md |
| UI state persistence patterns | DESIGN.md |
| Roadmap | ROADMAP.md |
| Refactor / dedup / cleanup plan | docs/REFACTOR_PLAN.md |
| Current audit + **Band 10** remediation plan | docs/AUDIT_2026-06-19.md |
| **`channel.py` split — planned slices + constraints** | docs/CHANNEL_REPOSITORY_SPLIT.md |
| **Watch Alerts rebuild — decisions, traps, what's left** | docs/WATCH_ALERTS_REBUILD.md |