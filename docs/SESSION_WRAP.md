# Session Wrap SOP

Triggered from [CLAUDE.md](../CLAUDE.md) on "let's wrap up" / "wrap this session". Do all of the
following in order.

> **Why steps 3 and 4 are mechanical and blocking.** Ten releases (v0.16.0 → v0.23.0) shipped 59
> What's New entries without a single ROADMAP.md checkbox being ticked, and three items were recorded
> in project memory as *shipped* that had never been written at all. The old step 3 read "update any
> now-stale docs" — a judgment call with no mechanism, so skipping it was indistinguishable from doing
> it. Steps 3 and 4 now each end in a command that fails loudly. Do not downgrade them back to prose.

1. **Tests** — `venv/bin/python -m pytest tests/ -x -q`; confirm all pass. Read the FULL summary line
   and confirm `0 failed` — never trust a truncated tail. If new behavior was added, note missing
   coverage in the FILTERING_DESIGN / ROADMAP test-coverage sections.

2. **Commit** everything uncommitted with a descriptive message; never leave working changes
   untracked.

3. **Roadmap reconciliation (blocking, mechanical).** Run:

       venv/bin/python scripts/roadmap_audit.py

   It lists every What's New entry that shipped since ROADMAP.md was last reconciled and exits
   non-zero while any remain. For each one, edit ROADMAP.md: tick the item `[x]` with
   `SHIPPED vX.Y.Z (#PR)`, downgrade it to `[~]` with the specific remainder spelled out, or add the
   line if the work wasn't on the roadmap at all. Then:

       venv/bin/python scripts/roadmap_audit.py --accept

   and commit the watermark **together with** the ROADMAP.md edit it certifies. `--accept` is not a
   way to silence the report — bumping it without doing the edit is the exact failure this replaces.

4. **Release-claims audit (blocking — the reverse check).** Ticking boxes only catches work that
   shipped. The costlier failure is the opposite: a wave/release scope list recording items as done
   that were never built. Three Wave 7 items ("Similar Content sibling", "preference-scored Explore
   columns", "Discover pre-warm setting") were logged as the spec-locked build list and went into
   memory as fact; none of the three existed in code. Nobody noticed for two releases.

   Before declaring any wave or release complete, run:

       venv/bin/python scripts/roadmap_audit.py --version X.Y.Z

   and map the release's **claimed** scope against that list, item by item. CLAUDE.md already
   requires a What's New entry for every PR with user-visible behavior, so:

   > **A claimed item with no What's New entry did not ship.** Record it as NOT BUILT.

   Where an item genuinely shipped without a user-visible entry (a refactor, dev tooling), cite a
   concrete code anchor — `file.py:line` — not a plan reference. A wave's scope list is a statement
   of intent, never evidence of delivery. Verify with several naming patterns before concluding
   something is missing; one grep for the name you expected is not a search.

5. **Docs** — update any other now-stale design/reference docs: `docs/FILTERING_DESIGN.md`,
   `docs/UI_UX_GUIDELINES.md` (if interaction patterns changed), `docs/METADATA_SYSTEM.md`.

6. **CLAUDE.md** — update if new critical rules, architecture patterns, or file locations were
   established.

7. **Memory** — refresh `~/.claude/projects/…/memory/`: `project_session_handoff.md` (branch/commit/
   open work) and relevant pattern/decision files. **Anything written to memory as "shipped" carries
   its evidence** — a What's New id or a `file.py:line` anchor. Never promote a plan, a brief, or an
   agent's self-report into a memory of delivered work; that is how the three phantom Wave 7 items
   became "fact".

8. **Push** — `git push origin main`; confirm no errors.

9. **Confirm** — report what was committed, pushed, and written to memory; call out anything that
   couldn't be done and why. State the roadmap watermark the session ended on.
