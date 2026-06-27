# Critical Rules — full detail

Companion to the **Critical Rules** section of [CLAUDE.md](../CLAUDE.md). CLAUDE.md is loaded every turn, so each rule there is one directive + a pointer; the code examples, every-call-site enumerations, exceptions, and rationale live here and are read on-demand when a task touches that area.

When a rule already has a dedicated deep-dive doc (threading, theming, content identity, the DR-NNNN rationale log), CLAUDE.md points straight at it and this file does not duplicate it. The sections below cover the rules that have no other home.

---

## EPG time and timezone

Directive lives in CLAUDE.md. Helpers live in `metatv/core/epg_utils.py`; never redefine inline or open-code timezone conversions.

- `EpgProgramDB.start_time` / `stop_time` are UTC-naive. Display → `to_local`. "Today"/weekday → `is_local_today` / `local_weekday` (never `.date() == date.today()`, which is UTC-anchored and wrong for non-UTC users). Arithmetic (remaining, progress) → compare UTC-naive against `now_utc()`.
- `epg_is_stale(epg_data_end)` is the single staleness boundary (a feed serving year-old guide data). The EPG view's banner list comes from `ProviderRepository.get_stale_epg_providers()`.

Full helper list: `now_utc`, `fmt_time`, `remaining_str`, `minutes_away`, `progress_pct`, `fmt_duration`, `epg_is_stale`, `to_local`, `is_local_today`, `local_weekday`, `local_day_window`.

## Styles and theme tokens

Full rationale: [UI_UX_GUIDELINES.md](UI_UX_GUIDELINES.md) → "Theming & style tokens". Two layers:

1. **Design tokens** (`COLOR_*`, `FONT_*`, `OVERLAY_*`) — the only place a raw hex/rgba literal or a font *size* may appear.
2. **Semantic constants** — full stylesheet strings composed from tokens, named by **role** (`STATUS_OK`, `LOADING_TEXT`), never by appearance.

- **Colors strict:** never inline a hex/rgba literal anywhere, including dynamic styles (`f"color: {_theme.COLOR_WARN};"`); always a `COLOR_*`/`OVERLAY_*` token. The codebase has zero stray color literals — keep it that way.
- **Font sizes:** `FONT_*` tokens, never `font-size: Npx`.
- **Structural-spacing px is fine inline** — `padding`/`margin`/`border-radius`/`setFixedWidth` have no token.
- A stylesheet string used by **>1 widget** must be a named role-based constant (`from metatv.gui import theme as _theme`); never copy-paste between files. Need a variant → add a new role constant, don't widen an existing one.

## Channel-name detected fields

All `detected_*` fields (`detected_prefix`, `detected_quality`, `detected_region`, `detected_title`, `detected_year`) are computed at ingestion by `update_detected_prefixes()` in `metatv/core/repositories/channel.py` and stored. **Never call `parse_channel_name()` in render-time display code** — read `channel.detected_*` directly.

```python
# Correct — render reads stored fields
bare = channel.detected_title or channel.name
year_str = f" · {channel.detected_year}" if channel.detected_year else ""

# Wrong — parsing at render time
_p = parse_channel_name(channel.name)
```

**One accepted exception:** `_make_recommendation_item` / `_make_channel_item` in `gui/epg_watchlist_mixin.py` still parse at render to derive audio/lang chips — there is no stored `detected_*` field for those. The audit does not flag this; every other surface reads stored fields.

## Content identity

Cross-source dedup has **one identity field**, not a per-surface heuristic. `content_key` is computed at ingestion by `content_identity.content_key_for()` inside `update_detected_prefixes()` and stored (indexed) on `ChannelDB`. Full spec: [CONTENT_IDENTITY.md](CONTENT_IDENTITY.md); rationale: DESIGN_RATIONALE **DR-0009**.

- **Compute once, read everywhere** (same rule as `detected_*`): the key is `{norm_title}|{media_type}` for series/live (year dropped — provider year labels are noisy) and `{norm_title}|movie|{start_year}` for movies. Director + metadata-year are excluded (unavailable at ingest). Never re-derive a dedup key at query/render time.
- **Collapse reads the stored key — never a parallel heuristic.** Browse/Recipe Show-All + tag counts collapse via `tag.py`'s `collapse_variants` path (`_build_collapsed_sample_query` window functions / `COUNT(DISTINCT …)`); Discover via `discovery_engine._dedup_cards`; details "Other Versions" via `content_key ==`. Adding a new browse/shelf/count surface → route through one of these, don't write a third dedup.
- **NULL-guard is mandatory:** group on `COALESCE(content_key, 'id:' || id)`. A bare `PARTITION BY content_key` merges every un-backfilled NULL row into one phantom group.
- **Phase 2 exception:** Recommendations + the Similar lightbox still use the richer runtime fingerprint in `content_dedup.py` (includes director) — don't "unify" them onto `content_key` without the deliberate re-base wave (DR-0009).

## Content dedup compromises

Two dedup layers coexist (see DR-0009 + [CONTENT_IDENTITY.md](CONTENT_IDENTITY.md)). Browse / Recipe Show-All / Discover / details "Other Versions" / tag counts collapse on the **stored `content_key`** (coarse: no director). The runtime fingerprint below is the **richer** key still used only by **Recommendations + the Similar lightbox** (Phase 2 will re-base those onto `content_key`). When metadata lands, a canonical TMDb/IMDb id replaces the `content_key` string in place.

`content_dedup.py` groups same-production channels across providers by a `(norm_title, media_type, year, director)` fingerprint — a heuristic stopgap until TMDb/IMDb canonical IDs are wired up (ROADMAP). Deliberate trade-offs:

- **Director excluded for series.** Many episode directors / inconsistent attribution cause false splits (same show appearing twice). Movies keep director — a single director is reliably credited and distinguishes remakes.
- **Null-year absorption.** A candidate with no year (in name or MetadataDB) is suppressed if a year-bearing engaged variant with the same `(norm, media_type)` exists (e.g. a no-year `Rick and Morty` when `Rick And Morty (2013)` is queued). Risk: a genuinely different same-name no-year series could be suppressed — accepted as rare.

Net effect: the recommendations list may occasionally hide a legitimate alternative or surface an unexpected variant. Don't tighten these without first checking the failing case isn't better fixed by improving metadata completeness (year in channel name, consistent director field). Canonical-ID primary key and a dedup-transparency toggle are tracked in ROADMAP.

## Tags and facets

In the guessing zone, bias to recall: a false negative is invisible and unfixable; a false positive is visible and one-click-correctable (and teaches the system). Full rationale + worked examples: DESIGN_RATIONALE **DR-0006**. Chokepoint: `tag_decomposer.py`. Curated code→facet + base-confidence data: `channel_name_utils.py`.

- A feeder yields the facet it **denotes** (high confidence) **plus** any *real* adjacent guess (low) — both captured, never withheld (`FR` → `language:French` high + `region:France` low). A real candidate must exist: `EN` → `language:English` only. A confident signal overrides a prior (`LAT` = `language:Latin American Spanish`, never merged into `Spanish`).
- **Confidence = ranking + prune-priority, never a suppression gate** — low-confidence tags still surface.
- **Every tag records its feeder + read-vs-inference**; the UI ships source-given vs ingestion-inferred labels *with* the capture.
- **Hierarchy is rollup, not auto-tagging:** `LAT ⊂ Spanish` is certain containment; a `region:Mexico` channel never silently gains `language:Spanish`.

## Icons

Every icon/emoji/symbol in the UI comes from `metatv/gui/icons.py`, never a literal in widget code (media-type, action, header, status — everything).

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

## Database sessions

`Database.session_scope()` commits on success, rolls back on exception, always closes:

```python
with self.db.session_scope() as session:
    repos = RepositoryFactory(session)
```

A bare `with session:` manages only the *transaction*, not cleanup — never use it. (Legacy `get_session()` + `try/finally` remains in old code — see Migration Status in CLAUDE.md.)

## ORM to DTO boundary

`session_scope()` exits with `expire_on_commit=True`, so a still-attached ORM object's next attribute access raises `DetachedInstanceError`. A frozen DTO (`core/repositories/dtos.py`) is a session-free *value* — it severs the dependency and keeps the schema free to add a `relationship()`/`deferred()` column without breaking the UI.

- Map ORM → DTO/dict *inside* the block and return that (`_run_query` enforces "never return ORM objects"). No ORM crosses worker→main.
- `session.expunge(obj)` is a fragile fallback (regresses the instant a `relationship()`/`deferred()` column is added) — prefer a DTO; if you keep an expunge site you own auditing it.
- `_apply_favorite_toggle` is the documented exception: `toggle_favorite()` commits internally and `session.refresh()` repopulates *before* close, so `session_scope`'s exit-commit would re-expire. Don't "modernize" it blindly.

## SQLite JSON columns

`Column(JSONEncoded)` (defined in `database.py`) serializes transparently. Assign and read plain objects — no `json.dumps/loads`. Never `json.dumps(value)` before assigning (double-encodes).

```python
metadata.cast = result.cast      # assign a list
cast = metadata.cast or []       # read a list back
```

## EPG manager internals

Rules for code inside `EpgManager` / the EPG fetch path.

**Notifications — never from a worker thread.** `NotificationManager.show()` creates an auto-dismiss `QTimer` (main thread only); all worker notifications go through private signals (`_notify`, `_progress_update`, `_progress_done`, `_progress_error`) that Qt queues to the main thread.

**One fetch worker at a time.** `EpgManager` uses `ThreadPoolExecutor(max_workers=1)`; two concurrent XMLTV fetches cause SQLite `database is locked` (each does bulk-delete + bulk-insert). Providers fetch sequentially.

**Per-provider config — three columns + one URL chokepoint.** Each `ProviderDB` row carries:

- `epg_enabled` (bool) — `False` skips the provider in the fetcher, excludes it via `get_epg_active_provider_ids()`, and purges its programmes via `EpgManager.purge_provider_epg()`.
- `epg_refresh_interval` (String enum) — `"default"` inherits `Config.epg_default_refresh_interval` (default `"3d"`); throttle logic in `EpgManager.needs_refresh()`.
- `epg_url_override` (optional XMLTV URL).

Resolve the fetch URL only via `EpgManager.effective_epg_url(provider)` — never read `provider.epg_url` directly.

**`channel_name` must be populated at fetch.** `EpgProgramDB.channel_name` stores the XMLTV display-name, written at fetch (`_fetch_worker` builds `chan_name_map`). `EpgManager.relink_all()` re-matches existing rows by this name (fuzzy tiers) — which is what makes the watchlist/Watch-Alerts populate without a manual Refresh. **Never stop populating it** or the "watchlist empty until you click Refresh" bug returns. Legacy nameless rows trigger a one-time re-fetch via `EpgRepository.has_unmatched_unnamed_epg()`.

## Context filter chips

Clicking a details-pane metadata value (genre/cast/director) activates a temporary context filter using a **strict** SQL filter — not `filter_panel`'s inclusive genre logic (which has a no-data passthrough). Full pattern: [CONTEXT_FILTER_CHIPS.md](CONTEXT_FILTER_CHIPS.md).

- Never route details-pane clicks through `filter_panel.select_only_genre()` or similar.
- At most one context filter is active; activating one clears the others.
- Text search coexists — typing narrows *within* the chip; it does not dismiss it.
- Chip styles from `theme.CONTEXT_FILTER_CHIP*`. State in `_details_*_filter` on `MainWindow`, passed through `load_channels()` → `get_all()`.

## Channel context menus

Every channel context menu is built by the registry in `metatv/gui/channel_menu.py` (`ChannelMenuContext` + `ACTIONS` + `SURFACE_LAYOUTS` + `build_channel_menu`). Do not regrow the old per-surface menus.

- Add an action: define it once in `ACTIONS` (label/icon/tooltip/`applies`), list its id in the relevant `SURFACE_LAYOUTS` entry, supply a handler at the call site. An id absent from a site's `handlers` is silently skipped — that's how surfaces opt in/out.
- MainWindow-family menus gather context **off-thread** through the single `_show_channel_menu` seam (`_bg_fetch_ctx_data` → `_ctx_data_ready` → `_on_ctx_data_ready`) — not bespoke `executor.submit` + inline `QMenu`.
- EPG/Preferences views build locally via `build_channel_menu`, delegating core handlers (play/favorite/queue/rate) to the MainWindow host.
- Non-channel menus (filter dropdowns, column headers, details chips) are out of scope.

## Player instance keying

mpv runs as a per-source instance registry (Split Streams). `PlayerManager.play(url, title, provider_id=…, force_new_window=…)` resolves the instance key — `"__shared__"` when split is off, the `provider_id` when `config.split_streams_by_source` is on or `force_new_window=True`.

- Every play path **threads the channel's `provider_id`**: `play_media` → `_bg_validate_and_play` → `_stream_ready` payload → `_on_stream_ready` → `player_manager.play(provider_id=…)`. Dropping it breaks Split Streams.
- `is_running`/`stop`/`get_properties`/`active_keys` go through `PlayerManager(..., key=…)`. Never touch `MPVPlayer`'s process/socket directly.

## View lifecycle

If a view has `on_activate()` (starts timers, loads data) it must have `on_deactivate()` (stops timers, cancels pending work). The host (`main_window.py`) calls `on_deactivate` for the departing view and `on_activate` for the arriving one. Safest: call `on_deactivate()` inside `_hide_all_content_views()` for any currently-visible view.

## Modal and overlay views

A modal/overlay stacked in `_list_layout` and triggered by sidebar buttons (not chip nav) must:

1. Be added to `_hide_all_content_views()` (calls `on_deactivate()` if visible, then hides).
2. Check existence via `"view_name" in self.__dict__` (safe for mocked test objects).
3. Have an enter method that hides others, shows the view, calls `on_activate()`.
4. Have an exit method that calls `on_deactivate()` and returns to list view.

Otherwise the modal lingers when users navigate away via chips and keeps consuming async loads.

Sibling rule: when a dialog/editor mutates data shown elsewhere (sidebar, list, details), emit a signal the host connects to a refresh of the affected view (e.g. the editor's `account_info_updated = pyqtSignal(str)` → MainWindow refreshes the Sources section) — prevents stale, out-of-sync views.

## Provider mutations refresh

Every view derived from the provider/channel corpus refreshes through the single `MainWindow._refresh_provider_dependent_views()` (sidebar Sources/Favorites/History/Queue/Recommended; main list/search incl. `provider_icon_map`; lazy Discover/Preferences overlays). All mutations funnel through it — add/edit/delete/toggle-active/toggle-visibility. Never re-implement a partial refresh at a call site (e.g. `load_providers()` alone — that recurring shortcut left views stale, most visibly a new source showing content with no icon badge). The account-info poll (`_on_account_info_updated`) is the one exception: it changes only the Sources display, so a sidebar-only refresh is correct.

## Active-source scoping

Content from inactive (toggled-off) or expired sources must never appear in a forward-looking view. Single source of truth: `ProviderRepository.get_hidden_provider_ids()` (= inactive ∪ expired), passed as `excluded_provider_ids` by the channel list (`_bg_load_channels`), Discover shelves/See-All (`discover_workers`), and recommendations (`preference_engine.score_candidates`). Never rebuild this set ad-hoc (e.g. `get_expired_provider_ids()` alone leaked disabled-but-unexpired sources into Discover).

- EPG/watchlist include-list sibling: `get_epg_active_provider_ids()` (= active ∧ not-expired ∧ has `epg_url` ∧ `epg_enabled`), passed as `provider_ids`.
- **Exception — record/engaged views (History, Favorites, Watch Queue)** show prior engagement regardless of current source state (you watched it; the source going inactive doesn't erase that). Recommendation *weights* still learn from engaged items on inactive sources; only the surfaced candidate *pool* is scoped to active sources.

Engine/control/view split rationale: DESIGN_RATIONALE **DR-0007**. The engine stays scope-agnostic (caller supplies `base_channel_ids`); the control layer scopes with `get_hidden_provider_ids()`. A single shared `visible_channel_filter` predicate is the target — tracked as task #59, not yet built; until it lands, match the file's existing convention and don't widen the inline `is_hidden`/`##` smear. Content-format guesses are ingestion-only — resolve `##`/placeholders at ingest into a stored field; never re-pattern-match in queries.

## closeEvent cleanup registry

`MainWindow` owns `self._cleanables: list[tuple[str, callable]]`. Register every new background manager's shutdown immediately after construction — `self._register_cleanable("my_manager", self.my_manager.shutdown)` — never add it to `closeEvent` by hand. `closeEvent` iterates `_cleanables` (exceptions caught per-entry, so one failure never blocks the rest); never add a `hasattr(self, "manager_name")` block. (`db.close()` and the view-deactivation loop stay explicit — they need sequencing/visibility logic.)

Background pools/threads: create a `ThreadPoolExecutor`/`QThread` once per owning object, never per call (a pool inside a method that runs more than once is a thread leak). Stop every pool/thread in its owner's cleanup path — `closeEvent` for managers, `on_deactivate` for views. Prefer the owner's shared `self.executor` for one-off background work over a throwaway pool.

## Async background DB reads

Threading deep dive: [THREADING_PATTERNS.md](THREADING_PATTERNS.md). Three composed rules:

**No unbounded DB work on the UI thread.** Any query that scans/filters/aggregates/counts over large tables (channels, EPG — 240k+ rows) runs in an executor and marshals results back via signal. Trivial primary-key lookups inline are fine; anything that grows with library size must be offloaded. Watch: startup stat initialization, sidebar `refresh()`, context-menu lookups.

**`_run_query` is the single async-read seam on `MainWindow`** (`_AsyncMixin`, `metatv/gui/main_window_async.py`). All new background reads use it — never ad-hoc `executor.submit` + manual signals.

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

**Background refresh failure must be visible — never silently blank a list.** On the `None`/error branch of `_on_data_ready`, render a distinct, non-selectable error row via `CollapsibleSection.show_load_error(list_widget, "Couldn't load …")` (adds a warning row, keeps the section expanded). Never `clear(); return` on failure — an empty "you have nothing here" state is a lie when the query actually threw.

## Tests

**Tests must prove behavior, not shape.** Shape tests (`"session_scope" in func`, attribute-present checks, name checks) are cheap insurance against a careless edit, but a green shape suite is **not coverage** — it stays green through the exact regression it appears to guard.

- Every behavior-changing PR includes ≥1 test that executes the changed path and asserts the outcome that would actually break. For DB-session work: drive the real handler against a real `Database` (`create_tables()` on a `tmp_path` file — not `:memory:`, whose pooled connections each get an empty DB), let the scope close, then assert a detached column is still readable.
- For async reads, the regressing half is the **main-thread `on_result`/`_on_data_ready`** (sorting, continue-vs-never split, icon mapping, episode-code rendering, empty state, failure row) — not the boring worker half. Construct the widget via `__new__`, hand it a real `QListWidget` (headless via the module `qapp` fixture) or a `_FakeLabel`, call the slot, assert the rendered rows.
- Never write a test (or docstring) whose only effect is to look like coverage. A docstring must not claim an invariant that no assert actually checks.

**Tests must never write the real user config.** `Config` paths default to `Path.home()/…`; a default `Config()` that saves (directly or via a handler calling `config.save()`) overwrites the developer's real `~/.config/metatv/config.yaml`, wiping Global Exclusions, the What's-New cursor, and migration version fields — a real, repeated bug that looked like flaky data loss. The autouse `_isolate_user_config` fixture in `tests/conftest.py` monkeypatches `Path.home()` to a throwaway tmp dir for every test.

- Never remove/weaken it or `monkeypatch.undo()` it. `tests/test_config_isolation.py` guards it — keep it green.
- A test that genuinely needs config on disk passes `config_dir=tmp_path` explicitly. No test writes outside its tmp dirs.

## Architecture discipline

The proactive form of the Governing Principles.

- **Find the existing path before adding a sibling.** Grep the verb-cluster (`play_*`/`load_*`/`refresh_*`/`fetch_*`/`_on_*_ready`) and the repo/manager method or seam you're about to call before writing a new one. A core primitive called from >1 UI site is a chokepoint — one entry, every caller gets the full behavior. Need a variant → share the core (one helper both call), never copy-paste-and-trim. Semantic duplication is invisible to syntactic greps — read behavior. (Cautionary case: a duplicate play path that silently dropped failover/buffering and rotted as fixes landed only on the canonical path — see [AUDIT_2026-06-19.md](AUDIT_2026-06-19.md).)
- **One concern per PR.** Discover a larger problem mid-task → record it in the backlog (task tracker, or the active `docs/REFACTOR_PLAN_BAND*.md`) as a new item; don't expand the PR and don't paper over it.
- **When the correct path is unclear, ask.** A one-line clarifying question beats inventing a third pattern.
