#!/usr/bin/env bash
# Run CI's four shards locally, the way CI runs them — one sanctioned path.
#
# WHY THIS EXISTS
# ---------------
# CLAUDE.md says "run all four CI shards locally before pushing when the change
# touches anything shared", and there was no script for it. So it got
# hand-rolled, and on 2026-09-01 the hand-rolled version was:
#
#     python scripts/ci_shard.py --shard $n --of 4     # <- prints file names
#     echo "shard $n exit=$?"                          # <- 0, every time
#
# ci_shard.py PRINTS the file list; CI pipes it into pytest. The local copy
# never ran a test and reported ALL SHARDS exit=0. That is the same false GREEN
# the project has now produced three ways — a grep of the summary, a pipe that
# ate the exit code, and now a runner that ran nothing — and the answer has
# been the same each time: one script, not a remembered incantation.
#
# What this adds over typing it out:
#
#   * every shard goes through scripts/pytest_verdict.sh, so it inherits the
#     exit-code-only verdict AND the flock that keeps two pytest-qt suites from
#     running at once (concurrent runs segfault; a crash is not a verdict);
#   * an EMPTY shard list is a failure, not a pass — that is the specific way
#     the hand-rolled version lied;
#   * a shard that collects zero tests is a failure too, for the same reason;
#   * shards run in sequence, never in parallel, and the run stops at the first
#     red so the log you read is the failure you have.
#
# Usage:  scripts/ci_shards_local.sh
#         scripts/ci_shards_local.sh --keep-going   # run all four regardless
set -u

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# _main_repo / resolve_py: the single sourced copy (GATE-7) — see
# scripts/repo_python.sh. Resolving `venv/bin/python` relative to CWD used to
# fail with exit 127 from a git worktree with no venv symlink; resolve_py
# borrows the main worktree's venv instead.
source "$SCRIPT_DIR/repo_python.sh"

cd "$(git rev-parse --show-toplevel)" || exit 1

if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif ! PY="$(resolve_py "$(pwd)")"; then
    _main="$(_main_repo "$(pwd)" 2>/dev/null || true)"
    echo "no interpreter found — looked for $(pwd)/venv/bin/python and ${_main:-<no main repo found>}/venv/bin/python (set PYTHON=)" >&2
    exit 1
fi

KEEP_GOING=0
[ "${1:-}" = "--keep-going" ] && KEEP_GOING=1

# ── THE REFUSAL ────────────────────────────────────────────────────────────
#
# This runs ONE platform's shards SEQUENTIALLY, ~10 minutes. CI runs the same
# files on Linux AND macOS in eight PARALLEL jobs and reports in about five. So
# the only time running it here is worth anything is when CI is not going to
# answer: no pull request yet, or a check that came back RED.
#
# Written 2026-09-02, the night this script was created, because it was created
# WITHOUT a refusal and burned ten minutes twice in an hour. Owner: "seriously
# what the fuck do you have to do to stop repeating this shit so the 15-30
# minute waits for every commit?"
#
# **The first two versions of this guard also let it through, and how is the
# useful part.** v1 keyed on "clean tree AND everything pushed" — reasoning that
# CI can only have seen a pushed commit. Both times the tree was dirty with an
# edit to THIS FILE, so the guard concluded CI could not answer, and ran the
# whole suite. v2 added a state for a PR whose checks had not registered yet and
# kept the same condition, so it fell through identically.
#
# The condition was WRONG, not incomplete. "Is my tree pushed" is not the
# question. The question is "will anything tell me this except me waiting ten
# minutes" — and an open PR with nothing failing is a yes whatever the tree
# looks like, because the right response to a local change is to PUSH it, not
# to spend ten minutes locally first.
#
# Override:  METATV_SHARDS_ANYWAY=1   (needing it twice means the habit is back)
should_refuse() {
    [ -n "${METATV_SHARDS_ANYWAY:-}" ] && return 1
    local branch has_pr checks failing
    branch="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '')"
    [ -n "$branch" ] || return 1
    has_pr="$(gh pr view "$branch" --json number -q .number 2>/dev/null || true)"
    [ -n "$has_pr" ] || return 1                 # no PR: nothing else will run this
    checks="$(gh pr checks "$branch" 2>/dev/null || true)"
    failing="$(printf '%s\n' "$checks" | grep -cE '\bfail\b' || true)"
    [ "${failing:-0}" -eq 0 ] || return 1        # something is RED: run it here
    REFUSE_PR="$has_pr"
    REFUSE_N="$(printf '%s' "$checks" | grep -c . || echo 0)"
    REFUSE_BRANCH="$branch"
    return 0
}

if should_refuse; then
    cat >&2 <<MSG
REFUSING: PR #$REFUSE_PR is open on '$REFUSE_BRANCH' and nothing has failed.

  checks reported   $REFUSE_N
  checks failing    0

CI runs these same files on both platforms in parallel. This script runs one
platform, sequentially, for about ten minutes — to learn what CI reports in
five while you do something else. If you have local changes, PUSH them; that is
faster than running them here first.

    gh pr checks $REFUSE_BRANCH --watch

Local shards earn their keep in exactly two cases:
  * no PR yet — nothing else is going to run this. On 2026-09-02 that case
    caught eight failures in a file no targeted test list would have selected.
  * a check came back RED and you want the failure in front of you.

Really need it anyway:  METATV_SHARDS_ANYWAY=1 scripts/ci_shards_local.sh
MSG
    exit 75      # EX_TEMPFAIL — a scheduling refusal, not a test failure
fi

OF=4
WORK="$(mktemp -d -t metatv-shards.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT
rc=0

export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}"

# One line, non-fatal, and placed HERE because this script runs at the moment
# before a push — which is exactly when a hook that never fires costs something.
#
# 2026-09-02: `.githooks/pre-push` was written on 2026-09-01 to stop ruff errors
# reaching CI, and `core.hooksPath` on the owner's machine points at the default
# `.git/hooks`, which is empty. So it had never run, and nothing said so. A
# guard nobody enabled is indistinguishable from a guard that passes.
hooks_path="$(git config core.hooksPath || true)"
case "$hooks_path" in
    *.githooks) ;;
    *) echo "note: git hooks are NOT enabled (core.hooksPath=${hooks_path:-<unset>})."
       echo "      .githooks/pre-push (ruff) and .githooks/pre-commit are inert."
       echo "      Enable with:  git config core.hooksPath .githooks" ;;
esac

for n in $(seq 1 "$OF"); do
    list="$WORK/shard$n.txt"
    if ! "$PY" scripts/ci_shard.py --shard "$n" --of "$OF" > "$list"; then
        echo "SHARDS: RED (ci_shard.py failed for shard $n/$OF)"
        exit 1
    fi
    files=$(wc -l < "$list" | tr -d ' ')
    if [ "$files" -eq 0 ]; then
        echo "SHARDS: RED (shard $n/$OF listed 0 test files — a shard that runs"
        echo "            nothing must never read as a pass)"
        exit 1
    fi

    echo "=== shard $n/$OF — $files test files ==="
    log="$WORK/shard$n.log"
    # Through pytest_verdict.sh, never a bare pytest: the verdict, the lock and
    # the summary formatting all live there and are not worth a second copy.
    PYTEST_VERDICT_LOG="$log" scripts/pytest_verdict.sh $(cat "$list")
    s=$?

    # A green run that collected nothing is the empty-shard failure wearing a
    # different hat — a stale path list, a collection error swallowed by -q.
    if [ "$s" -eq 0 ] && ! grep -qE "[0-9]+ (passed|error)" "$log"; then
        echo "SHARDS: RED (shard $n/$OF exited 0 but collected no tests)"
        exit 1
    fi

    if [ "$s" -ne 0 ]; then
        rc=$s
        echo "shard $n/$OF: RED (log kept at ${log/$WORK/${TMPDIR:-/tmp}})"
        cp "$log" "${TMPDIR:-/tmp}/metatv-shard$n.log" 2>/dev/null || true
        [ "$KEEP_GOING" -eq 1 ] || break
    fi
done

if [ "$rc" -eq 0 ]; then
    echo "SHARDS: GREEN (all $OF shards)"
else
    echo "SHARDS: RED (exit $rc)"
fi
exit "$rc"
