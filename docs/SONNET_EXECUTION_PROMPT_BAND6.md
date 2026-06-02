# Sonnet Execution Prompt — Band 6

Paste the block below into a fresh Claude Sonnet 4.6 session (with tools, in this repo) to
execute `docs/REFACTOR_PLAN_BAND6.md`. It travels with the repo so the plan and its
execution brief stay together.

---

````text
You are an implementing engineer working in the MetaTV repository (Python/PyQt6 IPTV
client). Your job is to EXECUTE `docs/REFACTOR_PLAN_BAND6.md` end to end, with discipline.
Do not redesign the plan — implement it. Where the plan gives a target, hit it; where
reality has drifted, say so and adapt.

────────────────────────────────────────────────────────
READ FIRST (before writing any code)
────────────────────────────────────────────────────────
1. `docs/REFACTOR_PLAN_BAND6.md` — your task list (B6-1 … B6-10), the status snapshot,
   the suggested PR grouping, and the Definition of Done.
2. `docs/REFACTOR_PLAN.md` — the original plan; B6-1/B6-2/B6-3/B6-4 are carryover P3/P4
   items from it, so read those sections for the original intent.
3. `CLAUDE.md` — the project's Critical Rules. These OVERRIDE default behavior. The ones
   this band leans on most:
     • Icons — always from `metatv/gui/icons.py` (B6-5).
     • Styles — two-layer `theme.py`; tokens for ALL hex/rgba/px (B6-6).
     • Database sessions — `session_scope()` for new/edited code (B6-8).
     • No unbounded/blocking work on the UI thread + Qt threading = signals only (B6-7).
     • Background pools are owned & long-lived — reuse `self.executor`, never a per-call
       pool (B6-7).
     • View lifecycle on_activate/on_deactivate must be symmetric (B6-2).
4. The "Session Wrap SOP" and "Coding Standards" sections of `CLAUDE.md`.

Confirm understanding by listing, in order, the tasks you intend to do, and flag any whose
premise no longer matches the code (verify each with `git grep` / `wc -l` / reading the
file before starting — some items may already be partly done; the plan's status snapshot
lists known-resolved ones: `provider_editor.py` is already < 1000, the `--help` artifact is
gone, and PR #6 review items #1–#4 are already fixed — do NOT redo those).

────────────────────────────────────────────────────────
EXECUTION ORDER & PR GROUPING
────────────────────────────────────────────────────────
Feature branch off `main` (NOT main directly). Follow the plan's suggested grouping:

  PR A — B6-5, B6-6, B6-9, B6-10  (icons, theme tokens, hoist imports, probe tests)
  PR B — B6-7, B6-8               (stream validation off-thread + session_scope)
  PR C — B6-3                     (status-set dedup, verify-then-extract)
  PR D — B6-1                     (main_window.py passes 2–3)
  PR E — B6-2                     (epg_view.py tab split — own session, smoke-tested)

One commit per task (B6-N). Do the small/safe PR A first so the big splits (D, E) land
against a clean tree. B6-4 is a no-op confirmation — fold it into PR A's description.

────────────────────────────────────────────────────────
PER-TASK PROTOCOL (non-negotiable)
────────────────────────────────────────────────────────
For EVERY task:
  a. Re-read the relevant code. Confirm the plan's premise still holds; if line numbers
     moved or it's already fixed, note it and adapt — don't blindly apply.
  b. TEST DISCIPLINE:
       • Pure refactors (B6-1, B6-2, B6-3, B6-5, B6-6, B6-8, B6-9): write/identify a
         characterization test that pins CURRENT behavior, see it green on the current
         tree, refactor, see it green again. A refactor with no guarding test is the most
         likely place to silently break behavior.
       • B6-7 (behavior change): write a regression test that captures the failover
         ordering + stat-update logic AND that play_media no longer blocks (the player
         launch happens from the signal slot). Put before/after in the commit message.
       • B6-10: net-new unit tests for `core/provider_probe.py` and the
         `_format_probe_message` boundary.
  c. FILE SPLITS ARE VERBATIM MOVES. Move code unchanged, fix imports, run tests. NEVER
     split and rewrite logic in the same commit — the Band 5 bar is `main_window.py`'s
     entire diff being 2 lines (import + class base). After a split, grep to prove no
     method is defined twice.
  d. Run `venv/bin/python -m pytest tests/ -x -q` — all green — before committing.
  e. Smoke-launch (`./run.sh` or `venv/bin/python -m metatv`) after ANY GUI split (B6-1,
     B6-2) and confirm the affected view renders and live-updates. Headless tests cannot
     catch a broken Qt layout. If you cannot launch a display, say so explicitly and mark
     the smoke-test as owner-to-verify in the PR body.

────────────────────────────────────────────────────────
TASK-SPECIFIC GUARDRAILS
────────────────────────────────────────────────────────
• B6-1 (main_window split): mixins must NOT define __init__ — all state stays owned by
  MainWindow.__init__. Add each mixin ahead of QMainWindow in the MRO. Cross-mixin helpers
  import at module scope.
• B6-2 (epg_view split): map shared cross-tab state FIRST (timers, the EPG refresh signal,
  date-combo). Shared state stays on the EpgView host and is passed in, never duplicated.
  Preserve on_activate/on_deactivate symmetry and stop EPG timers on deactivate.
• B6-3 (status-set dedup): VERIFY the sites compute the same set before merging. If two are
  legitimately different axes, leave them and document why — a one-paragraph "they don't
  overlap" note is a valid result, not a failure.
• B6-6 (theme tokens): appearance-PRESERVING. Add tokens with the EXACT existing hex; do
  not harmonize colours. `filter_group_row._ACCENT` stays a map — only its values become
  tokens.
• B6-7 (off-thread validation): reuse `self.executor`, do NOT create a new ThreadPoolExecutor.
  Notifications/QPixmap/widget updates happen ONLY in the main-thread signal slot. Keep the
  `loading_channels` double-launch guard.
• B6-8: coordinate with B6-7 — if both land, do B6-7 first, then B6-8 on the new structure.
  Watch the per-attempt failover stat commits; preserve their durability semantics.
• B6-9: hoist imports unless it causes a circular import; for any you must leave lazy, add a
  one-line comment naming the circular-import reason.

────────────────────────────────────────────────────────
WHAT "DONE" MEANS
────────────────────────────────────────────────────────
Meet the "Definition of done for Band 6" at the bottom of the plan:
  • main_window.py and epg_view.py < 1000 lines (or a documented residual + planned pass);
    no method defined twice after a split.
  • No icon-glyph literals or ICON_PALETTE in widget files; no raw hex/rgba in
    provider_editor.py or filter_group_row.py.
  • Stream validation no longer blocks the UI thread; main_window_streaming uses
    session_scope().
  • core/provider_probe.py has unit coverage; the probe↔UI formatter boundary is tested.
  • All prior behavior preserved (tests green + smoke-launch); B6-7 the only intentional
    behavior change.

────────────────────────────────────────────────────────
WRAP-UP
────────────────────────────────────────────────────────
When the band (or each PR) is complete, follow the Session Wrap SOP in CLAUDE.md:
tests → commit → update docs (ROADMAP.md Code Health section; tick Band 6 items) →
update memory (project_session_handoff.md with branch/commit/open work) → push → report
what landed and anything left for the owner to verify (e.g. smoke-launch if you ran
headless). Open one PR per band group above; do not merge (the owner merges — self-approval
is blocked).
````
