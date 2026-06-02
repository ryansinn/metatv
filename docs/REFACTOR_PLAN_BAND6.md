# MetaTV — Band 6 Refactor Plan (P3 remainder + P4 + PR #6 review follow-ups)

**Audience:** an implementing agent (Sonnet).
**Source:** carryover from [REFACTOR_PLAN.md](REFACTOR_PLAN.md) (P3/P4 leftovers) + senior
review of **PR #6** (Band 5 file decomposition), 2026-06-01.
**Prereqs landed:** Bands 1–5 merged/open (P0 bugs, P1 dedup, structural fixes, P2 styles,
P3 splits pass 1). The PR #6 review's items #1–#4 are **already fixed** on
`refactor/band5-splits` (structured `ProbeResult`, DRY `probe_all_urls`, hoisted probe
imports, `url_row_widget` tokens). This plan is everything that was **explicitly deferred**.

**Goal:** finish the file decomposition, retire the last duplication, and clear the
review's deferred items — without changing user-visible behavior except where a task says so
(only B6-7 changes runtime behavior, and only to remove UI-thread blocking).

---

## Ground rules for the implementer

1. **Follow `CLAUDE.md` Critical Rules.** Several tasks exist *because* a rule is currently
   violated. Do not introduce new violations while fixing old ones. Pay special attention to:
   *Icons from `icons.py`*, *Styles two-layer `theme.py`*, *`session_scope()` for new code*,
   *No unbounded DB / blocking work on the UI thread*, *Qt threading — signals only*.
2. **Small commits, one task per commit**, on a feature branch (NOT `main`). One PR for the
   band is fine; split B6-1/B6-2 into their own PRs if they get large.
3. **Run the suite after every task:** `venv/bin/python -m pytest tests/ -x -q`. All green.
4. **No behavior change unless the task says so.** B6-1/B6-2/B6-5/B6-6/B6-8/B6-9 are pure
   refactors — same runtime behavior, verified by tests. B6-7 is the one intentional
   behavior change (off-thread validation); pin it with a test.
5. **For file-split commits: move code verbatim, fix imports, run tests. Never split and
   rewrite logic in the same commit** — it makes regressions un-bisectable. This is the rule
   that kept Band 5 clean (`main_window.py`'s entire diff was 2 lines).
6. **Smoke-launch after any GUI split:** `./run.sh` and confirm the affected view renders.
   Headless tests cannot catch a broken Qt layout.

---

## Status snapshot (verify before starting — code may have drifted)

| Item | State at plan time |
|---|---|
| `provider_editor.py` | **978 lines — under 1000, no longer a violator.** Do not re-split. |
| `main_window.py` | 3835 lines — still over (Band 5 was pass 1 of 2–3). → **B6-1** |
| `epg_view.py` | 2157 lines — split deferred from Band 5. → **B6-2** |
| Stray `--help` artifact | **Absent** — already gone; P4-2 is moot, just confirm. |
| `probe_all_urls` dead code / probe English in core / `url_row_widget` literals | **Fixed** in the PR #6 follow-up commit. Do not redo. |

---

## Priority A — Finish file decomposition (P3 remainder)

### B6-1 — `main_window.py` (3835 → < 1000), passes 2–3
Band 5 extracted `_StreamingMixin` into `main_window_streaming.py`. Continue the same
mixin-by-concern pattern, `MainWindow` staying the thin host.

- **Suggested extractions** (verify cluster boundaries with `grep -n "def "` first):
  - `main_window_favorites.py` — favorite/queue/history toggles and their list reloads
    (`_apply_favorite_toggle`, `load_favorites`, `load_history`, `_refresh_queue_section`,
    queue add/remove). These already form a cohesive group.
  - `main_window_nav.py` — chip/view switching, `_hide_all_content_views`,
    `on_activate`/`on_deactivate` orchestration, the view-registry wiring.
  - `main_window_metadata.py` — the metadata-fetch executor path (already a self-contained
    concern after the P1-5 fix).
- **Method:** each mixin is `class _XxxMixin:` with methods that access `self.*` state set
  in `MainWindow.__init__`. Add to the MRO ahead of `QMainWindow`:
  `class MainWindow(_StreamingMixin, _FavoritesMixin, _NavMixin, QMainWindow):`. Mixins
  must NOT define `__init__` (state stays owned by `MainWindow`).
- **Watch:** a method moved into a mixin must not also remain in `main_window.py` (grep to
  confirm no shadowing — Band 5's clean result is the bar). Private cross-mixin helpers
  imported at module scope, not inside methods.
- **Accept:** `main_window.py` under 1000 (or as close as the host wiring allows; note the
  residual if a 4th pass is needed); no method defined twice; app launches; 139+ tests pass.

### B6-2 — `epg_view.py` (2157 → tab widgets)
The highest-coupling split; Band 5 explicitly deferred it for a dedicated session with GUI
smoke-testing. **Do this as its own PR.**

- **Split the three tabs into their own widgets:** `epg_watchlist_tab.py`,
  `epg_onnow_tab.py`, `epg_browse_tab.py`. `EpgView` becomes the tab-host that owns shared
  state and wires `on_activate`/`on_deactivate` to the active tab.
- **Cross-tab state is the hazard** — there are 90+ methods with shared timers, the EPG
  refresh signal, and the date-combo state. Map the shared state first; anything two tabs
  read stays on `EpgView` and is passed in, not duplicated.
- **Lifecycle:** preserve the `on_activate`/`on_deactivate` symmetry rule — the host must
  forward deactivate to the departing tab and activate to the arriving one. EPG timers must
  stop on deactivate (per the EPG single-worker / no-leak rules).
- **Method:** verbatim moves only, per Ground Rule 5. Smoke-launch each of the three tabs
  after the split (Watchlist / On Now / Browse all render and refresh).
- **Accept:** each file under 1000; all three tabs render and live-update; no duplicate EPG
  timers; tests pass.

---

## Priority B — Retire last duplication (P4)

### B6-3 — Status-set duplication (P4-1)
Audit the ~5 sites that build engaged/favorite/queue id-sets and centralize the
"compute engaged-id sets" step **only if they truly compute the same thing** — verify each,
since some are legitimately different axes (favorites vs. queue vs. watched).
- **Sites:** `preference_engine.py:~284`, `discovery_engine.py:~132`,
  `content_dedup.py:~195`, `details_versions.py:~282`, `details_similar.py:~163`.
- **Method:** write a characterization test that pins each call site's current set contents
  first; extract a shared helper (likely on a repository or a small `core` function); prove
  identical output. If two sites differ, leave them and document why in the commit.
- **Accept:** one helper, no behavior change, tests green. If they don't overlap, the task
  output is a one-paragraph note saying so — that's a valid result, not a failure.

### B6-4 — Stray artifact (P4-2) — confirm only
The 25 MB `--help` PostScript file is already absent. Confirm with `ls -- ./--help` and
close the item; no action needed unless it reappears.

---

## Priority C — PR #6 review follow-ups (deferred items #5–#6 + adjacent)

### B6-5 — Icons rule: `url_row_widget` glyphs + `ICON_PALETTE` placement
Eight icon-glyph literals remain as `config.X_icon if config else "▲"`-style fallbacks
(`url_row_widget.py:37,38,81,90,97,98,116,117`), and `ICON_PALETTE` (a list of emoji) lives
in a *widget* file (`url_row_widget.py:127`) only because `provider_editor` imports it.
- **Rule violated:** *"Icons — always from `metatv/gui/icons.py`, never hardcoded."* Glyphs
  are presentation constants, not user config; per the rule, the canonical home is `icons.py`.
- **Fix:**
  - Add the needed glyphs to `icons.py` (move-up/down, close, loading, success, error) if
    absent, and replace the `else "▲"` fallbacks with `icons.*` (drop the `config.X_icon`
    legacy path here, or keep config as the override and `icons.*` as the fallback —
    match how Band 4 handled the migration).
  - Move `ICON_PALETTE` + `pick_next_icon` out of the widget file. `ICON_PALETTE` is a data
    constant → `icons.py` (e.g. `icons.PROVIDER_ICON_PALETTE`); `pick_next_icon` can sit
    beside it or in a small `gui/icon_palette.py`. Update both importers
    (`url_row_widget`, `provider_editor:182`).
- **Accept:** no icon glyph literals in `url_row_widget.py`; `ICON_PALETTE` not defined in a
  widget module; both importers updated; tests pass.

### B6-6 — theme tokens: `ProviderIconPicker` + `filter_group_row._ACCENT`
~24 hex/rgba literals remain in `provider_editor.py` (mostly `ProviderIconPicker._BTN_STYLE`
/ `_BTN_SELECTED_STYLE`, `#4488ff` + `rgba(68,136,255,...)`) and ~20 in
`filter_group_row.py` (the `_ACCENT` per-section colour map).
- **Rule violated:** *"Styles — two-layer `theme.py`; tokens for all palette values."*
- **Fix:**
  - `ProviderIconPicker`'s blue selection styles → tokens. `#4488ff` is a recurring accent;
    add `COLOR_ACCENT_BLUE` (or reuse `COLOR_ACCENT` if visually identical — verify the hex)
    and the rgba tints as `OVERLAY_*`/dedicated tokens, then compose role-named constants
    (`ICON_PICK_BTN`, `ICON_PICK_BTN_SELECTED`).
  - `filter_group_row._ACCENT` is a **data map** of per-section accent colours. Keep it a
    map, but its *values* must be theme tokens, not raw hex
    (`{"media": _theme.COLOR_ACCENT_BLUE, "region": _theme.COLOR_ACCENT_GREEN, ...}`). Add
    the missing accent tokens to `theme.py` (green/purple/orange/teal/brown). Preserve exact
    hex values — this is appearance-preserving; do not "harmonize" colours.
- **Accept:** no raw hex/rgba in either file; new tokens are appearance-based names in the
  token layer; byte-equality of the resulting colours preserved (spot-check the hex).

### B6-7 — Move stream validation off the UI thread *(intentional behavior change)*
`main_window_streaming.play_media` → `validate_and_failover_stream_url` → `requests.get`
(`stream=True, timeout=(5,5)`) runs **on the main thread**, and failover loops that blocking
GET across every alternate URL. On a dead channel with several alternates the window can
freeze 15–30 s.
- **Rule violated (spirit):** *"No unbounded blocking work on the UI thread"* + *"Qt
  threading — signals only."*
- **Fix:** run validation/failover in `self.executor` (the long-lived MainWindow executor —
  do **not** spawn a new pool) and marshal the result back via a `pyqtSignal` to a
  main-thread slot that launches the player / shows the error toast. The `loading_channels`
  guard already prevents double-launch; keep it. Notifications must be created on the main
  thread (per the EPG/NotificationManager rule) — emit, then show in the slot.
- **Test:** characterization test for the failover ordering/stat-update logic (mock
  `validate_stream_url`), plus a test that `play_media` returns immediately and the player
  launch happens from the signal slot. Pin behavior before moving threads.
- **Accept:** UI does not block during validation; failover order + success/failure stat
  updates unchanged; player still launches; error toast still shows server message.

### B6-8 — `session_scope()` in `main_window_streaming`
`validate_and_failover_stream_url` and `play_media` use the legacy
`get_session()/try/finally` pattern (acceptable per CLAUDE, but flagged for migration).
- **Fix:** convert to `with self.db.session_scope() as session:`. Note `mark_played`
  self-commits (`channel.py:377`); the failover stat writes currently call
  `session.commit()` explicitly inside the loop — under `session_scope` the final commit is
  automatic, but **keep the per-attempt commits** if a later attempt's failure must not roll
  back an earlier success's stat write (verify the intended durability; document the choice).
- **Accept:** no `get_session()` in the file; stat writes persist correctly; tests pass.
- **Coordinate with B6-7** — if both land, do B6-7 first (it restructures the method), then
  B6-8 on the new structure, to avoid rebasing the same code twice.

### B6-9 — Hoist remaining in-function imports
Per the established convention (commit `943fc81`):
- `provider_editor.py:74` — `from metatv.providers.factory import get_provider` (account
  -info path). Hoist to module scope unless it creates a circular import (test the import).
- `main_window_streaming.py` — `_DEFAULT_HEADERS` (line ~55), `QApplication` (~249),
  `channel_name_utils.parse_channel_name` (~254) are imported inside methods. Hoist the ones
  that don't risk a circular import; leave (with a one-line comment) any that genuinely do.
- **Accept:** no avoidable in-function imports; any remaining lazy import has a comment
  stating the circular-import reason; tests pass.

### B6-10 — Test coverage for the now-testable core
Band 5 made `core/provider_probe.py` Qt-free — it is now unit-testable without a
`QApplication`, and the structured `ProbeResult` makes assertions clean.
- **Add `tests/test_provider_probe.py`:** mock `aiohttp` responses and assert `probe_url`
  returns the correct `ProbeStatus` for each branch (active / inactive+detail / auth-failed /
  HTTP error+code / timeout / exception+truncated detail), and that `probe_all_urls` sorts
  successes-fastest-first and invokes `on_result` once per URL.
- **Add a formatter test:** `provider_editor._format_probe_message` maps each `ProbeStatus`
  to its exact badge string (guards the core↔UI boundary that #2 introduced).
- **Accept:** new tests pass and fail if the probe branch logic or formatter mapping changes.

---

## Suggested band ordering & PR grouping

```
PR A — Priority C cleanups (B6-5, B6-6, B6-9, B6-10)   ← low-risk, fast, do first
PR B — B6-7 + B6-8 (streaming off-thread + session_scope)  ← behavior change, own PR
PR C — B6-3 status-set dedup                            ← verify-then-extract
PR D — B6-1 main_window.py passes 2–3                   ← large mechanical split
PR E — B6-2 epg_view.py tab split                       ← largest, own session + smoke test
```
Rationale: clear the small, safe items first so the big splits (D, E) happen against a clean
tree. B6-4 is a no-op confirmation, fold it into PR A's description.

---

## Verification protocol (every task)

1. `venv/bin/python -m pytest tests/ -x -q` — all green.
2. For B6-7, add the regression test described and put before/after in the commit message.
3. Smoke-launch after any GUI split (`./run.sh`); confirm the affected view renders and
   live-updates.
4. Follow the **Session Wrap SOP** in `CLAUDE.md` when finishing the band (tests → commit →
   docs → memory → push). Update `ROADMAP.md`'s Code Health section and the session-handoff
   memory when the band lands.

---

## Definition of done for Band 6

- `main_window.py` and `epg_view.py` under 1000 lines (or documented residual + a planned
  pass); no method defined twice after a split.
- No icon-glyph literals or `ICON_PALETTE` in widget files; no raw hex/rgba in
  `provider_editor.py` or `filter_group_row.py`.
- Stream validation no longer blocks the UI thread; `main_window_streaming` uses
  `session_scope()`.
- `core/provider_probe.py` has unit coverage; the probe↔UI formatter boundary is tested.
- All existing behavior preserved (tests green + smoke-launch), with B6-7 the only
  intentional behavior change.
