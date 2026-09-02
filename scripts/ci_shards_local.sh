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

cd "$(git rev-parse --show-toplevel)" || exit 1

PY="${PYTHON:-venv/bin/python}"
[ -x "$PY" ] || { echo "no interpreter at $PY (set PYTHON=)" >&2; exit 1; }

KEEP_GOING=0
[ "${1:-}" = "--keep-going" ] && KEEP_GOING=1

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
