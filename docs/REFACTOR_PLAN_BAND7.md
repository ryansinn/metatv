# MetaTV — Band 7 Refactor Plan (Responsiveness Seam + Finish Decomposition)

**Audience:** an implementing agent (Sonnet).
**Source:** senior review of **PR #7** (Band 6 — merged as squash `2e7ef5b`, 2026-06-05) + the
owner's directive to fix UI latency *architecturally* (not per-query band-aids) while finishing
the file decomposition Band 6 left incomplete.
**Prereqs landed:** Bands 1–6 merged. PR #7 shipped the Band 6 refactors (B6-1/3/4/7/8/9/10) plus
a large amount of feature work; `main` is at `2e7ef5b`, 291 tests green.

**Goal:** make the app stop hanging on large DB operations and view switches by building **one
reusable async-read seam** that future features plug into, and finish the `>1000`-line
decomposition (`main_window.py`, `epg_view.py`, `channel.py`). No user-visible behavior change
except work moving off the UI thread (B7-3…B7-6) — which is the point.

---

## Why this band exists (review findings from PR #7)

**Good in PR #7 (do not undo):** B6-7 off-thread streaming is textbook Qt threading
(primitives-only signal payload, all widget work on the main-thread slot, `loading_channels`
guard preserved); session_scope per-attempt-commit reasoning documented inline; the three new
mixins own no `__init__`, clean MRO, no duplicated methods, no hex/rgba/icon/stdlib-logging
violations; 28 new behavior-pinning tests. The 2026-06-05 prefix patches put all new lookup data
in the canonical `channel_name_utils.py` (lookup-table rule) with tests.

**Gaps / debt this band addresses:**
1. **Decomposition unfinished:** `main_window.py` = 2457, `epg_view.py` = 2157, `channel.py` = 1069
   — all over the 1000-line rule.
2. **Responsiveness applied inconsistently.** `load_channels` (240k rows) is already correct
   (read UI state on main thread → `self.executor.submit` → signal → render). But these are still
   **synchronous DB on the UI thread:** `switch_to_epg_view` → `get_total_programmes()` (COUNT);
   `populate_series_tree` (nested seasons×episodes + tree build); sidebar `refresh()`
   (favorites/history/queue/recommended) — fires after every play + every view switch (28 call
   sites); 32 `get_session()` context-menu handlers in the favorites/metadata mixins.
3. Dead `source_id`/`media_type` params in the streaming failover path.
4. Duplicated bracket-classification ladder in `channel_name_utils.parse_channel_name` (step 6a is
   a near-copy of step 3, already diverging) + language/region namespace overloading in
   `_BRACKET_LANG_NORM` (semantic debt, do not re-map this band).
5. Exclusions-chip dead-zone (known bug).

---

## Ground rules for the implementer

1. **Follow `CLAUDE.md` Critical Rules.** This band leans hardest on: *No unbounded / blocking DB
   work on the UI thread*, *Qt threading — signals only*, *Background pools owned & long-lived
   (reuse `self.executor`, never a per-call pool)*, *`session_scope()` for new code*, *View
   lifecycle on_activate/on_deactivate symmetric*.
2. **One concern per PR.** Owner directive after PR #7 bundled 34 mixed commits. Pure refactors are
   **verbatim moves**, kept separate from behavior changes and from net-new features. See the PR
   grouping below — do not collapse it.
3. **Run the suite after every task:** `venv/bin/python -m pytest tests/ -x -q`. All green.
4. **No behavior change unless the task says so.** B7-7/B7-8/B7-9/B7-12 are pure refactors (same
   runtime behavior, verified by tests). B7-3/B7-4/B7-5/B7-6 are intentional behavior changes (work
   moving off-thread) — pin each with a test before/after.
5. **For file-split commits: move code verbatim, fix imports, run tests. Never split and rewrite
   logic in the same commit** (Band 5's bar: `main_window.py`'s entire diff was 2 lines). After a
   split, grep to prove no method is defined twice.
6. **Smoke-launch after any GUI split** (B7-7, B7-8) — `./run.sh`; confirm the affected view
   renders and live-updates. Headless tests cannot catch a broken Qt layout. If you cannot launch a
   display, say so and mark smoke-test as owner-to-verify in the PR body.

---

## Status snapshot (verify before starting — code may have drifted)

| Item | State at plan time |
|---|---|
| `main_window.py` | **2457 lines** — over. B6-1 did passes 2–4 (nav/metadata/favorites mixins). → **B7-7** (pass 5) |
| `epg_view.py` | **2157 lines** — over; B6-2 deferred. → **B7-8** |
| `channel.py` (repo) | **1069 lines** — over, newly in scope. → **B7-9** |
| `load_channels` | **Already off-thread** — this is the seam template for B7-1. Do not "fix" it. |
| `_StreamingMixin` (B6-7) | Off-thread + session_scope **done**. Only debt: dead `source_id`/`media_type` params → **B7-10** |
| `_PREFIX_PARSE_VERSION` | At **4**; each prefix-definition change bumps it → full 240k rescan (already off-thread via `_bg_prefix_migration`). Leave as-is. |

---

## Priority A — The async-read seam (foundation)

### B7-1 — Async-read seam (keystone)
Extract the proven `load_channels` pattern (`main_window.py:~1218` +
`_bg_load_channels:~1359`) into a single reusable primitive — e.g. a small `_AsyncMixin` (or a
`gui/async_query.py` helper) with:

```python
def _run_query(self, query_fn, on_result, *, token=None):
    """Run query_fn(session) in self.executor; deliver its plain-data result to
    on_result on the main thread. If token is given and a newer token has been
    issued by the time the result lands, drop it (stale-result guard)."""
```

- Runs `query_fn(session)` in **`self.executor`** (the long-lived MainWindow pool — never a new
  pool). `query_fn` opens its own `session_scope()` and returns **plain data only** (see B7-2).
- Marshals the result back via **one** generic `pyqtSignal(object)` on `MainWindow`; the slot
  invokes `on_result(result)` on the main thread.
- Carries `load_channels`' **stale-token drop** so fast view-switching discards superseded
  results (mirror the existing token/counter in `_bg_load_channels`).
- **New code + tests; do NOT rewrite `load_channels` in this PR** — prove the seam standalone
  first. (`load_channels` can adopt it in a later, separate pass if desired.)
- **Test:** the submitted query runs off the main thread; result is delivered to `on_result`; a
  superseded token is dropped.
- **Wrap step (this PR only):** add the new CLAUDE.md Critical Rule documenting `_run_query` as
  the required pattern for new DB reads — now that the primitive actually exists.

### B7-2 — Repository reads return plain DTOs
ORM objects can't cross the thread boundary safely (lazy-load on a closed session). For each hot
path, add/confirm a repository method that returns **detached** dataclasses/dicts:
- series seasons + episodes (for `populate_series_tree`),
- sidebar favorites / history / queue / recommended rows.
- (`get_total_programmes` already returns `int` — fine, no DTO needed.)
- **Method:** define small `@dataclass(frozen=True)` DTOs in the repository module (or a
  `core/dtos.py`); the repository maps ORM → DTO inside the `session_scope()` before returning.
- **Test:** each method returns plain data with no live session attached (assert attribute access
  works after the session is closed).

---

## Priority B — Convert the hot blocking paths (behavior changes, one PR each)

### B7-3 — EPG view-switch count off-thread
`switch_to_epg_view` (`main_window_nav.py:~94`) calls `epg_manager.get_total_programmes()`
synchronously (COUNT over the large EPG table). Show `"EPG — counting…"` immediately, then update
`stats_label` via the seam.
- **Accept:** opening the EPG view never blocks; the count still appears; tests pin the deferred
  update.

### B7-5 — Sidebar refresh off-thread
favorites / history / queue / recommended `refresh()` (delegated from `load_favorites` /
`load_history` / `_refresh_queue_section` / `_refresh_recommended_section`, in
`main_window_favorites.py` and `gui/sidebar/*`) do synchronous DB + widget population on the UI
thread, and fire after **every** playback and **every** view switch (28 call sites). Highest
perceived win.
- **Method:** each section's `refresh()` loads its rows via the seam (DTOs from B7-2), then
  populates widgets in the main-thread `on_result`. Keep the section's existing public API.
- **Accept:** post-playback and view-switch no longer stutter; lists still populate correctly;
  tests pin the off-thread load + render.

### B7-6 — Context-menu lookups off-thread / lightweight
The 32 `get_session()` handlers in `main_window_favorites.py` (24) and `main_window_metadata.py`
(8) run on the UI thread (context menus, hide/unhide, etc.).
- **Method:** convert the **heavy** ones (anything that scans/filters/joins, grows with library
  size) to the seam; migrate **all touched** sites to `session_scope()`. Trivial primary-key
  lookups may stay inline — **document which and why** in the commit.
- **Accept:** no library-sized query on the UI thread in these handlers; tests green.

---

## Priority C — Finish decomposition (verbatim moves, one PR each) + paired async

### B7-7 — `main_window.py` pass 5 (2457 → < 1000)
Continue the mixin-by-concern pattern from B6-1.
- **Extractions** (verify boundaries with `grep -n "def "` first):
  - `main_window_channels.py` — `_ChannelLoadMixin` (~500 lines): `load_channels`,
    `_bg_load_channels`, `on_channels_loaded` and their filter-resolution helpers.
  - `main_window_series.py` — `_SeriesMixin` (~500 lines): series/episode handling,
    `populate_series_tree`, `show_series_context_menu`.
- **Method:** verbatim moves; mixins define NO `__init__`; add ahead of `QMainWindow` in the MRO
  (`class MainWindow(_StreamingMixin, _NavMixin, _MetadataMixin, _FavoritesMixin, _ChannelLoadMixin,
  _SeriesMixin, QMainWindow)`); cross-mixin helpers imported at module scope. Grep to prove no
  method defined twice.
- **Accept:** `main_window.py` < 1000; no method shadowed; app launches; tests pass. Note any
  residual if a 6th pass is needed.

### B7-4 — Series tree off-thread *(separate PR from B7-7)*
`populate_series_tree` loads seasons/episodes synchronously. Convert it to the seam + B7-2 DTOs,
landing on the new `_SeriesMixin`. **Refactor ≠ behavior change → its own PR after B7-7.**
- **Accept:** opening a series never blocks; the tree still builds identically; test pins the
  off-thread load.

### B7-8 — `epg_view.py` tab split (was B6-2) (2157 → tab widgets, < 1000 each)
Highest-coupling split; its own PR with GUI smoke-testing.
- **Split the three tabs:** `epg_watchlist_tab.py`, `epg_onnow_tab.py`, `epg_browse_tab.py`.
  `EpgView` becomes the tab-host owning shared state.
- **Cross-tab state is the hazard** (90+ methods, shared timers, the EPG refresh signal, the
  date-combo). Map shared state FIRST; anything two tabs read stays on `EpgView` and is passed in,
  never duplicated.
- **Lifecycle:** preserve `on_activate`/`on_deactivate` symmetry — host forwards deactivate to the
  departing tab, activate to the arriving one; EPG timers stop on deactivate (single-worker /
  no-leak rules).
- **Method:** verbatim moves only. **Smoke-launch all three tabs** (Watchlist / On Now / Browse
  render + refresh). Land after B7-3 so the split lands on already-responsive EPG.
- **Accept:** each file < 1000; all three tabs render and live-update; no duplicate EPG timers;
  tests pass.

### B7-9 — `channel.py` repo split (1069 → < 1000)
Split the channel repository by concern — e.g. query-builder/filter assembly vs CRUD vs search —
into a small package (`core/repositories/channel/` with a back-compat re-export) or sibling
modules. Verbatim move; fix imports; tests green.
- **Accept:** `channel.py` (or the package's entry module) < 1000; no method defined twice;
  importers unchanged or updated; tests pass.

---

## Priority D — Cleanups (one PR)

### B7-10 — Remove dead params
Drop the unused `source_id` and `media_type` parameters from
`_StreamingMixin.validate_and_failover_stream_url` and `_bg_validate_and_play`
(`main_window_streaming.py`) and their call sites in `play_media`.
- **Accept:** params gone; failover behavior unchanged; tests green.

### B7-11 — Exclusions-chip dead-zone
Text area of the Exclusions chip is not clickable at cold launch; becomes clickable after a
notification appears/dismisses. `setCheckable(False)` and solid-fill hover did NOT fix it.
- **Investigate** the z-order/geometry-timing root cause in the bottom nav bar init +
  `notification_widget.py` show/hide side-effects. Fix, or document the root cause if a fix isn't
  safe this band.
- **Accept:** chip clickable at cold launch, OR a written root-cause note + the discarded
  attempts.

### B7-12 — DRY the bracket-classification ladder (`channel_name_utils.py`)
Step 6a (`bsm2`) in `parse_channel_name` is a near-copy of step 3's alias→quality→lang→platform
if/elif chain, and already diverges (6a omits the content-origin + audio branches and sets `lang`
directly because step 4 ran).
- **Method:** extract one `_classify_bracket(content) -> (kind, value)` helper and call it from
  both sites; behavior-preserving. The existing `test_compound_prefix.py` cases are the
  characterization test — they must stay green.
- **Also:** leave a one-line comment documenting the language/region namespace overloading in
  `_BRACKET_LANG_NORM` (`KOREAN→KR`, `JAPANESE→JP`, `CHINESE→CN` are *region* codes, not ISO-639-1
  language codes) as known semantic debt tracked under the filter system. **Do NOT re-map it** —
  it's entangled with the compound-locale work.
- **Accept:** one bracket-classification path; `test_compound_prefix.py` green; debt note present.

---

## Suggested band ordering & PR grouping (one concern per PR)

```
PR A — B7-1 + B7-2   (async-read seam + repository DTOs)        ← foundation, new code + tests
PR B — B7-3          (EPG count off-thread)                     ← behavior
PR C — B7-5          (sidebar refresh off-thread)               ← behavior, biggest perceived win
PR D — B7-6          (context-menu lookups off-thread)          ← behavior + session_scope
PR E — B7-7          (main_window pass 5 → <1000)               ← VERBATIM MOVE
PR F — B7-4          (series tree off-thread, on new mixin)     ← behavior, depends on PR E
PR G — B7-8          (epg_view tab split → <1000)               ← VERBATIM MOVE, own session + smoke
PR H — B7-9          (channel.py repo split → <1000)            ← VERBATIM MOVE
PR I — B7-10 + B7-11 + B7-12  (cleanups)                        ← small
```
Rationale: foundation first (A) so every conversion shares one seam; highest-impact conversions
(B, C, D) before the big splits; splits (E, G, H) are verbatim moves landing on a clean tree; F
depends on E. **Never mix a refactor with a behavior change or a feature in one PR.**

---

## Verification protocol (every task)

1. `venv/bin/python -m pytest tests/ -x -q` — all green.
2. For B7-3/B7-4/B7-5/B7-6, add the regression test described and put before/after in the commit
   message.
3. Smoke-launch after any GUI split (B7-7, B7-8) via `./run.sh`; confirm the affected view renders
   and live-updates. If headless, mark owner-to-verify in the PR body.
4. After a split, grep to prove no method is defined twice.
5. Follow the **Session Wrap SOP** in `CLAUDE.md` when finishing the band: tests → commit → docs
   (tick Band 7 in `ROADMAP.md` Code Health) → memory (`project_session_handoff.md`) → push.

---

## Definition of done for Band 7

- `main_window.py`, `epg_view.py`, `channel.py` all **< 1000 lines**; no method defined twice
  after any split.
- **No synchronous DB read on the UI thread** in: EPG view switch, series tree, sidebar refresh,
  hot context menus (verify by audit/grep — those handlers go through the seam).
- One reusable async-read seam exists, is unit-tested (off-thread dispatch + stale-token drop), and
  is documented in `CLAUDE.md` as the required pattern for new DB reads.
- Repository hot-path reads return plain DTOs (no session-bound ORM objects crossing threads).
- Dead `source_id`/`media_type` params removed; Exclusions-chip dead-zone fixed or root-caused;
  one bracket-classification path in `channel_name_utils.py`.
- All prior behavior preserved (tests green + smoke-launch); the only intentional change is work
  moving off the UI thread.
