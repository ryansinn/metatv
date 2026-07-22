# Dev / manager scripts

Project-agnostic tooling that turns two repetitive multi-step Bash sequences
into one command each. Both are self-contained and configured through an
optional repo-root `.devscripts.conf` — no project details are hardcoded.

## `verify_pr.sh <PR#> [--keep]`

Full-suite PR gate. Resolves the PR, refreshes its `<main-repo>-pr-<PR#>`
worktree, runs the project's whole test suite there, and prints a `VERDICT:
GREEN/RED` line (exit 0 iff GREEN). A non-OPEN PR exits 2; a missing/unparseable
pytest summary is RED, never GREEN. `--keep` retains the worktree afterwards.

## `prune_merged.sh [--dry-run] [--force]`

Safe cleanup. Removes worktrees (under `.claude/worktrees/` and `<main>-pr-*`
siblings) and local branches that are merged into the trunk — via ancestry or a
gh MERGED/CLOSED PR, covering squash-merges. Never touches the trunk, the
current worktree, protected patterns, or anything unmerged (reported as `KEPT
(unmerged)`). Dirty worktrees are skipped unless their only change is an
untracked `venv/`; `--force` overrides. `--dry-run` shows every action and
changes nothing.

## Configuration — `.devscripts.conf`

Resolution order for anything project-specific: **(a)** a repo-root
`.devscripts.conf` (plain `KEY=VALUE` bash, sourced if present) → **(b)**
auto-detection → **(c)** safe defaults. Knobs (all optional):

| Knob | Meaning | Default / auto |
|---|---|---|
| `TEST_CMD` | Full-suite command | Auto-detect: Python (`tests/`, `pyproject.toml`, or `pytest.ini`) → `<borrowed-venv-python> -m pytest tests/ -q`; `package.json` → `npm test --silent`; `Cargo.toml` → `cargo test`; `go.mod` → `go test ./...`; else error |
| `PROTECTED_BRANCHES` | Extra never-prune globs, **appended** to defaults | `main master develop` |
| `BASE_BRANCH` | Trunk to diff / measure "merged" against | Auto from `origin/HEAD`, else `main` |

Verdict logic: a pytest `TEST_CMD` uses the strict summary parse
(missing/unparseable summary = RED, any failed/error = RED); any other runner
uses its exit code. GREEN is only ever claimed after the command runs to
completion.

## Deploy to another project

1. Copy `scripts/verify_pr.sh` and `scripts/prune_merged.sh` into the target
   repo (e.g. its own `scripts/`).
2. Optionally add a repo-root `.devscripts.conf` (see the table above). If the
   project is a standard Python/Node/Rust/Go layout you can skip it — the
   scripts auto-detect. Set `TEST_CMD` explicitly for anything non-standard.
3. Run: `scripts/verify_pr.sh <PR#>` and `scripts/prune_merged.sh --dry-run`.

**Requirements:** `bash`, `git`, and the GitHub CLI `gh` (authenticated).
`verify_pr.sh` additionally needs whatever `TEST_CMD` invokes (e.g. a Python
venv, `npm`, `cargo`, `go`).
