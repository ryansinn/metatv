#!/usr/bin/env bash
# mutate.sh — prove a test can actually detect the defect it is named for.
#
# A green test run says the test agrees with the current code. It says nothing
# about whether the test could ever catch the bug. The only way to know is to
# put the bug back and watch the test go red.
#
# WHY THIS IS A SCRIPT AND NOT A HABIT
# ------------------------------------
# Hand-rolled mutation loops have produced BOTH failure directions here:
#
#   false GREEN — the assertion was vacuously true (a bound checked over a
#                 collection that is always empty), so the mutation changed
#                 nothing observable.
#   false RED   — 2026-08-31: the loop began `cd <worktree>` to a worktree that
#                 had been removed. cd failed, cp failed, sed failed, pytest
#                 never ran, and the script reported "RED ✓" off the *cd's*
#                 exit code. A mutation that never happened was recorded as
#                 proof.
#
# So this script refuses to report anything until it has PROVEN it mutated the
# file: it diffs before and after, aborts if they match, and prints the changed
# line so the mutation is visible rather than assumed. It also verifies the
# restore, because a mutation left behind is worse than one never applied.
#
# USAGE
#   scripts/mutate.sh <file> <sed-expr> <pytest -k filter> <description>
#
#   scripts/mutate.sh metatv/core/recording_manager.py \
#       's/if row.recorded_bytes > 0:/if False:/' \
#       bytes_is_completed "a partial recording is called a failure"
#
# EXIT: 0 when the mutation was applied AND the test went red (the good case).
#       1 when the test stayed green — the test cannot see the defect.
#       2 when the mutation could not be applied — nothing was proven.
set -u

FILE="${1:?usage: mutate.sh <file> <sed-expr> <-k filter> <description>}"
EXPR="${2:?missing sed expression}"
KFILTER="${3:?missing pytest -k filter}"
DESC="${4:?missing description}"
PY="${PYTHON:-venv/bin/python}"
BAK="$(mktemp)"

cleanup() { [ -f "$BAK" ] && rm -f "$BAK"; }
trap cleanup EXIT

if [ ! -f "$FILE" ]; then
    echo "ABORT ?  $DESC"
    echo "         $FILE does not exist — nothing was mutated, nothing proven."
    exit 2
fi

cp "$FILE" "$BAK"
sed -i "$EXPR" "$FILE"

# THE CHECK THAT MAKES THIS TRUSTWORTHY: did the file actually change?
if diff -q "$BAK" "$FILE" >/dev/null 2>&1; then
    cp "$BAK" "$FILE"
    echo "ABORT ?  $DESC"
    echo "         sed matched nothing — the code was never mutated, so a red or"
    echo "         green result here would mean nothing. Fix the expression."
    exit 2
fi

echo "         mutation applied:"
diff "$BAK" "$FILE" | grep -E '^[<>]' | head -4 | sed 's/^/         /'

# Same lock as pytest_verdict.sh, and for the same reason: two pytest-qt suites
# at once segfault, and a segfault here would be read as "RED — the test caught
# it" when it caught nothing. A mutation harness that can be contaminated by a
# background run is worse than none, because its output looks like proof.
exec 9>"${TMPDIR:-/tmp}/metatv-pytest.lock"
flock 9

"$PY" -m pytest -q -p no:randomly -k "$KFILTER" >/dev/null 2>&1
code=$?
flock -u 9 2>/dev/null || true

# 139 is SIGSEGV. It is never evidence about the mutation — on this machine it
# means a Qt teardown crash, which would otherwise be counted as a pass for the
# test's ability to detect the defect.
if [ "$code" -eq 139 ]; then
    cp "$BAK" "$FILE"
    echo "ABORT !  $DESC"
    echo "         pytest segfaulted (139). That says nothing about the mutation."
    exit 2
fi

cp "$BAK" "$FILE"
if ! diff -q "$BAK" "$FILE" >/dev/null 2>&1; then
    echo "ABORT !  $DESC"
    echo "         RESTORE FAILED — $FILE is still mutated. Fix it before continuing."
    exit 2
fi

if [ "$code" -eq 5 ]; then
    echo "ABORT ?  $DESC"
    echo "         pytest collected no tests for -k '$KFILTER' — nothing ran."
    exit 2
fi

if [ "$code" -ne 0 ]; then
    echo "RED   ✓  $DESC"
    exit 0
fi
echo "GREEN ✗  $DESC"
echo "         The test passed with the defect reintroduced. It cannot detect it."
exit 1
