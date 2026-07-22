# MetaTV — Refactor, Dedup & Best-Practices Plan

**Audience:** an implementing agent (Sonnet).
**Source:** full-codebase review on 2026-06-01 (main @ d194dad, 94 files / ~32k LOC).
**Goal:** fix best-practice violations, remove duplication, and break up oversized
files — without changing user-visible behavior except where a task explicitly fixes a bug.

## Ground rules for the implementer

1. **Follow `CLAUDE.md` critical rules.** Several tasks below exist *because* a rule
   was violated. Do not introduce new violations while fixing old ones.
2. **Small commits, one task per commit.** Each task lists its own acceptance check.
3. **Run the test suite after every task:** `venv/bin/python -m pytest tests/ -x -q`.
   All must pass. If a task changes behavior, add/adjust a test.
4. **No behavior change unless the task says so.** P0 tasks fix real bugs; everything
   else must be a pure refactor (same runtime behavior, smaller/cleaner code).
5. Work top-down: P0 → P1 → P2 → P3. Stop and report if any task's premise no longer
   matches the code (it may have been fixed since this plan was written).

---

## Priority 0 — Correctness-adjacent violations (do first)

### P0-1 — `provider_loader.py` uses `with session` (session leak)
- **Where:** `metatv/core/provider_loader.py:400` — `with self.db.get_session() as session:`
- **Rule violated:** *"Database sessions — try/finally, never `with session`."*
  `with session` manages the transaction but never calls `session.close()`, so the
  connection leaks for every series-info store.
- **Fix:** convert to the canonical pattern:
  ```python
  session = self.db.get_session()
  try:
      ...   # existing body
  finally:
      session.close()
  ```
  Preserve the existing commit/rollback logic inside the body.
- **Accept:** no `with .*get_session()` remains in the file; series load still stores
  seasons/episodes; tests pass.

### P0-2 — EPG Browse date picker uses local date against UTC-naive storage
- **Where:** `metatv/gui/epg_view.py:435` (`today = date.today()`), consumed at
  `epg_view.py:797` (`target_date = self.date_combo.currentData()`) → passed to
  `metatv/core/repositories/epg.py:137-165`, which builds
  `day_start = datetime(target_date.year, target_date.month, target_date.day, 0,0,0)`
  and compares against UTC-naive `EpgProgramDB.start_time`.
- **Rule violated:** *"EPG times — stored as UTC-naive… never compare `.date()` directly
  against `date.today()`."* The picker offers *local* calendar days, but the repo query
  treats the chosen day as a *UTC* window. For any non-UTC user the "Today" tab shows the
  wrong slice of programmes (shifted by the UTC offset).
- **Fix (choose the consistent convention and document it):** the repo `browse_*` query
  must convert the requested *local* day into the matching UTC-naive window before
  comparing:
  ```python
  # target_date is a LOCAL calendar date chosen in the picker
  local_start = datetime(target_date.year, target_date.month, target_date.day, tzinfo=local_tz)
  day_start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
  day_end   = (local_start + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
  ```
  Use the machine local tz (`datetime.now().astimezone().tzinfo`). Apply the same
  conversion to the time-slot ("Morning/Afternoon/Evening") slicing at
  `epg.py:181-182`.
- **Accept:** add a unit test in `tests/` that, with a frozen non-UTC local tz, a
  programme at UTC `2026-06-01T02:00` is returned for the correct local browse day.
  Existing EPG tests pass.

---

## Priority 1 — Deduplication (pure refactors)

### P1-1 — Single helper for parsing `provider.urls` JSON
The "coerce `provider.urls` (JSON string *or* list) into a list[dict]" boilerplate is
copy-pasted in **at least 6 places**:
- `metatv/core/repositories/provider.py:71-76`
- `metatv/core/provider_loader.py:98-100`
- `metatv/core/epg_manager.py:88-94`
- `metatv/gui/main_window.py:2882`
- `metatv/gui/main_window.py:3768-3771`
- `metatv/core/repositories/provider.py:74` (and the write-back variant in
  `provider_loader.py:110` that re-serializes with `json.dumps`)

- **Fix:** add one canonical helper next to the provider repository, e.g.
  `metatv/core/repositories/provider.py`:
  ```python
  def parse_provider_urls(raw: str | list | None) -> list[dict]:
      """Coerce a ProviderDB.urls value (JSON string or list) into a list of dicts."""
      if isinstance(raw, str):
          try:
              raw = json.loads(raw)
          except Exception:
              return []
      return [u for u in (raw or []) if isinstance(u, dict)]
  ```
  Replace every site above with a call to it. Keep the existing write paths using
  `json.dumps` (per the JSON-serialization rule) but read through the helper.
- **Accept:** no remaining inline `isinstance(..., str): json.loads` for `urls`;
  provider load, EPG URL build, and stream failover all still work; tests pass.

### P1-2 — Collapse duplicated favorite-toggle into one method
- **Where:** `metatv/gui/main_window.py` — `toggle_favorite` (~line 2785) and
  `toggle_favorite_by_id` (~line 2966) are near-identical (open session → repo →
  `toggle_favorite` → set `channel.is_favorite` → status-bar message). This is part of
  the "status-set duplication (5 places)" noted in the refactor-audit memory.
- **Fix:** extract a private `_apply_favorite_toggle(channel_id) -> tuple[Channel, bool] | None`
  that owns the session/try-finally/repo/status-message, and have both public methods
  call it, then do their view-specific follow-up (details-pane refresh vs lightbox guard).
- **Accept:** both entry points behave identically to today; single source of the
  session+toggle logic; tests pass.

### P1-3 — Expand/collapse arrows hardcoded instead of `Config`
- **Where:** `metatv/gui/filter_panel.py:188`, `filter_panel.py:347`,
  `global_filter_dialog.py:233`, `global_filter_dialog.py:404` — all use literal
  `"▼"` / `"▶"`.
- **Rules violated:** *"Icons — always from Config"* AND *"Collapse/expand buttons —
  always `expand_icon` / `collapse_icon`."* `Config` already defines
  `expand_icon` (collapsed) and `collapse_icon` (expanded) at `config.py:515-516`.
- **Fix:** replace the literals — expanded → `config.collapse_icon`, collapsed →
  `config.expand_icon`. Make sure each widget has access to `self.config`.
- **Accept:** no arrow literals remain in those two files; toggling still flips the
  glyph; changing `Config.expand_icon` propagates.

### P1-4 — Hoist in-function `import` statements to module scope
- **Where:** ~8 in-function `import json` (e.g. `epg_manager.py:87`,
  `provider_loader.py:95`, `main_window.py:3770`) and ~55 function-local imports in
  `main_window.py`.
- **Why:** PEP 8 / readability; repeated re-import on hot paths; obscures real module
  dependencies. (`import json as _json` aliases also disappear once P1-1 centralizes the
  parsing.)
- **Fix:** move to the top-of-file import block unless the import exists solely to break a
  real circular dependency (leave those, add a one-line `# deferred: circular import`
  comment). Drop the `_json` alias where the helper from P1-1 now does the work.
- **Accept:** `grep -rnP "^\s+import (json|re|os)\b"` returns only genuinely-deferred,
  commented cases; tests pass.

---

### P1-5 — Per-call `ThreadPoolExecutor` for metadata fetch (thread leak)
- **Where:** `metatv/gui/main_window.py:2939` — inside the metadata-fetch path a fresh
  `executor = ThreadPoolExecutor(max_workers=1)` is created **on every channel selection**,
  used for one `submit`, and never `shutdown()`. Each call leaks a worker thread until GC.
- **Fix:** reuse the existing long-lived `self.executor` (created at `main_window.py:241`).
  Replace the local executor with `self.executor.submit(fetch_metadata)`; keep the
  `add_done_callback`. (The callback runs on the pool thread, so it already correctly
  marshals to the UI via `self.metadata_loaded.emit` — leave that intact.)
- **Accept:** no per-call executor remains; selecting many channels does not grow the thread
  count; metadata still loads.

### P1-6 — One shared Global-Exclusion predicate across all surfaces
- **Where:** three surfaces interpret the same `global_filter_excluded_categories` set differently:
  - `metatv/gui/main_window_channels.py` `_apply_python_exclusions` — **prefix-wins + region-fallback**
    (an un-excluded language prefix keeps the channel; region only decides when there is no prefix). *(current, correct rule — shipped #298)*
  - `metatv/gui/main_window_metadata.py` `_is_filtered` — **prefix-only**, no region at all (would show
    ~37k prefix-less region-excluded rows the channel list hides).
  - `metatv/gui/epg_on_now_mixin.py` `_on_now_hidden_prefixes` — builds its own hidden-prefix set.
- **Fix:** extract ONE predicate `is_channel_excluded(detected_prefix, detected_region, excluded)` (channel-list
  rule) into a dependency-free helper (e.g. `core/filter_utils.py`) and route all three surfaces through it, so
  search, Discovery/Recommendations, and EPG On-Now agree exactly (single-chokepoint; user's "everything should
  interpret the same way"). Detail: `docs/FILTERING_DESIGN.md` → Tier-2 "Open inconsistency".
- **Accept:** a search-hidden channel is hidden identically in Recommendations + EPG On-Now; one predicate, no
  parallel region/prefix logic. **Awaiting user go on the canonical rule (a behavior change to metadata/EPG).**

---

## Priority 2 — Inline stylesheets → `theme.py`

- **Rule violated:** *"Styles — use `theme.py`, never inline duplicates."*
- **Hotspots (count of `setStyleSheet(` calls):** `epg_view.py` 63, `provider_editor.py`
  36, `global_filter_dialog.py` 30, `similar_lightbox.py` 24, `filter_panel.py` 23,
  `sidebar_sections.py` 19, `details_sections.py` 17.
- **Scope guard:** only strings that are **shared across ≥2 widgets/files**, or are
  obvious repeated variants, must move to `theme.py` as named constants. A genuinely
  one-off style may stay inline — but most of these are repeated muted-label / border /
  small-font snippets (e.g. `"border: none; color: #777; font-size: 10px;"` at
  `epg_view.py:425`).
- **Fix approach (incremental, one file per commit, start with `epg_view.py`):**
  1. Grep the file's `setStyleSheet` strings; cluster identical/near-identical ones.
  2. For each cluster, add a named constant to `theme.py` (e.g. `MUTED_CLEAR_BTN`,
     `SECTION_HINT_LABEL`).
  3. Replace inline strings with `from metatv.gui import theme as _theme` references.
- **Accept:** per file, no duplicated stylesheet string remains; visual output unchanged.

---

## Priority 3 — Decompose oversized files (>1000-line standard)

**Rule:** *"Keep files under 1000 lines; one class per file."* Current violators:

| File | LOC | Suggested split |
|---|---|---|
| `gui/main_window.py` | 4178 | Extract mixins/controllers by concern: `main_window_favorites.py` (favorite/queue toggles — see P1-2), `main_window_streaming.py` (stream validation + URL failover, the `reconstruct_stream_url`/`validate_stream_url` cluster around 3700-3800), `main_window_nav.py` (chip/view switching, `_hide_all_content_views`). Keep `MainWindow` as the thin host wiring them together. |
| `gui/epg_view.py` | 2167 | Split the three tabs into their own widgets: `epg_watchlist_tab.py`, `epg_onnow_tab.py`, `epg_browse_tab.py`; `EpgView` becomes the tab-host. The browse query/date logic (P0-2) lands in the browse tab. |
| `gui/sidebar_sections.py` | 1403 | One section class per file under `gui/sidebar/` (queue, recs, alerts, favorites, history), keeping `CollapsibleSection` base in a shared module. |
| `gui/provider_editor.py` | 1120 | Extract the async connection-test/validation logic (`aiohttp` probe around 99-100) into a non-UI helper `core/provider_probe.py`; leave the form in the widget. |
| `gui/filter_panel.py` | 1061 | Extract the collapsible group-row widget and the summary-text logic into `gui/filter_group_row.py`. |

- **Order:** do the **mechanical, low-risk** extractions first (`sidebar_sections.py`,
  `filter_panel.py`), then `epg_view.py`, then `main_window.py` last (highest coupling).
- **Method:** move code verbatim, fix imports, run tests after each move. **Do not
  refactor logic during a file-split commit** — splitting and rewriting in the same commit
  makes regressions un-bisectable.
- **Accept:** each touched file under 1000 lines (main_window may need 2-3 passes); app
  launches; tests pass.

---

## Priority 4 — Lower-value cleanups (opportunistic)

- **P4-1 — Remaining status-set duplication.** The refactor-audit memory flags ~5 sites
  that build the engaged/favorite/queue sets. After P1-2, audit
  `preference_engine.py:284`, `discovery_engine.py:132-133`, `content_dedup.py:195`,
  `details_versions.py:282-283`, `details_similar.py:163-174` and centralize the
  "compute engaged-id sets" step into one helper if they truly overlap (verify first —
  some are legitimately different axes).
- **P4-2 — Stray artifact.** A 25 MB PostScript file literally named `--help` sits
  untracked in the repo root (ImageMagick misfire). Delete it: `rm -- ./--help`. Confirm
  it is not referenced anywhere before removing.

---

## Test & verification protocol (every task)

1. `venv/bin/python -m pytest tests/ -x -q` — all green.
2. For P0 tasks, add a regression test that fails before the fix and passes after.
3. Smoke-launch once after P3 file moves: `./run.sh` (or `venv/bin/python -m metatv`)
   and confirm the app starts and the affected view renders.
4. Follow the **Session Wrap SOP** in `CLAUDE.md` when finishing a batch (tests →
   commit → docs → memory → push).

---

## Tests to write (validate behavior going forward)

**Current state:** 65 tests in `tests/` across 3 files — all filter/prefix logic
(`test_channel_filters.py`, `test_extract_prefix.py`, `test_prefix_stats.py`).
`conftest.py` provides `db_session`, `repo`, and `make_channel(...)` fixtures.
`pytest-qt 4.5.0` **is installed**, so widget-level tests are viable. The core engines
and EPG layer have **zero** coverage today — that is the biggest risk for a refactor pass.

### Golden rule for refactor safety
For every **pure refactor** task (P1–P3), write a **characterization test first** that
pins the *current* behavior, confirm it passes on `main`, then refactor and confirm it
still passes. A refactor with no test guarding it is the most likely place to silently
break behavior. Order: test → see green → refactor → see green → commit both together.

### T0 — Regression tests for the P0 bug fixes (write these as part of P0)

- **T0-1 `test_provider_loader_session.py`** — guard the session-leak fix. Hard to assert a
  leak directly; instead assert the store path runs end-to-end and commits. Use a real
  in-memory DB (`db_session` fixture pattern), feed a minimal `series_data` dict, run the
  store, and assert seasons/episodes rows exist and the session is closed
  (`session.is_active is False` after, or patch `get_session` to a spy that records
  `close()` was called). Must pass after P0-1.
- **T0-2 `test_epg_browse_timezone.py`** — the important one. With a monkeypatched non-UTC
  local tz (e.g. UTC-7), insert an `EpgProgramDB` with UTC-naive `start_time` of
  `2026-06-01T02:00:00` (which is `2026-05-31 19:00` local). Assert `browse_*` for local
  date **2026-05-31** returns it and for **2026-06-01** does not. This test should FAIL on
  current `main` and PASS after P0-2. Also cover the time-slot ("Evening") boundary.

### P0-3 — `MainWindow.closeEvent` leaks threads (cleanup-rule violation)
- **Where:** `metatv/gui/main_window.py:4168-4178`. `closeEvent` calls
  `player_manager.cleanup()`, `stream_retry_manager.stop()`, `db.close()` — but **never**
  calls these background managers that own threads/timers:
  - `epg_manager.shutdown()` (`epg_manager.py:453` — stops the QTimer **and**
    `self._executor.shutdown()` for a 2-worker pool)
  - `image_cache.shutdown()` (`image_cache.py:290` — 4-worker pool)
  - `self.executor.shutdown()` (the MainWindow-owned 4-worker pool created at
    `main_window.py:241`)
- **Rule violated:** *"Resource cleanup in closeEvent — any background manager with a
  stop()/shutdown() method must be called explicitly… GC/parent destruction is not
  sufficient for threads."* On exit, these pools/timer keep running.
- **Fix:** add the three calls to `closeEvent` before `event.accept()`. Guard each with
  `hasattr`/`is not None` like the existing `stream_retry_manager` block.
- **Accept:** app exits cleanly; no lingering `epg`/`image`/executor threads; a test that
  spies `shutdown()`/`stop()` were each called on close.

### P0-4 — Views with `on_activate()` but no `on_deactivate()` (lifecycle-rule violation)
- **Where:** `discover_view.py`, `events_view.py`, `sports_view.py`, `preferences_view.py`
  each define `on_activate()` (start QThreads / submit executor work) but **no**
  `on_deactivate()`. (`epg_view`, `content_view`, `ppv_view` are symmetric — use them as
  the template.)
- **Rule violated:** *"View lifecycle — on_activate / on_deactivate must be symmetric."*
  Concrete failure: switch away from Discover mid-load and the running `QThread`
  (`discover_view.py:325`) is never `quit()`/`wait()`-ed; on app close this can raise
  *"QThread: Destroyed while thread is still running."* Executor-backed views
  (events/sports/preferences) keep fetching after the user has left the view.
- **Fix:** add `on_deactivate()` to each: quit+wait the QThread (or set a cancel flag the
  worker checks), stop any view timers, and have `main_window._hide_all_content_views()`
  call `on_deactivate()` on the departing view (per the CLAUDE.md "safest pattern").
- **Accept:** rapid view-switching during a Discover load produces no Qt thread warnings;
  leaving events/sports cancels in-flight fetches; tests assert the host calls
  `on_deactivate` on the outgoing view.

### T1 — Characterization tests before the P1 dedup refactors

- **T1-1 `test_provider_urls_parse.py`** — pin `parse_provider_urls()` semantics so all 6
  call sites can be swapped safely: JSON string input, already-a-list input, `None`,
  malformed JSON (→ `[]`), and list containing non-dict junk (filtered out). Write it
  against the new helper; assert each old call site now returns identical results to the
  pre-refactor inline code for the same inputs.
- **T1-2 `test_favorite_toggle.py`** — pin that both `toggle_favorite` and
  `toggle_favorite_by_id` flip `is_favorite`, persist it, and post the right status
  message. Run both paths against the `repo` fixture; assert DB state and returned/observed
  status text are identical. Guards the P1-2 extraction.
- **T1-3 (cheap, no DB) `test_expand_icons.py`** — assert `filter_panel` / `global_filter_dialog`
  collapse widgets render `Config.expand_icon` when collapsed and `Config.collapse_icon`
  when expanded (pytest-qt). Guards P1-3 and prevents regression to hardcoded glyphs.

### T2 — Core-engine coverage gaps (net-new value, independent of refactor)

These modules drive correctness and recommendations but have no tests. Prioritize by blast
radius:

- **`test_content_dedup.py`** — `normalize_title()` (leading-space strip, year-range
  `(2000-2005)`, bracket/paren qualifier stripping — the exact cases fixed in session 7,
  lock them in) and the `(norm_title, media_type, year, director)` fingerprint grouping,
  including the documented compromises: director excluded for series, null-year absorption.
- **`test_preference_engine.py`** — `score_candidates()` with the explicit/implicit
  `(explicit, implicit)` tuple ordering (explicit config must dominate); minimum-support
  threshold; recency decay; the language-preference fix (English version outranks
  Italian/Polish when both present).
- **`test_discovery_engine.py`** — shelf SQL builders (genre/decade/actor/director) return
  expected channels; `is_favorite` / `in_queue` flags set correctly from the id sets.
- **`test_epg_utils.py`** — `now_utc`, `fmt_time`, `remaining_str`, `minutes_away`,
  `progress_pct`, `fmt_duration` — pure functions, trivial to cover, high regression value.
- **`test_epg_repo.py`** — `current`, watchlist, browse, time-slot queries against seeded
  UTC-naive rows (overlaps T0-2; share fixtures).
- **`test_channel_name_utils.py`** — `normalize_region_code`, `REGION_FULL_NAMES`, quality
  token parsing — the canonical lookup tables the rules forbid duplicating.
- **`test_special_content.py`** — PPV/Events/Sports detection + classification keywords.

### T3 — Widget/integration tests (pytest-qt, fill the session-7 gaps)

- **`test_filter_panel.py`** — `get_filter_state()` after programmatic toggles; expand/collapse
  state persistence; **row-click toggles the checkbox** (session-7 feature, untested);
  **right-click context menu** ("Check only 'X'", "Exclude 'X' globally…") writes
  `global_filter_excluded_prefixes`.
- **`test_genre_normalization.py`** — multilingual genre map (Drama/Drame/Dramma → Drama,
  Komödie/Comédie → Comedy); non-Latin scripts dropped (RTL width guard).
- **View lifecycle** — for any view with `on_activate`/`on_deactivate`, assert they're
  symmetric (timers started are stopped) per the CLAUDE.md rule; a small parametrized test
  over the view classes catches future asymmetric additions.

### Test infrastructure to add alongside

- A `seed_epg(session, ...)` fixture in `conftest.py` for the EPG tests (UTC-naive rows).
- A `frozen_local_tz` fixture/monkeypatch helper so timezone tests are deterministic on any
  machine — reused by T0-2, T2 EPG tests.
- Keep all new tests offline/deterministic: no real network, no real provider, no mpv.
  Mock `aiohttp` and the Xtream client; use the in-memory SQLite from `conftest.py`.

### Definition of done for the test work
- `venv/bin/python -m pytest tests/ -q` stays green.
- T0-2 demonstrably fails before P0-2 and passes after (attach the before/after in the
  commit message).
- Update the **[filter test suite memory]** count and the FILTERING_DESIGN / ROADMAP
  test-coverage sections when the suite grows (per Session Wrap SOP step 1).

---

## Appendix — Are the CLAUDE.md "Critical Rules" themselves best practices?

> **Status (2026-06-01):** the *wording* changes from this review are already applied to
> CLAUDE.md — DB-sessions and SQLite-JSON rules reworded (no longer ban the better
> solution); Styles rule softened to target duplication; Collapse/expand rule merged into
> Icons; Icons + EPG-times rules carry `<!-- target -->` notes pointing here; two new rules
> added ("Background pools/threads — owned, long-lived, and shut down" and "No unbounded DB
> work on the UI thread"). What remains below is the *code/structural* work those targets
> describe — still TODO.

Reviewed each documented rule on its own merits. Verdicts: **Sound** (keep as-is),
**Band-aid** (the rule reliably prevents a bug, but it does so by mandating discipline at
every call site instead of removing the root cause — a deeper structural fix would make the
rule unnecessary), **Reconsider** (the rule may push code toward a mild anti-pattern).

Most rules are genuinely good. The five "Band-aid"/"Reconsider" items below share one
theme — *they enforce repeated manual discipline where a single shared mechanism would be
safer.* These are the highest-leverage structural improvements in this whole plan, because
each one **eliminates an entire recurring bug class** rather than fixing one instance. Treat
them as optional-but-recommended P1.5 work, each behind its own design discussion.

| CLAUDE.md rule | Verdict | Note |
|---|---|---|
| EPG time utils from `epg_utils.py` | **Sound** | Textbook DRY / single source. |
| Collapse/expand icon convention | **Sound** | Consistency convention; cheap to honor. |
| Styles in `theme.py`, *never* inline | **Sound** (soften wording) | DRY is right; "never inline" is too absolute — a genuinely one-off style is fine inline. Reword to "no **duplicated** stylesheet string." |
| Lookup tables single-source | **Sound** | Correct. |
| **Icons always on `Config`** | **Reconsider** | Overloads a *settings/persistence* model (Pydantic `Config`) with dozens of presentation constants — two concerns in one object, and every new glyph bloats the user config schema. Better: a dedicated `metatv/gui/icons.py` (or `theme.ICONS`) constants module; reserve `Config` for things the user actually configures. Keeps the "no hardcoded literals" benefit without conflating config with theming. |
| Logging = loguru only | **Sound** | Fine project-wide consistency choice. |
| **DB sessions: try/finally, never `with`** | **Band-aid** | The rule prevents a real leak, but enshrines try/finally boilerplate at ~every query site (and spawns the sibling rule "early returns must clean up"). Root-cause fix: one `@contextmanager session_scope()` helper that does `try → yield → commit → except: rollback → finally: close`. Call sites become `with session_scope() as s:` — shorter, leak-proof, and the "early-return cleanup" rule becomes moot for sessions. This is the single biggest readability win available. |
| **SQLite JSON: manual `json.dumps/loads` every assignment** | **Band-aid** | The rule itself documents a recurring bug (forgetting the write-back `dumps`). That bug class only exists *because* serialization is manual. Root-cause fix: a SQLAlchemy `TypeDecorator` (`JSONEncoded`) that does dumps/loads in `process_bind_param`/`process_result_value` once; columns become `Column(JSONEncoded)` and you assign/read plain Python objects. Eliminates the entire "stored a Python list instead of JSON string" footgun (incl. the P1-1 provider-urls churn). |
| Qt threading via signals | **Sound** | Correct and non-negotiable. |
| QPixmap on main thread | **Sound** | Correct Qt constraint. |
| Signal-block during restore | **Sound** | Standard Qt idiom. |
| EPG notifications not from workers | **Sound** | Correct; already implemented via private signals. |
| **EPG times stored UTC-naive** | **Reconsider (root cause)** | This single decision spawns *three* defensive rules (display-convert, "never `.date()==today()`", arithmetic-in-UTC) and is the direct cause of bug **P0-2**. Storing tz-aware UTC datetimes (or documenting a single conversion boundary at the parser/repo edge) would remove the footgun class. At minimum, centralize *all* conversions in `epg_utils.py` so no view ever touches a raw `start_time`. Heavier lift (touches the schema/parser) — scope as its own task, not a drive-by. |
| EPG one-worker fetch (SQLite lock) | **Sound** (note) | Correct given current setup. Worth a footnote: enabling SQLite **WAL mode** would relax write-concurrency pain app-wide and is independently worth doing. |
| Early returns clean up acquired state | **Sound** | Good defensive rule — but see the `session_scope()` note: context managers make most instances of it automatic. |
| View `on_activate`/`on_deactivate` symmetric | **Sound** | Good rule; currently **violated** in 4 views (task P0-4). |
| Resource cleanup in `closeEvent` | **Sound** (fragile) | Right intent, but manual per-manager registration is fragile and is **already violated** (task P0-3). Sturdier: a small `self._cleanables: list` that managers register into, iterated in `closeEvent` — new managers can't be forgotten. |
| UI state persistence everywhere | **Sound** | Good product rule. |

**Recommended structural tasks distilled from the above (each its own design + commit):**
1. `session_scope()` contextmanager → migrate query sites off raw try/finally. (Supersedes the "never `with session`" rule with a *better* `with`.)
2. `JSONEncoded` `TypeDecorator` → retire manual `json.dumps/loads` discipline.
3. `metatv/gui/icons.py` constants module → move glyphs off the `Config` settings model.
4. EPG tz-aware storage (or single conversion boundary) → dissolve the cluster of EPG-time rules; fixes P0-2 at the root.
5. `closeEvent` cleanup registry → make P0-3-style omissions structurally impossible.
6. (Independent) Enable SQLite **WAL mode** to ease the one-writer constraint.

Do **not** silently rewrite these — each changes a documented convention. Propose the change,
update CLAUDE.md's rule text in the *same* commit, and keep the old rule's intent intact.
