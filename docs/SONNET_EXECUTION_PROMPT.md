# Sonnet Execution Prompt — REFACTOR_PLAN

Paste the block below into a fresh Claude Sonnet 4.6 session (with tools, in this repo) to
execute `docs/REFACTOR_PLAN.md`. It travels with the repo so the plan and its execution
brief stay together.

---

````text
You are an implementing engineer working in the MetaTV repository (Python/PyQt6 IPTV client).
Your job is to EXECUTE the refactor plan in `docs/REFACTOR_PLAN.md`, end to end, with
discipline. Do not redesign the plan — implement it. Where the plan gives you a target,
hit it; where reality has drifted from the plan, say so and adapt.

────────────────────────────────────────────────────────
READ FIRST (before writing any code)
────────────────────────────────────────────────────────
1. `docs/REFACTOR_PLAN.md` — the task list (P0 → P1 → P2 → P3 → P4) plus an Appendix of
   structural rule-fix tasks (session_scope, JSONEncoded TypeDecorator, icons.py registry,
   tz-aware EPG storage, closeEvent cleanup registry, SQLite WAL).
2. `CLAUDE.md` — the project's Critical Rules. These OVERRIDE default behavior; follow them
   exactly. Note the `<!-- target -->` comments on some rules: they mark a rule whose
   root-cause fix is a task in the plan. When you implement that fix, update the rule's
   text AND delete its `<!-- target -->` note IN THE SAME COMMIT.
3. The "Session Wrap SOP" and "Coding Standards" sections of `CLAUDE.md`.

Confirm your understanding by listing, in order, the tasks you intend to do and any whose
premise no longer matches the current code (these may have been fixed since the plan was
written — verify each task against `git grep`/the file before starting it).

────────────────────────────────────────────────────────
EXECUTION ORDER & GROUPING
────────────────────────────────────────────────────────
Do the work in this order. Each numbered item is its own commit on a feature branch
(NOT main). Group commits into reviewable PRs by priority band (one PR per band is fine;
split P3 into one PR per file if it gets large).

  Band 1 — P0 correctness bugs:  P0-1, P0-2, P0-3, P0-4
  Band 2 — P1 dedup:             P1-1 … P1-5
  Band 3 — structural rule fixes (Appendix): session_scope(), JSONEncoded TypeDecorator,
           icons.py registry, closeEvent cleanup registry, SQLite WAL, tz-aware EPG.
           (Do these AFTER P0/P1 — several supersede band-aid rules and touch many sites.)
  Band 4 — P2 inline styles → theme.py (one file per commit, start with epg_view.py)
  Band 5 — P3 file decomposition (mechanical moves only; sidebar_sections & filter_panel
           first, main_window.py last)
  Band 6 — P4 leftovers

Rationale for putting structural fixes (Band 3) before the cosmetic P2/P3 work: they remove
whole bug classes and change conventions, so landing them early means later work is written
the new way once.

────────────────────────────────────────────────────────
PER-TASK PROTOCOL (non-negotiable)
────────────────────────────────────────────────────────
For EVERY task:
  a. Re-read the relevant code. Confirm the plan's premise still holds. If it's already
     fixed or the line numbers moved, note it and adapt — don't blindly apply.
  b. TEST DISCIPLINE:
       • P0 bug fixes: write a regression test that FAILS on current code and PASSES after
         your fix. Put the before/after result in the commit message. (P0-2's
         `test_epg_browse_timezone.py` is the flagship — it must fail before, pass after.)
       • Pure refactors (P1/P2/P3 and the structural fixes): write a CHARACTERIZATION test
         FIRST that pins current behavior, see it green on the unchanged code, THEN
         refactor, then see it green again. A refactor with no guarding test is not allowed.
  c. Make the change. Match surrounding code style, naming, comment density.
  d. Run: `venv/bin/python -m pytest tests/ -x -q` — must be all green.
  e. For P3 file moves and any UI-visible change, smoke-launch once: `./run.sh`
     (or `venv/bin/python -m metatv`) and confirm the app starts and the affected view
     renders. Report what you observed.
  f. Commit (see message format below). One task per commit.

────────────────────────────────────────────────────────
HARD CONSTRAINTS
────────────────────────────────────────────────────────
• Follow every Critical Rule in CLAUDE.md. Do not introduce a new violation while fixing an
  old one (e.g. while extracting code, keep sessions on try/finally-or-session_scope, icons
  from the registry, styles dedup'd, threads shut down).
• NO behavior change except where a P0 task explicitly fixes a bug. Refactors must be
  behavior-preserving.
• Do NOT split a file AND rewrite its logic in the same commit — move verbatim first
  (imports fixed), refactor logic in a separate commit. Keeps regressions bisectable.
• Do NOT tighten the content-dedup heuristics (see CLAUDE.md § "Content Dedup — Known
  Compromises"); they are deliberate. Leave them unless a task explicitly says otherwise.
• Structural fixes that supersede a rule MUST update CLAUDE.md's rule text + drop the
  `<!-- target -->` note in the same commit.
• Keep all new tests offline and deterministic: no real network, no real provider, no mpv.
  Use the in-memory SQLite + fixtures in `tests/conftest.py` (`db_session`, `repo`,
  `make_channel`). pytest-qt 4.5.0 is available for widget tests. Add the `seed_epg` and
  `frozen_local_tz` fixtures the plan calls for.
• Work on a branch; never commit directly to main. End every commit message with:
      Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
  End every PR body with:
      🤖 Generated with [Claude Code](https://claude.com/claude-code)
• Commit/push only the work; do not push unrelated changes. Do not delete or overwrite files
  you didn't create without first inspecting them.

────────────────────────────────────────────────────────
WHEN YOU'RE BLOCKED OR UNSURE
────────────────────────────────────────────────────────
• If a task's premise is gone (already fixed): skip it, note it in your progress report, move on.
• If two reasonable implementations exist and the plan doesn't specify: pick the one most
  consistent with existing code and the Critical Rules, state your choice in the commit, proceed.
• If a change would require touching the DB schema or a public interface in a way the plan
  didn't anticipate (e.g. tz-aware EPG storage may need a migration): STOP, write up the
  options and the blast radius, and ask before proceeding.

────────────────────────────────────────────────────────
COMMIT MESSAGE FORMAT
────────────────────────────────────────────────────────
  <type>(<scope>): <imperative summary>      # e.g. fix(epg): correct browse date timezone window

  - what changed and why (tie to the plan task id, e.g. "REFACTOR_PLAN P0-2")
  - test: <regression/characterization test added; before→after result for P0>

  Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>

────────────────────────────────────────────────────────
WHEN A BAND IS COMPLETE
────────────────────────────────────────────────────────
• Run the full suite once more (`venv/bin/python -m pytest tests/ -q`).
• Update docs that are now stale: tick items in `ROADMAP.md` "Code Health / Refactor",
  update the implementation-status / test-coverage sections of `docs/FILTERING_DESIGN.md`
  if touched, and the appendix Status note in `docs/REFACTOR_PLAN.md`.
• Update persistent memory under `~/.claude/projects/.../memory/`: refresh
  `project_session_handoff.md` (branch/commit/what's done/what's next) and the filter/test
  memory files if the suite grew.
• Open (or update) the PR for that band with a summary of tasks completed and tests added.
• Give me a short progress report: tasks done, tests added, anything skipped and why,
  anything that needs my decision.

────────────────────────────────────────────────────────
DEFINITION OF DONE (whole effort)
────────────────────────────────────────────────────────
• All plan tasks implemented or explicitly skipped-with-reason.
• `venv/bin/python -m pytest tests/ -q` green; P0 regressions demonstrably guard their bugs.
• Core engines (content_dedup, preference_engine, discovery_engine, epg_utils, epg repo,
  channel_name_utils, special_content) have the new unit tests from the plan's "Tests to
  write" section.
• No file over the 1000-line rule remains (main_window may need 2–3 passes).
• CLAUDE.md rules and their `<!-- target -->` notes are consistent with the code that now exists.
• App launches and the touched views render.

Start by reading `docs/REFACTOR_PLAN.md` and `CLAUDE.md`, then give me your ordered task list
with premise-verification notes before you write any code.
````
