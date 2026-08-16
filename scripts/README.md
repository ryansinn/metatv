# Dev / manager scripts

Project-agnostic tooling that turns repetitive multi-step Bash sequences into one
command each. All are self-contained and configured through an optional repo-root
`.devscripts.conf` — no project details are hardcoded.

**Manager workflow:** `merge_pr.sh` chains the other two — it runs `verify_pr.sh`
as a gate, merges, updates trunk, then runs `prune_merged.sh`. So the day-to-day
loop is just `verify_pr.sh <N>` while a PR is in review and `merge_pr.sh <N>` to
land it (verify + prune happen automatically inside).

## `verify_pr.sh <PR#> [--keep]`

Full-suite PR gate. Resolves the PR, refreshes its `<main-repo>-pr-<PR#>`
worktree, **merges `origin/<base>` into it and tests the MERGE RESULT** (what will
actually land — a branch that no longer merges cleanly is RED with the conflict
list, before any test runs), and prints a `VERDICT: GREEN/RED` line (exit 0 iff
GREEN). A non-OPEN PR exits 2; a missing/unparseable pytest summary is RED, never
GREEN. It also reports whether the branch was behind base (`merged N commits …` /
`up to date`). `--keep` retains the worktree afterwards.

## `merge_pr.sh <PR#> [--skip-verify] [--keep-worktree]`

The full merge sequence as one command: (1) refuse a non-OPEN PR (exit 2);
(2) gate on `verify_pr.sh <N>` and require `VERDICT: GREEN` — so a stale/conflicting
branch can't be merged (`--skip-verify` bypasses with a warning); (3)
`gh pr merge --<MERGE_METHOD> --delete-branch`, tolerating the known "local branch
held by a worktree" delete failure (prune handles it) but treating any other
failure as fatal, then confirming `MERGED` via gh; (4) fast-forward local trunk
(`git pull --ff-only origin <base>`; a non-FF divergence stops before pruning,
exit 1); (5) run `prune_merged.sh` (`--keep-worktree` skips it); (6) print a
summary (PR#, merge sha, verdict used, prune counts).

## `prune_merged.sh [--dry-run] [--force]`

Safe cleanup. Removes worktrees (under `.claude/worktrees/` and `<main>-pr-*`
siblings) and local branches merged into the trunk. **An attached worktree is
pruned only on merged/closed-PR evidence** (gh, or the `-pr-N` convention) —
ancestry alone is *not* treated as merged, because a freshly created agent branch
has no commits of its own and its tip is trivially an ancestor of trunk; those are
reported `KEPT (no unique commits — possibly active agent)` so a live agent is
never removed mid-task. Local branches *without* a worktree are still deletable by
ancestry (orphaned bookkeeping) or a gh MERGED PR (squash-merge). Never touches
the trunk, the current worktree, protected patterns, or anything unmerged. Dirty
worktrees are skipped unless their only change is an untracked `venv/` (`?? venv`
or `?? venv/`); `--force` overrides. `--dry-run` shows every action, changes
nothing, and labels itself as such (a real run never says "dry-run").

## `ship_batch.sh <version> <PR#> [<PR#>...] [--dry-run]`

Maintainer release tool (MetaTV-specific). Batches multiple staged PRs into a
release cut: (1) verifies each PR is OPEN; (2) creates a temp worktree, fetches
and merges PRs sequentially (abort on conflict); (3) applies the release chore
(bumps `__version__` in `metatv/__init__.py`, updates `version="..."` in added
What's New entries); (4) runs the full test gate (`pytest tests/ -q`); on GREEN,
(5) merges each PR via `gh pr merge --squash`, cherry-picks the chore commit
onto fresh origin/main, and pushes; (6) tags `v<version>` and publishes a
release (polls for CI completion, prints release URL + asset list); (7) cleans
up temp worktrees. No What's New entry for this tooling change itself. `--dry-run`
stops after step 4 (gate + conflict detection) and prints `WOULD-SHIP` on GREEN
(safe to verify the final gate before committing to the merge).

## `rebaseline_code_health.py`

Regenerates `tests/code_health_baseline.json`, the debt-ratchet baseline
enforced by `tests/test_code_health_ratchet.py` (see docs/AUDIT_2026-08-16.md
for why it exists: every audit finding shipped with a mechanical guard stayed
at zero two months later; every finding left to discipline alone regressed).
For every `*.py` under `metatv/`, the allowed size is `max(1000,
baseline.get(path, 0))` — a file may shrink freely but never grow past its
recorded baseline (or the flat 1000-line floor for a file not yet in the
baseline); a single `get_session()` call count is ratcheted the same way.
Run as `venv/bin/python scripts/rebaseline_code_health.py`; it recomputes both
numbers, rewrites the baseline, and prints a diff of what changed. Run it
**only** for a deliberate, reviewed increase (e.g. a split that leaves a file
still over 1000 but smaller) — never to silence a red guard for an accidental
regression.

## Configuration — `.devscripts.conf`

Resolution order for anything project-specific: **(a)** a repo-root
`.devscripts.conf` (plain `KEY=VALUE` bash, sourced if present) → **(b)**
auto-detection → **(c)** safe defaults. Knobs (all optional):

| Knob | Meaning | Default / auto |
|---|---|---|
| `TEST_CMD` | Full-suite command for `verify_pr.sh` | Auto-detect: Python (`tests/`, `pyproject.toml`, or `pytest.ini`) → `<borrowed-venv-python> -m pytest tests/ -q`; `package.json` → `npm test --silent`; `Cargo.toml` → `cargo test`; `go.mod` → `go test ./...`; else error |
| `PROTECTED_BRANCHES` | Extra never-prune globs, **appended** to defaults | `main master develop` |
| `BASE_BRANCH` | Trunk to diff / merge against / pull | Auto from `origin/HEAD`, else `main` |
| `MERGE_METHOD` | `gh pr merge` method for `merge_pr.sh` | `squash` |

Verdict logic: a pytest `TEST_CMD` uses the strict summary parse
(missing/unparseable summary = RED, any failed/error = RED); any other runner
uses its exit code. GREEN is only ever claimed after the command runs to
completion.

## Deploy to another project

1. Copy the scripts you want (`verify_pr.sh`, `prune_merged.sh`, `merge_pr.sh`)
   into the target repo (e.g. its own `scripts/`).
2. Optionally add a repo-root `.devscripts.conf` (see the table above). A standard
   Python/Node/Rust/Go layout needs none — the scripts auto-detect. Set `TEST_CMD`
   explicitly for anything non-standard.
3. Run: `scripts/verify_pr.sh <PR#>` and `scripts/prune_merged.sh --dry-run`.

**Requirements:** `bash`, `git`, and the GitHub CLI `gh` (authenticated).
`verify_pr.sh` additionally needs whatever `TEST_CMD` invokes (e.g. a Python
venv, `npm`, `cargo`, `go`).
