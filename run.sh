#!/usr/bin/env bash
# Launch script for MetaTV.
#
#   ./run.sh             Run THIS checkout. Uses its own venv if present,
#                        otherwise falls back to the MAIN worktree's venv — so
#                        linked git worktrees need no venv of their own.
#   ./run.sh <PR#>       Test-drive a PR: resolve PR #<PR#>'s branch, check it
#                        out into a dedicated worktree (<repo>-pr-<PR#>, created
#                        or refreshed to the latest pushed commit) and run it.
#                        The worktree is removed automatically when the app
#                        exits — unless it has uncommitted changes, then it's
#                        kept (with a hint to remove it manually).
#   ./run.sh [args...]   Extra args are forwarded to `python -m metatv`.
#
# metatv is run from source (not pip-installed), so a worktree borrowing the
# main venv's interpreter still runs ITS OWN code — the venv only supplies the
# (identical) third-party dependencies.

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

usage() {
    cat <<'EOF'
run.sh — launch MetaTV (PyQt6 IPTV client)

USAGE
  ./run.sh [ARGS...]         Run the current checkout. Borrows the main
                             worktree's venv when this checkout has none, so
                             linked git worktrees need no venv of their own.
                             ARGS are forwarded to `python -m metatv`.

  ./run.sh <PR#> [ARGS...]   Test-drive a pull request: resolve its branch,
                             check it out into a throwaway worktree
                             (<repo>-pr-<PR#>, created or hard-refreshed to the
                             latest pushed commit) and run it. The worktree is
                             removed automatically when the app exits — kept
                             only if it has uncommitted changes.

  ./run.sh -h | --help       Show this help and exit.

ENVIRONMENT
  METATV_DEV=1               Enable dev-only features (e.g. the floating
                             Testing Checklist). Inherited by `run.sh <PR#>`.

EXAMPLES
  ./run.sh                   Run the current branch.
  ./run.sh 186               Launch PR #186 in its own worktree.
  METATV_DEV=1 ./run.sh 186  Launch PR #186 with dev features on.

CLEANING UP
  A PR worktree self-cleans when the app exits (unless it has uncommitted
  changes). To deal with a leftover one by hand, from anywhere in the repo:

    git worktree list                             # see every worktree
    git worktree remove <repo>-pr-<PR#>           # remove it (must be clean)
    git worktree remove --force <repo>-pr-<PR#>   # force-remove (discards edits)
    git worktree prune                            # tidy stale bookkeeping

  <repo>-pr-<PR#> is a sibling of the main checkout, e.g.
  /home/you/Projects/metatv-pr-186.
EOF
}

# Help: `./run.sh -h` / `--help`.
case "${1:-}" in
    -h|--help|help) usage; exit 0 ;;
esac

# _main_repo / resolve_py: the single sourced copy (GATE-7) — see
# scripts/repo_python.sh.
source "$SCRIPT_DIR/scripts/repo_python.sh"

# Say so when this checkout is behind its remote, then run anyway.
#
# ./run.sh deliberately does NOT pull — it runs THIS tree, which is the whole
# point when you are testing a change. The failure mode is the silent one: a
# checkout drifts behind main and every launch quietly re-runs bugs that were
# fixed days ago. That happened over a whole evening — nine commits behind,
# repeatedly hitting a crash whose fix was already on main and already in the
# shipped build.
#
# So: report, never act. Fetching or pulling here would be worse than the
# problem, because it would change the code under someone who ran this script
# precisely to test what they have.
#
# Uses only refs already on disk (no network), so an offline or slow start
# costs nothing. Everything is guarded: outside a repo, no upstream, a detached
# HEAD, or no git at all, this prints nothing and the app starts as before.
warn_if_behind() {
    local dir="$1"
    command -v git >/dev/null 2>&1 || return 0
    git -C "$dir" rev-parse --git-dir >/dev/null 2>&1 || return 0

    local branch upstream behind ahead
    branch="$(git -C "$dir" symbolic-ref --quiet --short HEAD 2>/dev/null)" || return 0
    upstream="$(git -C "$dir" rev-parse --abbrev-ref --symbolic-full-name '@{upstream}' 2>/dev/null)" || return 0
    [ -n "$upstream" ] || return 0

    # Counted against the last fetch, so it can lag; that is fine. A stale
    # "behind" is still true, and a missed one is no worse than today.
    behind="$(git -C "$dir" rev-list --count "HEAD..$upstream" 2>/dev/null)" || return 0
    ahead="$(git -C "$dir" rev-list --count "$upstream..HEAD" 2>/dev/null)" || return 0
    [ "${behind:-0}" -gt 0 ] || return 0

    printf '\n  \033[33m!\033[0m  This checkout is %s commit(s) behind %s' "$behind" "$upstream"
    [ "${ahead:-0}" -gt 0 ] && printf ' (and %s ahead)' "$ahead"
    printf '.\n     run.sh runs THIS tree as-is and never pulls.\n'
    printf '     To catch up:  git -C %s pull --ff-only\n\n' "$dir"
}

# cd into <checkout-dir> and run metatv with the resolved interpreter.
run_dir() {
    local dir="$1"; shift
    local py
    if ! py="$(resolve_py "$dir")"; then
        echo "run.sh: no venv found (looked in $dir/venv and the main worktree)." >&2
        echo "        create one: python -m venv venv && venv/bin/pip install -r requirements.txt" >&2
        exit 1
    fi
    warn_if_behind "$dir"
    cd "$dir" || exit 1
    exec "$py" -m metatv "$@"
}

# ── ./run.sh <PR#> — launch a PR branch in its own worktree ───────────────────
if [[ "${1:-}" =~ ^[0-9]+$ ]]; then
    pr="$1"; shift
    command -v gh >/dev/null 2>&1 || { echo "run.sh: the gh CLI is required to launch a PR." >&2; exit 1; }
    branch="$(gh pr view "$pr" --json headRefName -q .headRefName 2>/dev/null)"
    [ -n "$branch" ] || { echo "run.sh: couldn't resolve a branch for PR #$pr (is gh authed?)." >&2; exit 1; }
    main="$(_main_repo "$SCRIPT_DIR")"
    wt="${main}-pr-${pr}"
    git -C "$main" fetch origin -q || true
    if git -C "$main" worktree list --porcelain | grep -qx "worktree $wt"; then
        git -C "$wt" reset --hard "origin/$branch" -q       # refresh to latest push
    else
        git -C "$main" worktree add -f --detach "$wt" "origin/$branch" || exit 1
    fi
    echo "run.sh: PR #$pr → $branch → $wt (HEAD $(git -C "$wt" rev-parse --short HEAD))" >&2
    # Run as a child (not exec) so the throwaway worktree can self-clean on exit.
    if ! py="$(resolve_py "$wt")"; then
        echo "run.sh: no venv found (looked in $wt/venv and the main worktree)." >&2
        exit 1
    fi
    ( cd "$wt" && "$py" -m metatv "$@" ); status=$?
    if git -C "$main" worktree remove "$wt" 2>/dev/null; then
        echo "run.sh: removed $wt" >&2
    else
        echo "run.sh: kept $wt (uncommitted changes) — remove with: git -C \"$main\" worktree remove --force \"$wt\"" >&2
    fi
    exit "$status"
fi

# ── default: run this checkout ────────────────────────────────────────────────
run_dir "$SCRIPT_DIR" "$@"
