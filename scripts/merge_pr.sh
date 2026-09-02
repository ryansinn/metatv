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
#   5. Batch label — run open_batch.sh --push. Safe to call on EVERY merge: it
#      bumps __version__ only when main moved since the label was opened, new
#      What's New entries exist, AND no other PR is still open against the trunk.
#      That last one is what makes it per-BATCH rather than per-PR — the label
#      names what the tester receives together, and bumping per merge would have
#      produced nine labels in one day. --no-bump skips. The step exists because
#      the bump used to live in ship_batch.sh's release chore, rolling releases
#      retired that ceremony, and 61 entries then piled up under one label.
#   6. Cleanup — run prune_merged.sh (Bug-3-safe around live agent worktrees).
#      --keep-worktree skips this.
#   7. Summary — PR#, merge sha, verify verdict used, batch label, prune counts.
#
# Config knobs (via repo-root .devscripts.conf, all optional):
#   MERGE_METHOD  gh merge method: squash | merge | rebase. Default: squash.
#   BASE_BRANCH   Trunk to pull. Unset → auto from origin/HEAD, else main.
#
#   scripts/merge_pr.sh <PR#>                    Verify, merge (squash), prune.
#   scripts/merge_pr.sh <PR#> --skip-verify      Merge without re-verifying.
#   scripts/merge_pr.sh <PR#> --auto             Queue the merge with GitHub so
#                                                it lands when checks pass. The
#                                                local verify gate still runs;
#                                                see the refusal below.
#   scripts/merge_pr.sh <PR#> --keep-worktree    Merge but skip the prune step.
#   scripts/merge_pr.sh <PR#> --no-bump          Merge without opening the next
#                                                What's New batch label.
#   scripts/merge_pr.sh <PR#> --quick            Gate with the QUICK verify
#                                                (launch smoke + this PR's own
#                                                test files) instead of the full
#                                                suite. For feature work; run the
#                                                full gate before a release.
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
  scripts/merge_pr.sh <PR#> --auto           Queue behind GitHub's auto-merge.
  scripts/merge_pr.sh <PR#> --keep-worktree  Skip the final prune step.
  scripts/merge_pr.sh <PR#> --quick         Gate with verify_pr.sh --quick:
                                            the launch smoke test plus only the
                                            test files this PR changed. Seconds
                                            instead of ~10 minutes. NOT a
                                            substitute for the full gate — run
                                            that before a release / at wrap.
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
AUTO=0
QUICK=0
KEEP_WT=0
NO_BUMP=0
PR=""
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --skip-verify) SKIP_VERIFY=1 ;;
        --auto) AUTO=1 ;;
        --keep-worktree) KEEP_WT=1 ;;
        --no-bump) NO_BUMP=1 ;;
        --quick) QUICK=1 ;;
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
    if [ "$QUICK" = 1 ]; then
        echo "── gate: scripts/verify_pr.sh $PR --quick ──"
    else
        echo "── gate: scripts/verify_pr.sh $PR ──"
    fi
    verify_log="$(mktemp "${TMPDIR:-/tmp}/merge_pr.${PR}.verify.XXXXXX.log")"
    if [ "$QUICK" = 1 ]; then
        "$SCRIPT_DIR/verify_pr.sh" "$PR" --quick 2>&1 | tee "$verify_log"
    else
        "$SCRIPT_DIR/verify_pr.sh" "$PR" 2>&1 | tee "$verify_log"
    fi
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
#
# EVERY check must be literally SUCCESS, and there must be at least one.
#
# PENDING is not GREEN, and neither is an empty rollup — a PR whose workflow has
# not registered yet reports no checks at all, which reads as "nothing failed".
#
# `gh pr merge --auto` is the specific trap and it is not hypothetical: on
# 2026-09-02 this repo had `allow_auto_merge: false`, so `--auto` did not queue
# the merge behind the checks, it MERGED IMMEDIATELY with nine of ten jobs still
# in progress. The rule "never merge on pending CI" was written in CLAUDE.md AND
# in the agent's own notes, including the --auto behaviour specifically, and was
# broken anyway within minutes of being read. Which is the whole argument for
# putting it here instead of in a sentence.
# --auto does not wait for checks HERE — that is the point of it — so the
# protection has to move rather than disappear. Two assertions replace the
# "every check SUCCESS" one, and the first is the entire lesson of 2026-09-02:
#
#   1. allow_auto_merge must be TRUE on the repository. When it is false, `gh pr
#      merge --auto` does not queue anything, it merges NOW. That is not a
#      failure mode someone imagined; it is what happened, with nine of ten jobs
#      still running. Asking the API costs one call and removes the trap.
#   2. No check may have already CONCLUDED as a failure. An auto-merge parked
#      behind a red check can never land, and the person who queued it walks
#      away believing it will — which is worse than a refusal.
if [ "$AUTO" = 1 ] && [ -z "${MERGE_PR_SKIP_CHECKS:-}" ]; then
    echo
    echo "── auto-merge preconditions ──"
    allow_auto="$(gh api "repos/{owner}/{repo}" --jq '.allow_auto_merge' 2>/dev/null || echo 'unknown')"
    printf '   allow_auto_merge: %s\n' "$allow_auto"
    if [ "$allow_auto" != "true" ]; then
        echo "merge_pr.sh: REFUSING --auto — allow_auto_merge is '$allow_auto' on this repo." >&2
        echo "  With it off, 'gh pr merge --auto' MERGES IMMEDIATELY rather than queueing." >&2
        echo "  That shipped a red main on 2026-09-02 with 9 of 10 jobs in progress." >&2
        echo "  Enable it in repo settings, or merge without --auto once checks are green." >&2
        exit 1
    fi
    bad="$(gh pr checks "$PR" --json name,state 2>/dev/null | "${PYTHON:-python3}" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = []
dead = {"FAILURE", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
for x in d:
    if x.get("state") in dead:
        print(" ", x.get("state"), x.get("name"))
')"
    if [ -n "$bad" ]; then
        printf '%s\n' "$bad" >&2
        echo "merge_pr.sh: REFUSING --auto — a check has already failed." >&2
        echo "  An auto-merge behind a red check never lands, and looks like it will." >&2
        exit 1
    fi
    echo "   no check has failed — safe to queue."
fi

if [ "$AUTO" = 0 ] && [ -z "${MERGE_PR_SKIP_CHECKS:-}" ]; then
    echo
    echo "── checks: every one must be SUCCESS ──"
    checks_json="$(gh pr checks "$PR" --json name,state 2>/dev/null || echo '[]')"
    read -r n_total n_ok n_bad <<EOF
$(printf '%s' "$checks_json" | "${PYTHON:-python3}" -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = []
ok = sum(1 for x in d if x.get("state") == "SUCCESS")
print(len(d), ok, len(d) - ok)
')
EOF
    printf '   %s check(s): %s SUCCESS, %s not\n' "$n_total" "$n_ok" "$n_bad"
    if [ "${n_total:-0}" -eq 0 ]; then
        echo "merge_pr.sh: REFUSING — no checks reported for PR #$PR." >&2
        echo "  An empty rollup is not a pass; the workflow may not have registered yet." >&2
        echo "  Watch it:  gh pr checks $PR --watch" >&2
        exit 1
    fi
    if [ "${n_bad:-1}" -ne 0 ]; then
        printf '%s' "$checks_json" | "${PYTHON:-python3}" -c '
import json, sys
for x in json.load(sys.stdin):
    if x.get("state") != "SUCCESS":
        print("   ", x.get("state"), x.get("name"))
' >&2
        echo "merge_pr.sh: REFUSING — $n_bad check(s) are not SUCCESS." >&2
        echo "  Watch them:  gh pr checks $PR --watch" >&2
        exit 1
    fi
fi

echo
auto_flag=""
[ "$AUTO" = 1 ] && auto_flag=" --auto"
echo "── merge: gh pr merge $PR --$MERGE_METHOD --delete-branch$auto_flag ──"
if [ "$AUTO" = 1 ]; then
    merge_out="$(gh pr merge "$PR" --"$MERGE_METHOD" --delete-branch --auto 2>&1)"
else
    merge_out="$(gh pr merge "$PR" --"$MERGE_METHOD" --delete-branch 2>&1)"
fi
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

# --auto queued it; the merge has NOT happened, so every step below would be
# operating on a trunk that has not moved and a branch that still exists.
# Stopping here and SAYING what is deferred beats running them against the
# wrong state — the batch label in particular decides what the tester receives
# together, and running it now would label a merge that has not landed.
if [ "$AUTO" = 1 ]; then
    echo
    echo "── merge_pr.sh summary ──"
    printf 'PR:              #%s (QUEUED — auto-merge, %s)\n' "$PR" "$MERGE_METHOD"
    printf 'verify:          %s\n' "$verdict_used"
    echo   'landed:          not yet — GitHub merges it when every check passes.'
    echo
    echo 'Deferred until it lands (this script cannot do them yet):'
    printf '  git -C %s pull --ff-only origin %s\n' "$main" "$base_branch"
    echo   '  scripts/open_batch.sh --push        # What'"'"'s New batch label'
    echo   '  scripts/prune_merged.sh             # worktree + branch cleanup'
    echo
    printf 'Watch it:        gh pr checks %s --watch\n' "$PR"
    printf 'Cancel it:       gh pr merge %s --disable-auto\n' "$PR"
    exit 0
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

# ── 5. open the next What's New batch label ───────────────────────────────────
# open_batch.sh decides for itself whether a bump is owed — main moved, new
# entries exist, and nothing else is still open — so calling it after every merge
# is correct: it fires once, on the merge that empties the queue.
batch_summary="(skipped — --no-bump)"
if [ "$NO_BUMP" = 1 ]; then
    echo
    echo "merge_pr.sh: --no-bump — leaving the batch label alone."
elif [ ! -x "$SCRIPT_DIR/open_batch.sh" ]; then
    batch_summary="(open_batch.sh not present)"
else
    echo
    echo "── batch label: scripts/open_batch.sh ──"
    batch_log="$(mktemp "${TMPDIR:-/tmp}/merge_pr.${PR}.batch.XXXXXX.log")"
    if "$SCRIPT_DIR/open_batch.sh" --push 2>&1 | tee "$batch_log"; then
        batch_summary="$(grep -oE '[0-9]+\.[0-9]+\.[0-9]+ -> [0-9]+\.[0-9]+\.[0-9]+' "$batch_log" | tail -1)"
        [ -n "$batch_summary" ] || batch_summary="(unchanged — nothing owed)"
    else
        # A label that failed to open is not a reason to unwind a good merge.
        batch_summary="(FAILED — run scripts/open_batch.sh by hand)"
    fi
    rm -f "$batch_log"
fi

# ── 6. cleanup (prune_merged.sh) ──────────────────────────────────────────────
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

# ── 7. final summary ──────────────────────────────────────────────────────────
merge_sha="$(git -C "$main" log -1 --oneline 2>/dev/null)"
echo
echo "── merge_pr.sh summary ──"
echo "PR:              #$PR ($MERGE_METHOD merged)"
echo "verify:          ${verdict_used:-<none>}"
echo "trunk ($base_branch): $merge_sha"
echo "batch label:     $batch_summary"
echo "prune:           $prune_summary"
