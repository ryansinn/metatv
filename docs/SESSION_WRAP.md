# Session Wrap SOP

Triggered from [CLAUDE.md](../CLAUDE.md) on "let's wrap up" / "wrap this session". Do all of the following in order:

1. **Tests** — `venv/bin/python -m pytest tests/ -x -q`; confirm all pass. If new behavior was added, note missing coverage in the FILTERING_DESIGN / ROADMAP test-coverage sections.
2. **Commit** everything uncommitted with a descriptive message; never leave working changes untracked.
3. **Docs** — update any now-stale design/reference docs: `docs/FILTERING_DESIGN.md`, `ROADMAP.md`, `docs/UI_UX_GUIDELINES.md` (if interaction patterns changed).
4. **CLAUDE.md** — update if new critical rules, architecture patterns, or file locations were established.
5. **Memory** — refresh `~/.claude/projects/…/memory/`: `project_session_handoff.md` (branch/commit/open work) and relevant pattern/decision files.
6. **Push** — `git push origin main`; confirm no errors.
7. **Confirm** — report what was committed, pushed, and written to memory; call out anything that couldn't be done and why.
