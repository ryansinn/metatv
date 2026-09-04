# repo_python.sh — resolve the shared main repo and a usable python, once.
#
# SOURCED, never executed directly: `source "$(dirname "${BASH_SOURCE[0]}")/repo_python.sh"`.
# Defines exactly two functions, moved verbatim out of scripts/verify_pr.sh
# (which had the correct answer first) so every other script and the
# pre-push hook share ONE copy instead of re-deriving it:
#
#   _main_repo <checkout-dir>   Absolute path of the shared main worktree.
#   resolve_py <checkout-dir>   Echo a usable python: the checkout's own
#                                venv, else the main worktree's venv.
#                                Returns 1 (echoes nothing) if neither exists.
#
# GATE-7: .githooks/pre-push and scripts/pytest_verdict.sh used to hardcode
# `PY="venv/bin/python"` relative to CWD, which is exit-127-wrong the moment
# CWD is a git worktree without its own venv symlink — cost two blocked
# pushes on 2026-09-03. Every caller now goes through resolve_py() instead.

# Absolute path of the main worktree for any checkout dir (mirrors run.sh).
_main_repo() { dirname "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; }

# Echo a usable python: the checkout's own venv, else the main worktree's venv.
# Generic for any linked-worktree Python repo (metatv runs from source, so a
# linked worktree can borrow the main venv's identical interpreter).
resolve_py() {
    local base="$1" main
    if [ -x "$base/venv/bin/python" ]; then printf '%s\n' "$base/venv/bin/python"; return 0; fi
    main="$(_main_repo "$base")"
    if [ -n "$main" ] && [ -x "$main/venv/bin/python" ]; then printf '%s\n' "$main/venv/bin/python"; return 0; fi
    return 1
}
