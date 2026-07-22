#!/usr/bin/env bash
# verify_pr.sh — a project-agnostic PR QA gate as one command.
#
# Resolves PR #<N>, (re)creates the SAME <main-repo>-pr-<N> sibling worktree
# convention run.sh uses (so a paired launcher can reuse the checkout), runs
# the project's FULL test suite against it, and prints an unmissable GREEN/RED
# verdict. Exit code is 0 iff GREEN.
#
# PORTABLE: nothing project-specific is hardcoded. Configuration resolves as
#   (a) a repo-root `.devscripts.conf` (plain KEY=VALUE bash, sourced if present)
#   (b) auto-detection, then (c) safe defaults.
# Copy this file (and prune_merged.sh) into any git+gh repo; optionally add a
# `.devscripts.conf`. See scripts/README.md.
#
#   scripts/verify_pr.sh <PR#>          Verify an OPEN PR, then self-clean the
#                                       worktree (kept only if it went dirty).
#   scripts/verify_pr.sh <PR#> --keep   Keep the worktree afterwards.
#   scripts/verify_pr.sh -h | --help    Show this help and exit.
#
# Config knobs (via .devscripts.conf, all optional):
#   TEST_CMD   Full-suite command. Unset → auto-detect: Python (tests/ dir or
#              pyproject.toml/pytest.ini) → "<borrowed-venv-python> -m pytest
#              tests/ -q"; package.json → "npm test --silent"; Cargo.toml →
#              "cargo test"; go.mod → "go test ./..."; else error.
#   BASE_BRANCH  Trunk to diff against. Unset → auto from origin/HEAD, else main.
#
# Verdict: a pytest TEST_CMD uses the strict summary parse (missing/unparseable
# summary = RED, any failed/error = RED — never a truncated tail read as pass);
# any other runner uses its exit code (0 = GREEN). Either way GREEN is claimed
# only after the command has run to completion.
#
# Guards two real past incidents: a non-OPEN PR exits 2 (merged/closed work is
# never "verified"); a missing/unparseable summary is RED, never GREEN.
#
# _main_repo / resolve_py mirror run.sh (generic for any linked-worktree repo).

set -u

usage() {
    cat <<'EOF'
verify_pr.sh — full-suite PR gate with a GREEN/RED verdict (project-agnostic)

USAGE
  scripts/verify_pr.sh <PR#>          Verify an OPEN PR: refresh its worktree
                                      (<main-repo>-pr-<PR#>), run the full test
                                      suite, print VERDICT: GREEN/RED. Exit 0
                                      iff GREEN.
  scripts/verify_pr.sh <PR#> --keep   As above, but keep the worktree after
                                      verifying.
  scripts/verify_pr.sh -h | --help    Show this help and exit.

CONFIG (repo-root .devscripts.conf, all optional)
  TEST_CMD      Full-suite command; unset → auto-detected per project type.
  BASE_BRANCH   Trunk to diff against; unset → auto from origin/HEAD, else main.

EXIT CODES
  0  GREEN — suite passed.
  1  RED   — failures/errors, unparseable summary, or missing config.
  2  The PR is not OPEN (merged/closed) — refused, not verified.
EOF
}

# ── argument parsing ──────────────────────────────────────────────────────────
KEEP=0
PR=""
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --keep) KEEP=1 ;;
        ''|*[!0-9]*)
            echo "verify_pr.sh: unexpected argument '$arg'" >&2
            usage >&2
            exit 64 ;;
        *) PR="$arg" ;;
    esac
done
if [ -z "$PR" ]; then
    echo "verify_pr.sh: a PR number is required." >&2
    usage >&2
    exit 64
fi

command -v gh >/dev/null 2>&1 || { echo "verify_pr.sh: the gh CLI is required." >&2; exit 1; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

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

# Auto-detect a full-suite command for a checkout dir. Echoes the command on
# success; exit 3 = Python project but no venv; exit 1 = nothing recognised.
detect_test_cmd() {
    local dir="$1" py
    if [ -d "$dir/tests" ] || [ -f "$dir/pyproject.toml" ] || [ -f "$dir/pytest.ini" ]; then
        if py="$(resolve_py "$dir")"; then
            printf '%s -m pytest tests/ -q\n' "$py"
            return 0
        fi
        return 3
    fi
    if [ -f "$dir/package.json" ]; then printf 'npm test --silent\n'; return 0; fi
    if [ -f "$dir/Cargo.toml" ];  then printf 'cargo test\n';       return 0; fi
    if [ -f "$dir/go.mod" ];      then printf 'go test ./...\n';    return 0; fi
    return 1
}

# Resolve the trunk branch: explicit BASE_BRANCH, else origin/HEAD, else main.
resolve_base_branch() {
    local main="$1" ref
    if [ -n "${BASE_BRANCH:-}" ]; then printf '%s\n' "$BASE_BRANCH"; return; fi
    ref="$(git -C "$main" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)"
    [ -n "$ref" ] && { printf '%s\n' "${ref#origin/}"; return; }
    printf 'main\n'
}

# ── resolve the PR ────────────────────────────────────────────────────────────
state=""; branch=""; oid=""
IFS=$'\t' read -r state branch oid < <(
    gh pr view "$PR" --json state,headRefName,headRefOid \
        --jq '[.state, .headRefName, .headRefOid] | @tsv' 2>/dev/null
)
if [ -z "$state" ]; then
    echo "verify_pr.sh: couldn't fetch PR #$PR (does it exist / is gh authed?)." >&2
    exit 1
fi
echo "PR #$PR: state=$state  branch=$branch  head=${oid:0:12}"

if [ "$state" != "OPEN" ]; then
    echo "verify_pr.sh: PR #$PR is $state, not OPEN — refusing to 'verify' non-open work." >&2
    echo
    echo "VERDICT: RED — PR #$PR is $state (not OPEN)"
    exit 2
fi

# ── (re)create the shared PR worktree (mirrors run.sh exactly) ────────────────
main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "verify_pr.sh: not inside a git repo." >&2; exit 1; }
wt="${main}-pr-${PR}"

git -C "$main" fetch origin -q || true
if git -C "$main" worktree list --porcelain | grep -qx "worktree $wt"; then
    git -C "$wt" reset --hard "origin/$branch" -q       # refresh to latest push
else
    git -C "$main" worktree add -f --detach "$wt" "origin/$branch" || {
        echo "verify_pr.sh: failed to create worktree $wt" >&2; exit 1; }
fi
echo "verify_pr.sh: PR #$PR → $branch → $wt (HEAD $(git -C "$wt" rev-parse --short HEAD))"

# ── load config: repo-root .devscripts.conf → auto-detect → defaults ──────────
conf="$wt/.devscripts.conf"
if [ -f "$conf" ]; then
    echo "verify_pr.sh: sourcing $conf"
    # shellcheck source=/dev/null
    . "$conf"
fi
base_branch="$(resolve_base_branch "$main")"

# ── what changed vs the trunk ─────────────────────────────────────────────────
echo
echo "── changes vs origin/$base_branch (merge-base..HEAD) ──"
mb="$(git -C "$wt" merge-base "origin/$base_branch" HEAD 2>/dev/null || true)"
if [ -n "$mb" ]; then
    git -C "$wt" diff --stat "$mb"..HEAD || true
else
    echo "(origin/$base_branch not found — skipping diffstat)"
fi

# ── resolve TEST_CMD ──────────────────────────────────────────────────────────
cleanup_worktree() {
    if [ "$KEEP" = 1 ]; then
        echo "verify_pr.sh: kept $wt (--keep)"
    elif git -C "$main" worktree remove "$wt" 2>/dev/null; then
        echo "verify_pr.sh: removed $wt"
    else
        echo "verify_pr.sh: kept $wt (uncommitted changes) — remove with: git -C \"$main\" worktree remove --force \"$wt\""
    fi
}

if [ -z "${TEST_CMD:-}" ]; then
    if ! TEST_CMD="$(detect_test_cmd "$wt")"; then
        rc=$?
        echo >&2
        if [ "$rc" = 3 ]; then
            echo "verify_pr.sh: detected a Python project but found no venv (looked in $wt/venv and the main worktree)." >&2
        else
            echo "verify_pr.sh: couldn't auto-detect a test command — set TEST_CMD in .devscripts.conf." >&2
        fi
        cleanup_worktree
        exit 1
    fi
fi

case "$TEST_CMD" in
    *pytest*) runner="pytest" ;;
    *)        runner="generic" ;;
esac

# ── run the FULL suite (no -x / no fail-fast) ─────────────────────────────────
log=""
trap 'rm -f "${log:-}"' EXIT
log="$(mktemp "${TMPDIR:-/tmp}/verify_pr.${PR}.XXXXXX.log")"

echo
echo "── running full suite ($runner): $TEST_CMD ──"
( cd "$wt" && bash -c "$TEST_CMD" ) >"$log" 2>&1
status=$?

echo "── test output (last 15 lines) ──"
tail -n 15 "$log"

# ── verdict ───────────────────────────────────────────────────────────────────
verdict="RED"
reason=""
if [ "$runner" = "pytest" ]; then
    # The final pytest banner is the last `===...===` line. Count-anchored
    # patterns ("N failed" / "N error") avoid false hits on words like "xfailed".
    summary_line="$(grep -E '^=+.*=+$' "$log" | tail -n1)"
    if [ -z "$summary_line" ]; then
        reason="no pytest summary line found (exit $status)"
    elif printf '%s' "$summary_line" | grep -qiE '[0-9]+ (failed|error)'; then
        reason="$summary_line"
    elif [ "$status" -ne 0 ]; then
        reason="pytest exited $status — $summary_line"
    elif printf '%s' "$summary_line" | grep -qiE '[0-9]+ passed'; then
        verdict="GREEN"
        reason="$summary_line"
    else
        reason="unparseable / non-passing summary — $summary_line"
    fi
else
    if [ "$status" -eq 0 ]; then
        verdict="GREEN"
        reason="\`$TEST_CMD\` exited 0"
    else
        reason="\`$TEST_CMD\` exited $status"
    fi
fi

# ── clean up + unmissable final line ──────────────────────────────────────────
echo
cleanup_worktree
echo
echo "VERDICT: $verdict — $reason"
[ "$verdict" = "GREEN" ] && exit 0 || exit 1
