# MetaTV — Band 8 Refactor Plan (PR-A review follow-ups + carryover)

> **STATUS (2026-06-15):** **B8-1, B8-2, B8-3, B8-5, B8-7 — DONE & merged to main**
> (562 tests green). **B8-4 (load_channels→seam) and B8-6 (expunge→DTO) — DEFERRED → Band 9:**
> both touch paths that cannot be smoke-tested headless (central channel load /
> play-details-series). B8-6's approach is recorded in memory `project_band78_autonomous`
> (play_media is duck-typed → a PlayableDTO drops in; details/series are the hard sites). Resume
> with a display available.

**Audience:** an implementing agent (Sonnet).
**Source:** senior reviews of **Band 7 PRs A / C / D** — B8-1…B8-4 from PR A (`c09386a`, async-read
seam + DTOs), B8-5 from PR C (`65a2b1b`, sidebar refresh off-thread), B8-6 from PR D (`76fa505`,
session_scope migration). Each PR landed at A−; its one load-bearing gap was fixed in-PR before
merge, and the non-blocking follow-ups were deferred here. **Read `docs/SONNET_EXECUTION_PROMPT_BAND7.md`
("Anti-patterns that got Band 7 PRs downgraded") before starting — the same three traps recurred
across A, C, and D and must not recur in Band 8.**

**Goal:** pay down the small, well-scoped debt the seam/DTO work left behind — without changing
user-visible behavior. Each item is independently shippable and low-risk; the value is keeping the
foundation clean before B7-3…B7-6 build on it heavily.

---

## Why this band exists (review findings from Band 7 PR A)

PR A's happy path was textbook (correct token timing on the main thread, DTOs mapped inside the
session, post-close attribute-access tests). Three smaller findings were deferred here rather than
bloating PR A:

1. **N+1 query in `build_history_dtos`.** Bounded today by `limit=30`, documented, not a bug — but
   a latency multiplier that's invisible at 30 rows and painful at scale.
2. **Cargo-culted lazy imports.** The DTO-returning repo methods import the DTO *inside* the method
   body to "avoid a circular import" that does not exist.
3. **Read-only queries issue a COMMIT.** The generic seam wraps every `query_fn` in
   `session_scope()`, which commits on success — semantically odd for pure reads.

None of these block downstream work; all three are cheap to fix correctly now.

---

## Ground rules for the implementer

1. **Follow `CLAUDE.md` Critical Rules.** This band leans on: *`session_scope()` for new code*,
   *No unbounded / blocking DB work on the UI thread*, *Database sessions*, and the
   *`_run_query` — required pattern* rule (now including the `on_error` clause).
2. **One concern per PR.** Group below. Do not collapse.
3. **No behavior change.** Every item here is behavior-preserving; pin each with a test that is
   green before and after (B8-1 also adds a test proving the batch result equals the per-row
   result).
4. **Run the suite after every task:** `venv/bin/python -m pytest tests/ -x -q`. All green.
5. **Verify premises before editing** — line numbers and method names may have drifted; `git grep`
   first.

---

## Status snapshot (verify before starting)

| Item | State at plan time |
|---|---|
| `_AsyncMixin` error path | **Done in PR A** — `on_error` callback + worker emits error envelope; stale-token drop applies to failures too. Do not redo. |
| `build_history_dtos` | `dtos.py` — loops channels, calls `repos.episodes.get_last_played()` once per series row (N+1). |
| DTO lazy imports | `channel.py` / `season.py` / `episode.py` import the DTO inside the method; `build_history_dtos` imports `MediaType` inside the function. |
| Seam commit-on-read | `main_window_async.py` `_worker` uses `self.db.session_scope()` (commits on success) for read-only `query_fn`. |

---

## Priority A — Review follow-ups (one PR each)

### B8-1 — Kill the N+1 in `build_history_dtos`
`build_history_dtos` (`core/repositories/dtos.py`) issues one `get_last_played()` per series row.
Collapse it to a single batched query.
- **Method:** add `EpisodeRepository.get_last_played_for_series(series_ids: list[str], provider_id)`
  (or a `(series_id, provider_id)`-keyed variant if histories can span providers) that returns a
  `dict[str, EpisodeDB]` (or a `dict` of the pre-extracted `episode_code`) in **one** query —
  `IN (...)` filter + per-series max-`last_played`. Build the `episode_code` map once, then loop
  channels with O(1) lookups.
- **Watch:** the existing single-row `get_last_played` has callers elsewhere — leave it; add the
  batch method alongside, don't rewrite the old one.
- **Test:** assert the batched `build_history_dtos` output is **identical** to the current per-row
  output for a fixture with multiple series (same `episode_code` values, same ordering), and that
  it issues a bounded number of queries (e.g. assert via a query counter / `event.listen` on the
  engine, or simply that no per-row call path remains).
- **Accept:** `build_history_dtos` does a constant number of queries regardless of row count;
  output unchanged; tests green.

### B8-2 — Hoist the DTO imports to module scope
The lazy imports in `channel.get_favorites_dto`, `season.get_seasons_dto`,
`episode.get_episodes_dto_by_season`, and the `MediaType` import inside `build_history_dtos` guard
against a circular import that does not exist (`dtos.py` imports `RepositoryFactory` only under
`TYPE_CHECKING`).
- **Method:** first *prove* there's no cycle — move each import to module top, run the suite +
  `venv/bin/python -c "import metatv.gui.main_window"`. If (and only if) a real cycle surfaces,
  keep the lazy import and add a one-line comment naming the cycle. Otherwise hoist them all.
- **Accept:** imports at module scope (or a named-cycle comment justifying each that stays); no new
  import errors; tests green.

### B8-3 — Read-only path should not COMMIT *(investigate, then decide)*
The seam's `_worker` wraps `query_fn` in `session_scope()`, which commits on success. For pure
reads this is a no-op write transaction — harmless on SQLite today, but semantically wrong and a
faint lock-contention cost if a read replica or busier writer ever lands.
**Widened by B7-6 (PR-D Lesson 3):** the migration routed ~32 handlers — many of them pure reads
(context-menu lookups, play-by-id, details) — through `session_scope`, so every one now issues a
COMMIT-on-exit for a read. Scope this item against that larger surface, not just the seam.
- **Options (pick the smallest that's correct):**
  1. Add a `read_only=True` path to the seam that uses a non-committing session context (e.g. a
     `session_scope(commit=False)` variant or a plain `get_session()` + `finally: close()`), and
     default `_run_query` to it (all current `query_fn`s are reads).
  2. If `session_scope` already rolls back / no-ops when there are no dirty objects, **document
     that** and close the item with a test asserting no write occurs — no code change.
- **Constraint:** do not weaken write paths; this is scoped to the read seam only. Confirm a
  `query_fn` that accidentally writes still has *some* defined behavior (prefer: rolled back).
- **Accept:** read-only `query_fn`s no longer trigger a COMMIT (or it's proven they already don't),
  with a test pinning it; CLAUDE.md `_run_query` rule updated if the signature gained `read_only`.

---

### B8-5 — Unify the async-read pattern: a `BackgroundRefreshMixin` widgets can reach
*Source: senior review of **Band 7 PR C** (`65a2b1b` — B7-5 sidebar refresh off-thread).*
The `_run_query` seam (B7-1) lives on `MainWindow._AsyncMixin`, so standalone sidebar `QWidget`s
can't reach it. PR C therefore hand-rolled the seam's mechanics a **third and fourth** time
(Favorites/History/Queue, on top of the pre-existing Recommended): own `ThreadPoolExecutor` +
`_data_ready` signal + `_bg_refresh` (try/except → `emit(None)`) + `_on_data_ready`. That's exactly
the duplication the seam was meant to kill, but the seam wasn't built where its biggest customers
(the sidebar — N lock-prone reads) could use it.
- **Method:** extract the shared skeleton into a small `BackgroundRefreshMixin` (own executor,
  `_data_ready: pyqtSignal(object)`, the `_bg_refresh` try/except/emit-`None` wrapper, the
  `_on_data_ready` clear+dispatch) that both the sidebar sections and — where it fits — the
  `MainWindow` seam compose. Sections supply a `_load()` (returns DTOs) and a `_populate(data)`.
  Alternative if a mixin fights Qt's metaclass: have sections accept an injected `run_query`
  callable from `MainWindow`. Pick whichever keeps the call sites smallest.
- **Preserve:** `max_workers=1` (SQLite-lock rule), the `_executor` attribute name (the closeEvent
  cleanup loop keys on `hasattr(section, "_executor")`), and the `None`→`show_load_error` failure
  row (CLAUDE.md "Background refresh failure must be visible").
- **Accept:** Favorites/History/Queue/Recommended share one refresh skeleton; no behavior change;
  the four copies collapse to one; CLAUDE.md "Widget-level sections can't reach the seam" rule
  updated to point at the unified primitive instead of the verbatim-copy pattern; tests green.
- **Note:** This was deliberately *not* fixed in PR C (that PR was behavior-preserving and followed
  the existing Recommended precedent). It is the one larger item the PR-C review deferred here.

### B8-6 — Convert the read-then-consume handlers to DTOs (kill the `expunge` coupling)
*Source: senior review of **Band 7 PR D** (`76fa505` — B7-6 session_scope migration).*
B7-6 correctly stopped sessions leaking, but to pass a `ChannelDB`/`EpisodeDB` out of the `with`
block it used `session.expunge(obj)` before the scope's exit-commit. That works **only because the
ORM currently has no `relationship()` and no `deferred()` columns** — an invariant that lives in a
CLAUDE.md note and three runtime tests, nowhere in the model. The day a relationship is added,
every expunge call site (`play_channel_by_id`, `play_queue_item_id`, `play_favorite_id`,
`play_from_history_id`, `show_channel_details_by_id`, `on_channel_selection_changed`,
`_on_retry_play_requested`, `_show_watch_alert_details`) silently regresses.
- **Method:** give these handlers a small DTO (or reuse `FavoriteDTO`/a new `PlayableDTO`) carrying
  exactly the fields the consumers touch (`id`, `name`, `media_type`, `source_id`, `provider_id`,
  and whatever `play_media`/`drill_into_series`/`update_details_pane_for_channel` actually read —
  audit each). Build it inside the `session_scope`, return/pass the DTO, drop the `expunge`. This is
  the same boundary `_run_query` already enforces ("Never return ORM objects").
- **Watch:** `play_media`/`drill_into_series`/`update_details_pane_for_channel` currently accept an
  ORM `ChannelDB`. Either adapt them to the DTO or keep a thin ORM-fetch at the very point of use —
  pick the one that removes the cross-boundary ORM handoff without ballooning the diff.
- **Also (PR-D Lesson 4, minor):** in `_bg_fetch_versions` / `_bg_fetch_similar_titles` the heavy
  scoring/sorting and the early-return `emit()`s run *inside* the open session. They're on a worker
  thread (no UI block) and unchanged from before, so it's not a regression — but the cleaner shape
  is pull-rows → close session → score/emit. Fold in opportunistically if touching these.
- **Accept:** no ORM object crosses a `session_scope` boundary in `_FavoritesMixin`/`_MetadataMixin`;
  the `session.expunge` calls are gone; the CLAUDE.md "ORM objects must not outlive their session"
  rule is updated to point at the DTO path as the norm; behavior unchanged; the B7-6 runtime tests
  (detached-column-readable) still pass.

### B8-7 — ✅ DONE (merged #19) — Migrate `WatchAlertsSection.refresh()` to `BackgroundRefreshMixin` (deferred from EPG band)
*Source: deliberate deferral from the EPG band (PR-1 plan note).*
`WatchAlertsSection.refresh()` (`metatv/gui/sidebar/alerts.py`) runs its watchlist queries
synchronously on the main thread and issues an N+1 `ChannelDB` lookup per programme — a direct
violation of the "no unbounded DB work on the UI thread" rule. Migrating it to
`BackgroundRefreshMixin` (landed in B8-5) will bring it in line with Favorites/History/Queue and
eliminate the main-thread block at sidebar load time.
- **Method:** compose `BackgroundRefreshMixin` on `WatchAlertsSection`; move the session +
  `get_live_for_watchlist` / `get_upcoming_for_watchlist` + per-programme channel lookup into
  `_load_rows()` (worker thread, returns a DTO list); populate in `_populate_rows()` on the main
  thread. The DTOs need the fields currently read from `ChannelDB` after the inline lookup — audit
  and define in `dtos.py` or reuse an existing DTO.
- **Accept:** `refresh()` returns immediately; no DB work on the main thread; `BackgroundRefreshMixin`
  handles load error visibility; tests green.

---

## Priority B — Carryover (only if not already done in Band 7)

Verify against `main` first — these may have shipped in later Band 7 PRs. If done, strike them.

### B8-4 — `load_channels` adopts the seam *(optional, deferred from B7-1)*
B7-1 deliberately did **not** rewrite `load_channels` onto `_run_query`. Once the seam has proven
itself across B7-3…B7-6, migrate `load_channels`/`_bg_load_channels` to it so there is exactly one
async-read path. Pure refactor, behavior-preserving, characterization test green before/after.
- **Accept:** `load_channels` uses `_run_query`; the bespoke `_load_channels_token`/`_bg_load_channels`
  wiring is gone; channel list still loads identically; tests green.

---

## Definition of done for Band 8
- `build_history_dtos` issues a constant number of queries; output byte-identical to before.
- DTO imports live at module scope unless a real cycle is named in a comment.
- The read seam does not COMMIT on a pure read (or it's proven it never did), test-pinned.
- (If taken) `load_channels` runs through the one shared seam.
- (B8-5) The four hand-rolled sidebar refresh copies collapse to one shared primitive; the
  CLAUDE.md widget-pattern rule points at it.
- (B8-6) No ORM object crosses a `session_scope` boundary in the favorites/metadata mixins; the
  `session.expunge` fallback is replaced by DTOs; the B7-6 detached-column runtime tests still pass.
- All prior behavior preserved — tests green; no user-visible change.
