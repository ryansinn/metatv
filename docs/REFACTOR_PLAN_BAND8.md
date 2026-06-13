# MetaTV — Band 8 Refactor Plan (PR-A review follow-ups + carryover)

**Audience:** an implementing agent (Sonnet).
**Source:** senior review of **Band 7 PR A** (`c09386a` — B7-1 async-read seam + B7-2 repository
DTOs). PR A landed at A− quality. The one load-bearing gap (no error-delivery path in the seam)
was fixed in PR A itself before merge. This band collects the **non-blocking follow-ups** the
review flagged plus any Band 7 carryover.

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
- All prior behavior preserved — tests green; no user-visible change.
