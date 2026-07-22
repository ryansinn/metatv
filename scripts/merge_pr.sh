#!/usr/bin/env bash
# merge_pr.sh — the full PR merge sequence as one command (project-agnostic).
#
# Chains the sibling scripts so a merge can't skip the staleness/conflict gate:
#   1. Preconditions — gh present; PR exists and is OPEN (else exit 2).
#   2. Gate (default ON) — run verify_pr.sh <N>, which tests the MERGE RESULT
#      against origin/<base> and goes RED on conflict; require VERDICT: GREEN.
#      --skip-verify bypasses (prints a warning).
#   3. Merge — gh pr merge <N> --<MERGE_METHOD> --delete-branch. The known
#      non-fatal "local branch held by a worktree" delete failure is tolerated
#      (prune handles it); any other failure is fatal. Merged state is then
#      confirmed via gh before continuing.
#   4. Trunk — from the main worktree, git pull --ff-only origin <base>; a
#      non-fast-forward means local <base> diverged: stop before pruning (exit 1).
#   5. Cleanup — run prune_merged.sh (Bug-3-safe around live agent worktrees).
#      --keep-worktree skips this.
#   6. Summary — PR#, merge sha, verify verdict used, prune counts.
#
# Config knobs (via repo-root .devscripts.conf, all optional):
#   MERGE_METHOD  gh merge method: squash | merge | rebase. Default: squash.
#   BASE_BRANCH   Trunk to pull. Unset → auto from origin/HEAD, else main.
#
#   scripts/merge_pr.sh <PR#>                    Verify, merge (squash), prune.
#   scripts/merge_pr.sh <PR#> --skip-verify      Merge without re-verifying.
#   scripts/merge_pr.sh <PR#> --keep-worktree    Merge but skip the prune step.
#   scripts/merge_pr.sh -h | --help              Show this help.
#
# _main_repo mirrors run.sh.

set -u

usage() {
    cat <<'EOF'
merge_pr.sh — verify → merge → prune, as one command (project-agnostic)

USAGE
  scripts/merge_pr.sh <PR#>                  Gate (verify_pr.sh, require GREEN),
                                             then merge and prune.
  scripts/merge_pr.sh <PR#> --skip-verify    Skip the verify gate (warns).
  scripts/merge_pr.sh <PR#> --keep-worktree  Skip the final prune step.
  scripts/merge_pr.sh -h | --help            Show this help and exit.

CONFIG (repo-root .devscripts.conf, all optional)
  MERGE_METHOD  gh merge method: squash | merge | rebase. Default: squash.
  BASE_BRANCH   Trunk to pull; unset → auto from origin/HEAD, else main.

EXIT CODES
  0  Merged, trunk fast-forwarded, cleanup done.
  1  Verify RED, a fatal merge failure, or local <base> could not fast-forward.
  2  The PR is not OPEN (merged/closed) — refused.
EOF
}

# ── argument parsing ──────────────────────────────────────────────────────────
SKIP_VERIFY=0
KEEP_WT=0
PR=""
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --skip-verify) SKIP_VERIFY=1 ;;
        --keep-worktree) KEEP_WT=1 ;;
        ''|*[!0-9]*)
            echo "merge_pr.sh: unexpected argument '$arg'" >&2; usage >&2; exit 64 ;;
        *) PR="$arg" ;;
    esac
done
if [ -z "$PR" ]; then
    echo "merge_pr.sh: a PR number is required." >&2; usage >&2; exit 64
fi

command -v gh >/dev/null 2>&1 || { echo "merge_pr.sh: the gh CLI is required." >&2; exit 1; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Absolute path of the main worktree for any checkout dir (mirrors run.sh).
_main_repo() { dirname "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; }

main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "merge_pr.sh: not inside a git repo." >&2; exit 1; }
script_wt="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

# ── load config: repo-root .devscripts.conf → defaults ────────────────────────
conf="${script_wt:-$main}/.devscripts.conf"
if [ -f "$conf" ]; then
    echo "merge_pr.sh: sourcing $conf"
    # shellcheck source=/dev/null
    . "$conf"
fi
MERGE_METHOD="${MERGE_METHOD:-squash}"
case "$MERGE_METHOD" in
    squash|merge|rebase) ;;
    *) echo "merge_pr.sh: invalid MERGE_METHOD '$MERGE_METHOD' (use squash|merge|rebase)." >&2; exit 64 ;;
esac
if [ -n "${BASE_BRANCH:-}" ]; then
    base_branch="$BASE_BRANCH"
else
    base_branch="$(git -C "$main" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)"
    base_branch="${base_branch#origin/}"
    [ -n "$base_branch" ] || base_branch="main"
fi

# ── 1. preconditions: PR must exist and be OPEN ───────────────────────────────
state=""
state="$(gh pr view "$PR" --json state --jq '.state' 2>/dev/null)"
if [ -z "$state" ]; then
    echo "merge_pr.sh: couldn't fetch PR #$PR (does it exist / is gh authed?)." >&2
    exit 1
fi
if [ "$state" != "OPEN" ]; then
    echo "merge_pr.sh: PR #$PR is $state, not OPEN — refusing to merge." >&2
    exit 2
fi
echo "merge_pr.sh: PR #$PR is OPEN — method=$MERGE_METHOD  base=$base_branch"

# ── 2. staleness / conflict gate (verify_pr.sh) ───────────────────────────────
verdict_used=""
if [ "$SKIP_VERIFY" = 1 ]; then
    echo "merge_pr.sh: WARNING — verification skipped (--skip-verify); merging without re-testing the merge result."
    verdict_used="(skipped — --skip-verify)"
else
    echo
    echo "── gate: scripts/verify_pr.sh $PR ──"
    verify_log="$(mktemp "${TMPDIR:-/tmp}/merge_pr.${PR}.verify.XXXXXX.log")"
    "$SCRIPT_DIR/verify_pr.sh" "$PR" 2>&1 | tee "$verify_log"
    verify_rc="${PIPESTATUS[0]}"
    verdict_used="$(grep -E '^VERDICT:' "$verify_log" | tail -n1)"
    rm -f "$verify_log"
    if [ "$verify_rc" -ne 0 ] || ! printf '%s' "$verdict_used" | grep -q '^VERDICT: GREEN'; then
        echo
        echo "merge_pr.sh: gate did not pass — aborting merge."
        echo "  ${verdict_used:-<no VERDICT line; verify_pr.sh exited $verify_rc>}"
        exit 1
    fi
fi

# ── 3. merge ──────────────────────────────────────────────────────────────────
echo
echo "── merge: gh pr merge $PR --$MERGE_METHOD --delete-branch ──"
merge_out="$(gh pr merge "$PR" --"$MERGE_METHOD" --delete-branch 2>&1)"
merge_rc=$?
printf '%s\n' "$merge_out"
if [ "$merge_rc" -ne 0 ]; then
    # Tolerated: remote merge succeeded but the LOCAL branch can't be deleted
    # because a worktree holds it (e.g. an agent's checkout). prune handles it.
    if printf '%s' "$merge_out" | grep -qiE 'failed to delete local branch|used by worktree|checked out at'; then
        echo "merge_pr.sh: local branch held by worktree (prune will handle it) — continuing."
    else
        echo "merge_pr.sh: merge failed (see above) — aborting." >&2
        exit 1
    fi
fi

# Confirm the merge actually landed before touching trunk.
post_state="$(gh pr view "$PR" --json state --jq '.state' 2>/dev/null)"
if [ "$post_state" != "MERGED" ]; then
    echo "merge_pr.sh: PR #$PR is '$post_state' after merge attempt (expected MERGED) — aborting." >&2
    exit 1
fi
echo "merge_pr.sh: PR #$PR is MERGED."

# ── 4. update local trunk (fast-forward only) ─────────────────────────────────
echo
echo "── trunk: fast-forward local $base_branch from origin ──"
cur="$(git -C "$main" symbolic-ref --short -q HEAD || echo '(detached)')"
if [ "$cur" = "$base_branch" ]; then
    if git -C "$main" pull --ff-only origin "$base_branch"; then
        :
    else
        echo "merge_pr.sh: local '$base_branch' could not fast-forward — it has diverged from origin." >&2
        echo "  Stopping before prune; reconcile the divergence by hand." >&2
        exit 1
    fi
else
    echo "merge_pr.sh: main worktree is on '$cur', not '$base_branch' — updating origin refs only (skipping local FF)."
    git -C "$main" fetch origin -q "$base_branch" || true
fi

# ── 5. cleanup (prune_merged.sh) ──────────────────────────────────────────────
prune_summary="(skipped — --keep-worktree)"
if [ "$KEEP_WT" = 1 ]; then
    echo
    echo "merge_pr.sh: --keep-worktree — skipping prune."
else
    echo
    echo "── cleanup: scripts/prune_merged.sh ──"
    prune_log="$(mktemp "${TMPDIR:-/tmp}/merge_pr.${PR}.prune.XXXXXX.log")"
    "$SCRIPT_DIR/prune_merged.sh" 2>&1 | tee "$prune_log"
    prune_summary="$(grep -E '^(removed|kept-unmerged|kept-active|skipped-dirty|kept-protected) *:' "$prune_log" \
        | sed -E 's/ +:/:/; s/[[:space:]]*$//' | paste -sd' ' -)"
    rm -f "$prune_log"
    [ -n "$prune_summary" ] || prune_summary="(no summary parsed)"
fi

# ── 6. final summary ──────────────────────────────────────────────────────────
merge_sha="$(git -C "$main" log -1 --oneline 2>/dev/null)"
echo
echo "── merge_pr.sh summary ──"
echo "PR:              #$PR ($MERGE_METHOD merged)"
echo "verify:          ${verdict_used:-<none>}"
echo "trunk ($base_branch): $merge_sha"
echo "prune:           $prune_summary"
