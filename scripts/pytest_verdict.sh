#!/usr/bin/env bash
# Run pytest and report a verdict that cannot be misread.
#
# WHY THIS EXISTS
# ---------------
# On 2026-08-31 a full local suite finished "1 failed, 8044 passed" and was
# reported to the owner as GREEN. Two checks were used and both were wrong:
#
#   grep -oE "[0-9]+ (passed|failed)" LOG | tail -1   -> "8044 passed"
#   grep -c "^FAILED" LOG                             -> 0
#
# The first takes the LAST number in "1 failed, 8044 passed" — which is always
# the passing one. The second matched nothing because pytest writes ANSI colour
# codes before the word, so "FAILED" is never at the start of a raw line.
#
# CLAUDE.md already said "never pipe a test run through tail/head/grep in the
# same command that decides success — redirect to a log, capture $?, decide on
# it." The redirect happened; the decision was still made on grep. So the
# exit code is the ONLY thing this script decides on, and the summary is
# printed for humans rather than parsed for a verdict.
#
# Usage:  scripts/pytest_verdict.sh [pytest args...]
#         scripts/pytest_verdict.sh tests/test_foo.py
#         scripts/pytest_verdict.sh            # whole suite
set -u

LOG="${PYTEST_VERDICT_LOG:-$(mktemp -t pytest-verdict.XXXXXX.log)}"
PY="${PYTHON:-venv/bin/python}"

# A FULL local suite is a deliberate act, not a default.
#
# CI runs the whole suite on Linux AND macOS for every pull request, so a local
# full run duplicates a gate that is already running — ~15 minutes each, and
# two of them cannot even run at once (concurrent pytest-qt segfaults, so they
# serialize). CLAUDE.md has said "never re-run locally what CI has already
# reported" since 2026-08-27 and it was ignored twice on 2026-08-31, which is
# the argument for a mechanical step rather than another sentence of prose.
#
# Passing no path argument means "everything". That now requires a stated
# reason, so the decision is made on purpose and is visible in the shell
# history:
#
#   METATV_FULL_SUITE_REASON="one gate for the merge batch" scripts/pytest_verdict.sh
#
# The legitimate reasons are narrow: the single gate for a merge batch, a
# release, session wrap, or a change broad enough that per-file runs have a
# blind spot (a moved contract breaks files the change never touched).
if [ "$#" -eq 0 ] && [ -z "${METATV_FULL_SUITE_REASON:-}" ]; then
    cat >&2 <<'MSG'
REFUSING to run the full suite without a reason.

CI already runs it on both platforms for every PR. While building, run the
files you changed:

    scripts/pytest_verdict.sh tests/test_the_thing_you_changed.py

If you genuinely need the whole suite — the one gate for a merge batch, a
release, session wrap, or a change whose blast radius per-file runs cannot
see — say so:

    METATV_FULL_SUITE_REASON="one gate for the merge batch" scripts/pytest_verdict.sh
MSG
    exit 64
fi

if [ "$#" -eq 0 ]; then
    echo "FULL SUITE — reason: ${METATV_FULL_SUITE_REASON}"
fi

# SERIALIZED BY A LOCK, not by remembering.
#
# Two pytest-qt suites in one process tree segfault on this machine — SIGSEGV,
# exit 139, no summary line. That has been known and written down since
# 2026-07-30, and the note twenty lines above this one says they "cannot even
# run at once". Prose did not stop it: on 2026-08-31 an overlap contaminated a
# segfault investigation, and the crash it produced was read as evidence about
# the code under test rather than about the overlap.
#
# flock makes it impossible instead of inadvisable. A second run WAITS rather
# than racing, so a background loop and a foreground check can both be started
# without thinking about it. Set METATV_PYTEST_NOWAIT=1 to fail fast instead of
# queueing, which is what a script wants when it would rather skip than block.
LOCK="${TMPDIR:-/tmp}/metatv-pytest.lock"
if [ -n "${METATV_PYTEST_NOWAIT:-}" ]; then
    _FLOCK_ARGS="-n"
else
    _FLOCK_ARGS=""
fi
exec 9>"$LOCK"
if ! flock $_FLOCK_ARGS 9; then
    echo "VERDICT: RED (another pytest run holds $LOCK — concurrent pytest-qt segfaults)"
    exit 75          # EX_TEMPFAIL: not a test failure, a scheduling refusal
fi

TZ=UTC QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" \
    "$PY" -m pytest "$@" > "$LOG" 2>&1
code=$?
flock -u 9 2>/dev/null || true

# Strip ANSI so the human-readable lines below are actually readable.
sed -i 's/\x1b\[[0-9;]*m//g' "$LOG" 2>/dev/null || true

echo "--- failures -------------------------------------------------------"
grep -E "^(FAILED|ERROR) " "$LOG" | head -40 || true
echo "--- summary --------------------------------------------------------"
tail -n 3 "$LOG"
echo "--- log ------------------------------------------------------------"
echo "$LOG"

# The verdict is the exit code and nothing else. pytest returns 0 only when
# every collected test passed; 1 on failures, 2 on interrupt, 3 internal,
# 4 usage, 5 no-tests-collected. All of those are RED here — "no tests ran"
# has been mistaken for success before.
if [ "$code" -eq 0 ]; then
    echo "VERDICT: GREEN (pytest exit 0)"
else
    echo "VERDICT: RED (pytest exit $code)"
fi
exit "$code"
