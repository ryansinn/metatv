# MetaTV — Band 9 Refactor Plan (deferred seam items + EPG cosmetic cleanup)

> **STATUS: DRAFT — pending Opus review and sequencing.** Do not start implementing until
> Opus has reviewed and approved this plan. Premises were verified in code at the time of
> writing (2026-06-15, branch `docs/band8-wrap-and-band9-plan`) but line numbers may
> drift before implementation begins — re-verify with `git grep` before editing.

**Audience:** an implementing agent (Sonnet).
**Source:** carryover from Band 8 (B8-4, B8-6 — deferred because they cannot be
smoke-tested headless), plus small EPG-band cosmetic debts identified during Band 8 wrap.
**Read `docs/SONNET_EXECUTION_PROMPT_BAND7.md`** ("Anti-patterns that got Band 7 PRs
downgraded") before starting — the same three traps (ORM objects crossing session
boundaries, bare `get_session()` instead of `session_scope`, shape-only tests) must not recur.

**Goal:** close out the last two architectural deferred items and do a handful of targeted
cosmetic fixes, all while keeping behavior identical. Every item is independently
shippable; they may be sequenced as separate PRs.

---

## Ground rules for the implementer

1. **Follow `CLAUDE.md` Critical Rules.** Key ones for this band: *ORM objects must not
   outlive their session*, *`_run_query` — the required pattern*, *Styles — two-layer
   `theme.py`*, *No unbounded DB work on the UI thread*, *Icons — always from `icons.py`*.
2. **One concern per PR.** B9-1, B9-2, and B9-3 are separate PRs.
3. **No behavior change.** Every item is behavior-preserving; pin each with a test that
   executes the changed code path and asserts the outcome that would break on regression.
4. **Verify premises before editing** — re-run `git grep` for file:line anchors; they
   drift between sessions.
5. **Run the suite after every task:** `venv/bin/python -m pytest tests/ -x -q`. All green.
6. **Items B9-1 and B9-2 require a display to smoke-test** (central channel-load path,
   play/details/series paths). Implement against the headless test harness first; then
   manually run `./run.sh` to confirm the channel list loads and playback/details still
   work before marking done. Do not land blind.

---

## Status snapshot (verify before starting)

| Item | State at plan time |
|---|---|
| `load_channels` bespoke wiring | `main_window.py:288` (`_load_channels_token: int`), `:1521–1523` (manual token increment + `executor.submit`), `:1525` (`_bg_load_channels`), `:1630` (token check in `_on_channels_loaded`). NOT using `_run_query`. |
| `session.expunge` sites | `main_window_favorites.py` lines 105, 299, 503, 551, 563, 729, 811. `main_window_metadata.py` lines 343, 362. Nine sites total. |
| Dead local import in `_classify_event` | `epg_view.py:74` — `from metatv.core.repositories.dtos import LiveEventDTO`. Import is unused in the function body (duck-typed `dto`); comment says "avoid circular" but `dtos.py` does not import `epg_view`. |
| Dormant view files | `metatv/gui/events_view.py` and `metatv/gui/sports_view.py` are only referenced in `tests/test_view_lifecycle.py` (import guards). Not imported anywhere in the main app code. The Events tab was built inside `epg_view.py`, not these files. |
| `QColor("#555")` in `alerts.py` | `metatv/gui/sidebar/alerts.py:332` — `item.setForeground(0, QColor("#555"))`. `theme.py` already has `COLOR_FAINT = "#555"` at line 34; use that. |
| Triple-`🎯` icon collision | `metatv/gui/icons.py:60,70,72` — `preferred_version_icon`, `preferences_icon`, and `events_icon` all use `🎯`. Confirmed: `events_icon` is used by `epg_view.py:295`; the other two are legacy `config.*` references (details pane). Cosmetic issue only — not a bug today. |

---

## Priority A — Deferred seam items (display required to smoke-test)

### B9-1 — `load_channels` adopts the `_run_query` seam *(carryover B8-4)*

`load_channels` / `_bg_load_channels` in `main_window.py` is the last bespoke async-read
path that predates the `_run_query` seam introduced in B7-1. It has its own int token
(`_load_channels_token`), its own `executor.submit` call, its own `session.get_session()`
+ `finally: close()` pattern, and its own token check in the `_on_channels_loaded` slot.
Migrating it to `_run_query` makes the codebase's async-read shape uniform.

- **Method:**
  1. Replace `self._load_channels_token: int` (line 288) with `self._load_channels_token: list[int] = [0]` (the list-ref form that `_run_query`'s `token_ref` uses).
  2. In `load_channels()` (line ~1520), replace the manual increment + `executor.submit(_bg_load_channels, params, token)` with a `_run_query(lambda repos: _do_load(repos, params), self._on_channels_loaded, token_ref=self._load_channels_token)` call. The `query_fn` must return plain data (channels list + populated params dict) — audit what `_bg_load_channels` currently returns via `_channels_loaded.emit(channels, params)` and match that shape.
  3. Drop `_bg_load_channels` and the bespoke `_channels_loaded` signal wiring once `_run_query` dispatches to `_on_channels_loaded`.
  4. In `_on_channels_loaded`, remove the manual token check (`params.get('token') != self._load_channels_token`) — stale-drop is handled by `_run_query`'s token mechanism.
  5. Pass `on_error` to `_run_query` so a failed channel query clears any loading spinner rather than hanging. The existing `logger.error(...)` in `_bg_load_channels:1622` is the model for the error body.
- **Watch:**
  - `_bg_load_channels` currently uses bare `session = self.db.get_session()` + `finally: session.close()`. The seam uses `session_scope(commit=False)` — confirm a read-only `query_fn` is semantically equivalent (it is, per B8-3).
  - The token check shape differs: the old code passes `token` inside `params` dict (line 1621: `params['token'] = token`), then checks `params.get('token')`. The seam's list-ref token drops stale results before calling `on_result`. Make sure the token key is not left in `params` after migration or the `_on_channels_loaded` slot still checks it (either clean it up or leave a comment).
  - `_on_channels_loaded` must stay a two-argument slot (`channels, params`) since the seam's `on_result` receives whatever `query_fn` returns — return a tuple `(channels, params)` and unpack in the slot, or restructure as a single DTO. Choose the minimal diff.
  - `_clear_provider_busy()` is called at the top of `_on_channels_loaded` (line 1635). This must remain on the main thread — it already is, since `_on_channels_loaded` runs there after `_run_query` dispatches via `_query_result` signal.
- **Test:** write a characterization test that constructs `MainWindow` via `__new__` (or the existing test fixture pattern), wires up an in-memory `Database`, calls `load_channels()`, processes events (or calls `_on_channels_loaded` directly with a captured result), and asserts the channel list populates. Green before and after. The test does not need a display — it tests the slot logic in isolation.
- **Accept:** `_load_channels_token` is a `list[int]`; `_bg_load_channels` is deleted; `_channels_loaded` signal is gone or repurposed; `load_channels()` calls `_run_query`; `_on_channels_loaded` no longer does a manual token check. Channel list loads identically under manual smoke-test. Tests green.

---

### B9-2 — Replace `session.expunge` with DTOs in favorites/metadata mixins *(carryover B8-6)*

B7-6 migrated the favorites/metadata handlers to `session_scope()`, but passed a raw
`ChannelDB` (and in one case `EpisodeDB`) out of the `with` block using `session.expunge`.
This works **only because the ORM currently has no `relationship()` or `deferred()` columns**
— a CLAUDE.md-documented invariant. The correct pattern is to build a DTO inside the
`session_scope` and drop the expunge entirely.

**Consumer field audit (what each downstream method reads from the channel object):**

- `play_media(channel)` (`main_window_streaming.py:230`) — reads: `channel.id`, `channel.name`, `channel.stream_url`, `channel.media_type`.
- `drill_into_series(channel)` (`main_window.py:2081`) — reads: `channel.name`, `channel.provider_id`, `channel.source_id`.
- `update_details_pane_for_channel(channel)` (`main_window_metadata.py:366`) — reads: `channel.media_type`, `channel.provider_id`, `channel.name`, `channel.id`. Also calls `self.details_pane.show_channel(channel, ...)` which may read additional fields from the raw `ChannelDB` — audit `details_pane.show_channel()` before finalizing the DTO fields.
- `play_episode(last_episode)` in `play_from_history_id` (`main_window_favorites.py:563`) — the expunged `EpisodeDB` is passed to `play_episode` — audit what fields `play_episode` reads.

**Expunge sites and their handlers** (verified at `main_window_favorites.py` lines 105, 299, 503, 551, 563, 729, 811; `main_window_metadata.py` lines 343, 362):

| Site | Handler | Consumer |
|---|---|---|
| `favorites.py:105` | `_on_retry_play_requested` | `play_media(channel)` |
| `favorites.py:299` | `play_queue_item_id` | `play_media` or `drill_into_series` |
| `favorites.py:503` | `_show_watch_alert_details` | `details_pane.show_channel(channel)` |
| `favorites.py:551` | `play_from_history_id` | `play_media` or `drill_into_series` |
| `favorites.py:563` | `play_from_history_id` | `play_episode(last_episode)` (EpisodeDB) |
| `favorites.py:729` | `play_favorite_id` | `play_media` or `drill_into_series` |
| `favorites.py:811` | `play_channel_by_id` | `play_media` or `drill_into_series` |
| `metadata.py:343` | `show_channel_details_by_id` | `update_details_pane_for_channel(channel)` |
| `metadata.py:362` | `on_channel_selection_changed` | `update_details_pane_for_channel(channel)` |

- **Method:**
  1. Add a `PlayableDTO` to `core/repositories/dtos.py` containing the union of fields consumed across all sites: `id`, `name`, `media_type`, `stream_url`, `source_id`, `provider_id`, and any additional fields `details_pane.show_channel()` reads from the raw ORM object (audit this — it's the likely source of scope creep).
  2. In each handler, replace the `repos.channels.get_by_id(channel_id)` + `session.expunge(channel)` pattern with a `PlayableDTO`-returning helper (e.g. `repos.channels.get_playable_dto(channel_id) -> PlayableDTO | None`). Build it inside the `session_scope`; the `with` block returns the DTO.
  3. Update `play_media`, `drill_into_series`, and `update_details_pane_for_channel` to accept `PlayableDTO` OR keep them accepting a duck-typed object — whichever minimizes the diff. `play_media` only reads five fields; a `PlayableDTO` slots in with no changes to the method body.
  4. For the `EpisodeDB` expunge at line 563 — define a `PlayableEpisodeDTO` (or extend `EpisodeDTO` if it already has `stream_url` and `title`) and convert `play_episode` to accept it.
  5. Drop all nine `session.expunge(...)` calls.
- **Watch:**
  - `details_pane.show_channel(channel)` is a thick consumer — it may access many `ChannelDB` fields (genre, year, poster_url, raw_data, detected_title, etc.). Audit `details_pane.py` and `details_sections.py` before finalizing `PlayableDTO` — the DTO must carry every field these methods touch. If the field list is very long, consider whether a thin `show_channel` refactor (passing individual fields rather than the whole object) is preferable.
  - `drill_into_series` opens its own `get_session()` + `finally: close()` block (legacy pattern, line 2088) — do not convert that in this PR; the scope here is only the expunge sites.
  - `_apply_favorite_toggle` is the documented exception (CLAUDE.md) — do NOT touch it.
- **Test:** construct a handler instance via `__new__`, wire a `tmp_path` in-memory `Database` with `create_tables()`, insert a test `ChannelDB` row, call the handler, let the `session_scope` close, then assert the DTO fields are still readable (the regression this replaces was `DetachedInstanceError`). This is the same test shape as the B7-6 runtime tests — ensure those still pass.
- **Accept:** no `session.expunge` call remains in `_FavoritesMixin` or `_MetadataMixin`; no ORM object crosses a `session_scope` boundary in these files; `PlayableDTO` (and `PlayableEpisodeDTO` if needed) are in `dtos.py`; `details_pane.show_channel` receives the DTO; B7-6 runtime tests pass; behavior unchanged under manual smoke-test. Tests green.

---

## Priority B — EPG cosmetic cleanup (headless-testable, low-risk)

### B9-3 — Bundle EPG-band cosmetic follow-ups

These are four small, independent cleanups from the EPG band that are individually too
small for their own PRs. Bundle into one low-risk PR.

#### B9-3a — Remove dead local import in `_classify_event`

**Verified:** `epg_view.py:74` has `from metatv.core.repositories.dtos import LiveEventDTO`
inside `_classify_event`. The function body does NOT use `LiveEventDTO` — it only accesses
`dto.always_available` and `dto.start_time` (duck-typed). The comment says "local import,
avoid circular" — but `dtos.py` imports nothing from `epg_view`, so no cycle exists.

B8-2 already proved the pattern: move to module scope or delete if unused. Since
`LiveEventDTO` IS used elsewhere in `epg_view.py` (docstrings at lines 88, 94, 127, 132;
type annotation in line 258's comment; worker at line 770), the right fix is to hoist it
to a module-level import (alongside the other `dtos` imports) and remove the local one.

- **Method:** add `from metatv.core.repositories.dtos import LiveEventDTO` to the module-level imports (near line 17). Remove the local import at line 74 and its comment.
- **Test:** `python -c "import metatv.gui.epg_view"` must not raise; the existing suite must stay green.
- **Accept:** no local import inside `_classify_event`; `LiveEventDTO` imported at module scope.

#### B9-3b — Delete dormant `events_view.py` and `sports_view.py`

**Verified:** `metatv/gui/events_view.py` and `metatv/gui/sports_view.py` are only
referenced by `tests/test_view_lifecycle.py` (import guards at lines 59 and 66). They are
not imported anywhere in the main application. The Events tab was implemented inside
`epg_view.py` (PR #17); these files are dead.

- **Method:**
  1. Delete both files: `git rm metatv/gui/events_view.py metatv/gui/sports_view.py`.
  2. Remove or update the two test import-guard blocks in `tests/test_view_lifecycle.py` that reference them — if the tests were testing lifecycle patterns of those now-deleted views, replace with a note or remove the test entirely (don't leave a test that imports a deleted module).
- **Watch:** confirm no other file imports these — `git grep "events_view\|sports_view"` must return only the test file (verified at plan time; re-verify before deleting).
- **Test:** the full suite must be green after deletion. `python -m pytest tests/test_view_lifecycle.py` specifically.
- **Accept:** both files deleted; no import errors; tests green.

#### B9-3c — Replace `QColor("#555")` literal in `alerts.py` with `theme.COLOR_FAINT`

**Verified:** `metatv/gui/sidebar/alerts.py:332` — `item.setForeground(0, QColor("#555"))`.
`metatv/gui/theme.py:34` already has `COLOR_FAINT = "#555"` (the canonical token for faint
hints / empty states). This is a one-line fix.

- **Method:** in `alerts.py`, replace the literal with the token:
  ```python
  # Before
  item.setForeground(0, QColor("#555"))
  # After
  from metatv.gui import theme as _theme
  item.setForeground(0, QColor(_theme.COLOR_FAINT))
  ```
  Check whether `metatv.gui.theme` is already imported in `alerts.py`; if so, use the existing import alias rather than adding a duplicate.
- **Test:** no visual regression (manual check); `QColor("#555")` must not appear in `alerts.py` after the change.
- **Accept:** no hex literal in `alerts.py`; uses `_theme.COLOR_FAINT`.

#### B9-3d — Resolve the triple-🎯 icon collision (assess, then decide)

**Verified:** `icons.py` lines 60, 70, 72 — `preferred_version_icon`, `preferences_icon`,
and `events_icon` all use `🎯`. The collision is cosmetic today (each appears in a
different UI surface) but confuses the icon vocabulary. `events_icon` is the newest and the
odd one out semantically — the other two are about "preference/recommendation" contexts.

- **Method:** choose a distinct glyph for `events_icon` that evokes "live events / schedule". Candidates: `📅` (calendar), `🎪` (events/circus), `📡` (live broadcast), `🗓️` (calendar). Confirm the chosen glyph renders legibly at Qt's small tab font size before committing. Update `icons.py:72` only; `epg_view.py:295` reads from `icons.events_icon` and will pick it up automatically.
- **Watch:** `preferred_version_icon` and `preferences_icon` are still accessed via `self.config.*` in legacy code (`details_sections.py:514`, `details_versions.py:258,283`, `sidebar/recommended.py:24,42`, `main_window.py:658`) — those are not in scope for this item; do not touch them.
- **Test:** visual check that the Events tab tab-bar renders the new icon.
- **Accept:** `events_icon` uses a glyph distinct from `preferences_icon` / `preferred_version_icon`; `icons.py` is the only file changed; the EPG Events tab displays the new icon.

---

## Candidate B9 items (file-size splits — Opus to decide sequencing)

The following files exceed the 1000-line guideline. They were flagged as B7-7/8/9 in
`docs/REFACTOR_PLAN_BAND7.md` but were not carried into Band 8. Line counts as of
2026-06-15:

| File | Lines | Note |
|---|---|---|
| `metatv/gui/main_window.py` | 2668 | Band 6 pass 4 brought it to 2457; it has grown since. Candidate for pass 5: extract the provider-toggle / channel-load orchestration or the series-tree logic into a new mixin. |
| `metatv/gui/epg_view.py` | 2676 | The EPG Events tab was added here (PR #17) rather than in a split file. A tab-split (Watchlist / OnNow / Browse / Events into sub-modules) was B6-2 / B7-8 — still open. |
| `metatv/core/repositories/channel.py` | 817 | Below 1000; borderline. Was flagged as B7-9 (`get_live_events_dto` added in PR #17). May not need splitting yet. |

**These are NOT assigned to Band 9 as items.** They are carried forward as candidates for
a future band (Band 10 or a dedicated split band). Opus will decide whether to prioritize
them above or below the EPG-surface roadmap items (TMDb, EPG Browse makeover, etc.).

---

## Definition of done for Band 9

- `load_channels` uses `_run_query`; the bespoke `_bg_load_channels` / `_load_channels_token: int` / `_channels_loaded` signal wiring is gone; channel list loads identically under a real display; the seam's stale-drop handles token management.
- No `session.expunge` call remains in `_FavoritesMixin` or `_MetadataMixin`; `PlayableDTO` (and `PlayableEpisodeDTO` if needed) are in `dtos.py`; B7-6 runtime tests pass.
- `_classify_event` has no local import; `LiveEventDTO` is at module scope in `epg_view.py`.
- `events_view.py` and `sports_view.py` are deleted; no import errors; test suite green.
- `QColor("#555")` replaced with `_theme.COLOR_FAINT` in `alerts.py`.
- `events_icon` uses a glyph distinct from `preferences_icon` / `preferred_version_icon`.
- All prior behavior preserved; tests green; no user-visible change.
