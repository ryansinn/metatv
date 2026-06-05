# Sonnet Execution Prompt — Band 7

Paste the block below into a fresh Claude Sonnet 4.6 session (with tools, in this repo) to
execute `docs/REFACTOR_PLAN_BAND7.md`. It travels with the repo so the plan and its execution
brief stay together.

---

````text
You are an implementing engineer working in the MetaTV repository (Python/PyQt6 IPTV client).
Your job is to EXECUTE `docs/REFACTOR_PLAN_BAND7.md` end to end, with discipline. Do not
redesign the plan — implement it. Where the plan gives a target, hit it; where reality has
drifted, say so and adapt.

────────────────────────────────────────────────────────
READ FIRST (before writing any code)
────────────────────────────────────────────────────────
1. `docs/REFACTOR_PLAN_BAND7.md` — your task list (B7-1 … B7-12), the status snapshot, the
   PR grouping, the per-task guardrails, and the Definition of Done.
2. `docs/REFACTOR_PLAN_BAND6.md` — the previous band, for the mixin-extraction pattern (B6-1)
   and the epg_view deferral context (B6-2 → now B7-8).
3. `CLAUDE.md` — the project's Critical Rules. These OVERRIDE default behavior. The ones this
   band leans on most:
     • No unbounded / blocking DB work on the UI thread (B7-1…B7-6).
     • Qt threading — signals only; QPixmap/widgets/notifications only on the main thread.
     • Background pools are owned & long-lived — reuse `self.executor`, NEVER a per-call pool.
     • Database sessions — `session_scope()` for new/edited code (B7-2, B7-6).
     • View lifecycle on_activate/on_deactivate must be symmetric (B7-8).
     • Lookup tables — single source of truth in `channel_name_utils.py` (B7-12).
4. The "Session Wrap SOP" and "Coding Standards" sections of `CLAUDE.md`.

Confirm understanding by listing, in order, the tasks you intend to do, and flag any whose
premise no longer matches the code (verify each with `git grep` / `wc -l` / reading the file
before starting). Known-good baseline: `main` at squash `2e7ef5b`, 291 tests green;
`load_channels` is ALREADY off-thread (it is the template for B7-1, do not "fix" it);
`_StreamingMixin` is already off-thread + session_scope (only debt there is the dead
`source_id`/`media_type` params → B7-10).

────────────────────────────────────────────────────────
EXECUTION ORDER & PR GROUPING (one concern per PR — non-negotiable)
────────────────────────────────────────────────────────
Feature branch off `main` (NOT main directly). PR #7 was rejected-in-spirit for bundling 34
mixed commits; the owner's directive is ONE CONCERN PER PR. Pure refactors are verbatim moves,
kept separate from behavior changes and from features. Follow the plan's grouping:

  PR A — B7-1 + B7-2            (async-read seam + repository DTOs)     ← foundation
  PR B — B7-3                   (EPG count off-thread)
  PR C — B7-5                   (sidebar refresh off-thread — biggest win)
  PR D — B7-6                   (context-menu lookups off-thread + session_scope)
  PR E — B7-7                   (main_window pass 5 → <1000)            ← VERBATIM MOVE
  PR F — B7-4                   (series tree off-thread, on the new _SeriesMixin)
  PR G — B7-8                   (epg_view tab split → <1000)            ← VERBATIM MOVE + smoke
  PR H — B7-9                   (channel.py repo split → <1000)         ← VERBATIM MOVE
  PR I — B7-10 + B7-11 + B7-12  (cleanups)

Foundation first (A) so every conversion shares one seam. Do NOT collapse the grouping.

────────────────────────────────────────────────────────
PER-TASK PROTOCOL (non-negotiable)
────────────────────────────────────────────────────────
For EVERY task:
  a. Re-read the relevant code. Confirm the plan's premise still holds; if line numbers moved
     or it's already partly done, note it and adapt — don't blindly apply.
  b. TEST DISCIPLINE:
       • Behavior changes (B7-3, B7-4, B7-5, B7-6): write a regression test that pins CURRENT
         behavior (the data the path renders) AND asserts the work now happens off-thread (the
         query is submitted to the executor; the render happens in the main-thread slot). Put
         before/after in the commit message.
       • Pure refactors (B7-7, B7-8, B7-9, B7-12): write/identify a characterization test that
         pins current behavior, green before, refactor, green after. For B7-12 the existing
         `tests/test_compound_prefix.py` IS that test — keep it green.
       • B7-1: net-new unit tests for the seam (off-thread dispatch + stale-token drop).
       • B7-2: tests that each repository method returns DETACHED plain data (attribute access
         works after the session closes).
  c. FILE SPLITS ARE VERBATIM MOVES. Move code unchanged, fix imports, run tests. NEVER split
     and rewrite logic in the same commit — the Band 5 bar is `main_window.py`'s entire diff
     being 2 lines (import + class base). After a split, grep to prove no method is defined
     twice.
  d. Run `venv/bin/python -m pytest tests/ -x -q` — all green — before committing.
  e. Smoke-launch (`./run.sh` or `venv/bin/python -m metatv`) after ANY GUI split (B7-7, B7-8)
     and confirm the affected view renders and live-updates. Headless tests cannot catch a
     broken Qt layout. If you cannot launch a display, say so explicitly and mark the
     smoke-test as owner-to-verify in the PR body.

────────────────────────────────────────────────────────
TASK-SPECIFIC GUARDRAILS
────────────────────────────────────────────────────────
• B7-1 (seam): model it on the EXISTING `load_channels`/`_bg_load_channels` flow — read UI
  state on the main thread, submit `query_fn` to `self.executor`, marshal a plain-data result
  back via ONE `pyqtSignal(object)` on MainWindow, run `on_result` in the slot. Carry the
  stale-token drop. `query_fn` opens its OWN `session_scope()` and returns plain data only. Do
  NOT rewrite `load_channels` in this PR. THIS PR also adds the new CLAUDE.md Critical Rule
  documenting `_run_query` as the required pattern (the rule must point at real code, so it is
  added now that the primitive exists — not before).
• B7-2 (DTOs): ORM objects must NOT cross the thread boundary. Map ORM → frozen dataclass/dict
  INSIDE the `session_scope()` before returning. Keep DTOs minimal — only the fields the widget
  renders.
• B7-3/B7-5: show an immediate placeholder ("EPG — counting…" / keep the list, then repopulate)
  so the UI never looks frozen; update via the seam's main-thread slot.
• B7-6: convert only the heavy handlers (anything that grows with library size); trivial PK
  lookups may stay inline — DOCUMENT which and why. Migrate ALL touched sites to session_scope.
• B7-7 (main_window split): mixins must NOT define __init__ — all state stays owned by
  MainWindow.__init__. Add each new mixin ahead of QMainWindow in the MRO. Cross-mixin helpers
  import at module scope.
• B7-4 (series async): land it on the NEW `_SeriesMixin` from B7-7, in its OWN PR (refactor ≠
  behavior change).
• B7-8 (epg_view split): map shared cross-tab state FIRST (timers, the EPG refresh signal,
  date-combo). Shared state stays on the EpgView host and is passed in, never duplicated.
  Preserve on_activate/on_deactivate symmetry and stop EPG timers on deactivate.
• B7-9 (channel.py split): if you make it a package, keep a back-compat re-export so importers
  don't break. Verbatim moves only.
• B7-12 (bracket ladder): extract ONE `_classify_bracket(content)` helper used by both step 3
  and step 6a; behavior-preserving. Add the one-line language/region-overloading debt note. Do
  NOT re-map `_BRACKET_LANG_NORM` — it's entangled with the compound-locale work.

────────────────────────────────────────────────────────
WHAT "DONE" MEANS
────────────────────────────────────────────────────────
Meet the "Definition of done for Band 7" at the bottom of the plan:
  • main_window.py, epg_view.py, channel.py all < 1000 lines; no method defined twice.
  • No synchronous DB read on the UI thread in: EPG view switch, series tree, sidebar refresh,
    hot context menus.
  • One reusable async-read seam, unit-tested, documented in CLAUDE.md as the required pattern.
  • Repository hot-path reads return plain DTOs.
  • Dead params removed; Exclusions chip fixed or root-caused; one bracket-classification path.
  • All prior behavior preserved (tests green + smoke-launch); only intentional change = work
    moving off the UI thread.

────────────────────────────────────────────────────────
WRAP-UP
────────────────────────────────────────────────────────
When the band (or each PR) is complete, follow the Session Wrap SOP in CLAUDE.md:
tests → commit → update docs (ROADMAP.md Code Health section; tick Band 7 items) → update
memory (`project_session_handoff.md` with branch/commit/open work; refresh
`project_async_read_seam.md` if the seam's shape changed) → push → report what landed and
anything left for the owner to verify (e.g. smoke-launch if you ran headless). Open one PR per
group above; do not merge (the owner merges — self-approval is blocked).
````
