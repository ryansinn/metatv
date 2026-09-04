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

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
# _main_repo / resolve_py: the single sourced copy (GATE-7) — see
# scripts/repo_python.sh. Resolving `venv/bin/python` relative to CWD used to
# fail with exit 127 from a git worktree with no venv symlink; resolve_py
# borrows the main worktree's venv instead.
source "$SCRIPT_DIR/repo_python.sh"

LOG="${PYTEST_VERDICT_LOG:-$(mktemp -t pytest-verdict.XXXXXX.log)}"
if [ -n "${PYTHON:-}" ]; then
    PY="$PYTHON"
elif ! PY="$(resolve_py "$(pwd)")"; then
    _main="$(_main_repo "$(pwd)" 2>/dev/null || true)"
    echo "pytest_verdict.sh: no python found — looked for $(pwd)/venv/bin/python and ${_main:-<no main repo found>}/venv/bin/python. Set PYTHON=... to override." >&2
    exit 2
fi

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

# ...and a REASON IS NOT ENOUGH, because a prompt that accepts any string is a
# speed bump, not a gate. On 2026-09-01 the full local suite ran four times in
# one session, ~35 minutes each — over two hours — and three of those four were
# on trees CI had ALREADY reported green on both platforms. The prompt above was
# answered every time; it asks "why" and believes the answer.
#
# So this asks the fact instead: has CI already run the whole suite on exactly
# this tree? If yes, there is nothing a local rerun can discover.
#
# The three conditions that let it through are the three where CI genuinely
# cannot have an answer — and they are exactly the runs that have paid off. The
# CFG-5 gate that caught two cross-file failures was a pre-push run on a dirty
# tree; it would still be allowed today.
if [ "$#" -eq 0 ] && [ -z "${METATV_FULL_SUITE_ANYWAY:-}" ]; then
    _sha="$(git rev-parse HEAD 2>/dev/null || echo "")"
    _dirty="$(git status --porcelain 2>/dev/null | head -1)"
    if [ -n "$_sha" ] && [ -z "$_dirty" ] && command -v gh >/dev/null 2>&1; then
        # Total checks, and how many are not SUCCESS. An EMPTY rollup must not
        # read as "nothing failed" — that false green has shipped here twice —
        # so a total of 0 falls through to running the suite.
        _ci="$(gh api "repos/{owner}/{repo}/commits/${_sha}/check-runs" \
                 --jq '[.check_runs[] | .conclusion // "PENDING"]
                       | "\(length) \([.[] | select(. != "success" and . != "SUCCESS")] | length)"' \
               2>/dev/null || echo "")"
        _total="${_ci%% *}"; _bad="${_ci##* }"
        if [ -n "$_total" ] && [ "$_total" -gt 0 ] 2>/dev/null && [ "$_bad" = "0" ]; then
            cat >&2 <<MSG
REFUSING the full local suite: CI already ran it on this exact tree.

  commit ${_sha}
  ${_total} checks, all green — both platforms, sharded, already reported.

A local rerun of the same commit cannot discover anything CI did not. It costs
~35 minutes; CI costs ~8 and has already spent them.

Run the files you changed instead:

    scripts/pytest_verdict.sh tests/test_the_thing_you_changed.py

This gate does NOT fire when CI cannot have an answer — a dirty working tree,
an unpushed commit, or checks still pending — which is every case where a local
full run is the useful one.

If you are certain you need it anyway:

    METATV_FULL_SUITE_ANYWAY=1 METATV_FULL_SUITE_REASON="..." scripts/pytest_verdict.sh
MSG
            exit 64
        fi
    fi
fi

# SECOND LAYER: how many times already, recently.
#
# The CI check above is principled but narrow — it only fires on a clean, pushed,
# already-green tree. Replaying 2026-09-01 against it: of four full runs, three
# were on unpushed or dirty trees and only one would have been refused. The
# pattern the owner actually objected to was REPETITION ("this has been going on
# for days"), and repetition is what this counts.
#
# Two inside six hours is the budget. The one gate per merge batch plus one
# genuine pre-push run on a broad change fits; a third means something is being
# re-asked rather than asked.
_FS_LOG="${TMPDIR:-/tmp}/.metatv_full_suite_runs"
if [ "$#" -eq 0 ] && [ -z "${METATV_FULL_SUITE_ANYWAY:-}" ]; then
    _now=$(date +%s)
    _cut=$((_now - 21600))
    _recent=0
    if [ -f "$_FS_LOG" ]; then
        # Keep only entries inside the window, then count them.
        awk -v c="$_cut" '$1 > c' "$_FS_LOG" > "${_FS_LOG}.tmp" 2>/dev/null || : 
        mv -f "${_FS_LOG}.tmp" "$_FS_LOG" 2>/dev/null || :
        _recent=$(wc -l < "$_FS_LOG" 2>/dev/null || echo 0)
    fi
    if [ "$_recent" -ge 2 ] 2>/dev/null; then
        cat >&2 <<MSG
REFUSING: ${_recent} full local suites already in the last 6 hours.

Each costs ~35 minutes. CI runs the same suite on BOTH platforms, sharded, in
about 8 — for every PR, automatically. A third local run in one session is
almost always the same question asked again.

  Previous runs (reason given):
$(sed 's/^[0-9]* /    /' "$_FS_LOG" 2>/dev/null | tail -5)

Run the files you changed:

    scripts/pytest_verdict.sh tests/test_the_thing_you_changed.py

Or push and read CI. If this really is the exception:

    METATV_FULL_SUITE_ANYWAY=1 METATV_FULL_SUITE_REASON="..." scripts/pytest_verdict.sh
MSG
        exit 64
    fi
    printf '%s %s\n' "$_now" "${METATV_FULL_SUITE_REASON}" >> "$_FS_LOG"
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
# scripts/running.sh answers "is a test run already going?" without the
# self-matching that made `pgrep -f pytest` lie five times in one session.
# The lock below is what actually enforces serialization; running.sh is for
# a human (or an agent) asking before they start.
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
