# Sonnet Execution Prompt — Band 8

Paste the block below into a fresh Claude Sonnet 4.6 session (with tools, in this repo) to
execute `docs/REFACTOR_PLAN_BAND8.md`. It travels with the repo so the plan and its execution
brief stay together.

---

````text
You are an implementing engineer working in the MetaTV repository (Python/PyQt6 IPTV client).
Your job is to EXECUTE `docs/REFACTOR_PLAN_BAND8.md` end to end, with discipline. Do not
redesign the plan — implement it. Where the plan gives a target, hit it; where reality has
drifted, say so and adapt.

Band 8 is a small, low-risk debt-paydown band: the non-blocking follow-ups from the senior
review of Band 7 PR A (the async-read seam + repository DTOs). The one load-bearing fix from
that review — the seam's `on_error` path — ALREADY LANDED in PR A. Do NOT redo it. Everything
here is behavior-preserving cleanup.

────────────────────────────────────────────────────────
READ FIRST (before writing any code)
────────────────────────────────────────────────────────
1. `docs/REFACTOR_PLAN_BAND8.md` — your task list (B8-1 … B8-4), the status snapshot, and the
   Definition of Done.
2. `docs/REFACTOR_PLAN_BAND7.md` — the parent band; B8 follows up its PR A. Context for the seam
   (B7-1) and DTOs (B7-2).
3. `metatv/gui/main_window_async.py` and `metatv/core/repositories/dtos.py` — the code you are
   refining. Read them fully first.
4. `CLAUDE.md` Critical Rules — these OVERRIDE default behavior. The ones this band leans on:
     • `session_scope()` for new/edited code.
     • No unbounded / blocking DB work on the UI thread.
     • The `_run_query` — required-pattern rule (including the new `on_error` clause).
     • Background pools are owned & long-lived — reuse `self.executor`, NEVER a per-call pool.
5. The "Session Wrap SOP" and "Coding Standards" sections of `CLAUDE.md`.

Confirm understanding by listing, in order, the tasks you intend to do, and flag any whose
premise no longer matches the code (verify each with `git grep` / reading the file before
starting). Known-good baseline: Band 7 PR A merged; the seam's `on_error` path + tests exist —
do not reimplement them.

────────────────────────────────────────────────────────
EXECUTION ORDER & PR GROUPING (one concern per PR — non-negotiable)
────────────────────────────────────────────────────────
Feature branch off `main` (NOT main directly). ONE CONCERN PER PR.

  PR A — B8-1   (kill the N+1 in build_history_dtos)
  PR B — B8-2   (hoist DTO imports to module scope)
  PR C — B8-3   (read seam should not COMMIT on a pure read — investigate, then decide)
  PR D — B8-4   (OPTIONAL, only if Band 7 finished: load_channels adopts the seam)

These are independent; A→B→C order is convenience, not a dependency. Do NOT collapse the
grouping.

────────────────────────────────────────────────────────
PER-TASK PROTOCOL (non-negotiable)
────────────────────────────────────────────────────────
For EVERY task:
  a. Re-read the relevant code. Confirm the plan's premise still holds; if it's already done or
     drifted, note it and adapt — don't blindly apply.
  b. TEST DISCIPLINE — everything here is behavior-preserving:
       • B8-1: write a test asserting the batched output is IDENTICAL to the per-row output
         (same episode_code values, same ordering) for a multi-series fixture, AND that query
         count is bounded (engine query counter / SQLAlchemy `event.listen`, or prove no per-row
         path remains). Green before refactor (against current code) and after.
       • B8-2: the suite + an explicit `python -c "import metatv.gui.main_window"` import check is
         the test — green before and after the hoist.
       • B8-3: a test asserting no write/COMMIT occurs for a read-only query_fn (or, if you prove
         session_scope already no-ops, a test pinning that).
       • B8-4 (if taken): a characterization test pinning that the channel list loads the same
         rows; green before/after the migration.
  c. Run `venv/bin/python -m pytest tests/ -x -q` — all green — before committing.
  d. No GUI layout changes here, so headless tests suffice; a smoke-launch is nice-to-have, not
     required, unless B8-4 touches the channel-load path (then smoke-launch and confirm the list
     populates).

────────────────────────────────────────────────────────
TASK-SPECIFIC GUARDRAILS
────────────────────────────────────────────────────────
• B8-1 (N+1): ADD a batched `EpisodeRepository.get_last_played_for_series(...)` returning a
  dict; do NOT rewrite the existing single-row `get_last_played` (it has other callers). Build
  the episode_code map once, then loop channels with O(1) lookups. Watch the key: histories may
  span providers — key by what uniquely identifies a series row in this context.
• B8-2 (imports): PROVE there's no cycle before hoisting (`dtos.py` imports RepositoryFactory
  only under TYPE_CHECKING, so there should be none). If a real cycle surfaces, KEEP the lazy
  import and add a one-line comment naming the cycle — don't force it.
• B8-3 (commit-on-read): pick the SMALLEST correct option from the plan. Prefer not weakening any
  write path. If `session_scope` already effectively no-ops on a clean read, just document + test
  it and close the item with no code change. If you add `read_only=True` to `_run_query`, update
  the CLAUDE.md `_run_query` rule to match.
• B8-4 (load_channels): OPTIONAL and only if Band 7 is otherwise complete. Pure refactor —
  verbatim behavior. If in doubt, skip it and say so; it is explicitly deferrable.

────────────────────────────────────────────────────────
WHAT "DONE" MEANS
────────────────────────────────────────────────────────
Meet the "Definition of done for Band 8" at the bottom of the plan:
  • build_history_dtos issues a constant number of queries; output byte-identical to before.
  • DTO imports at module scope unless a real cycle is named in a comment.
  • The read seam does not COMMIT on a pure read (or it's proven it never did), test-pinned.
  • (If taken) load_channels runs through the one shared seam.
  • All prior behavior preserved — tests green; no user-visible change.

────────────────────────────────────────────────────────
WRAP-UP
────────────────────────────────────────────────────────
When the band (or each PR) is complete, follow the Session Wrap SOP in CLAUDE.md:
tests → commit → update docs (ROADMAP.md Code Health; tick Band 8 items) → update memory
(`project_session_handoff.md` with branch/commit/open work; refresh
`project_async_read_seam.md` if the seam's shape changed, e.g. a `read_only` param) → push →
report what landed and anything left for the owner to verify. Open one PR per group above; do
not merge (the owner merges — self-approval is blocked).
````
