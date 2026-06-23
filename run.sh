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

# Absolute path of the main worktree for any checkout dir.
_main_repo() { dirname "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; }

# Echo a usable python: the checkout's own venv, else the main worktree's venv.
resolve_py() {
    local base="$1" main
    if [ -x "$base/venv/bin/python" ]; then printf '%s\n' "$base/venv/bin/python"; return 0; fi
    main="$(_main_repo "$base")"
    if [ -n "$main" ] && [ -x "$main/venv/bin/python" ]; then printf '%s\n' "$main/venv/bin/python"; return 0; fi
    return 1
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
