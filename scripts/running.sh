#!/usr/bin/env bash
# running.sh — what of MINE is actually running, without lying about it.
#
# WHY THIS EXISTS
# ---------------
# `pgrep -f pytest` matches its own shell, because the shell's argv contains the
# pattern. That produced a false answer five separate times in one session:
#
#   - a crash-hunt loop that had died on launch was reported as "still running"
#     for several minutes, because pgrep matched the querying shell and showed
#     an elapsed time of 0s
#   - a "stale process" was reported that was the query itself
#   - twice more while checking whether it was safe to start a test run
#
# Reading /proc/*/cwd instead does not fix it either: the querying shell's cwd
# is also the repo, and its command line still embeds the pattern.
#
# The fix is to exclude the caller by IDENTITY rather than to hope the pattern
# is specific enough — this script's own pid, its parent, and its process
# group are skipped by number.
#
#   scripts/running.sh            # test runs and watch loops
#   scripts/running.sh --all      # every process rooted in the repo
#
# Exit 0 when something is running, 1 when nothing is — so it can gate a script:
#
#   scripts/running.sh >/dev/null || scripts/pytest_verdict.sh tests/...
set -u

ALL=0
[ "${1:-}" = "--all" ] && ALL=1

# This reads /proc, so it is Linux-only. On a platform without it the loop
# below simply never runs and the script would answer "nothing running" — the
# false negative this script exists to prevent, on a whole platform. Say so and
# exit 0 (= "something may be running") instead, because the gate form
# `running.sh || pytest` treats non-zero as permission to start a second run,
# and "I cannot tell" must never grant that.
if [ ! -d /proc ]; then
    echo "  cannot determine what is running on this platform (no /proc)" >&2
    exit 0
fi

SELF=$$
PARENT=$PPID
REPO=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
# Worktrees live outside the repo root, so match the project name too.
NAME=$(basename "$REPO")

found=0
for proc in /proc/[0-9]*; do
    pid=${proc#/proc/}

    # Identity exclusions — the whole point of this script.
    #
    # By PID, not by process GROUP. Excluding the caller's whole process group
    # was the first attempt and it was worse than the bug it replaced: a
    # background job started with `&` from the same shell shares that group, so
    # the script reported "nothing running" WHILE A TEST RUN WAS ACTIVE. A
    # false negative here is more dangerous than the false positive it was
    # written to fix — it would green-light a second concurrent pytest, which
    # segfaults on this machine.
    [ "$pid" = "$SELF" ] && continue
    [ "$pid" = "$PARENT" ] && continue

    cwd=$(readlink "$proc/cwd" 2>/dev/null) || continue
    case "$cwd" in *"$NAME"*) ;; *) continue ;; esac

    cmd=$(tr '\0' ' ' < "$proc/cmdline" 2>/dev/null)
    [ -z "$cmd" ] && continue
    # Any other copy of this script, and the shell wrapping it.
    case "$cmd" in *running.sh*) continue ;; esac

    if [ "$ALL" -eq 0 ]; then
        case "$cmd" in
            *"-m pytest"*|*"for i in "*|*"gh pr checks"*|*"until "*) ;;
            *) continue ;;
        esac
    fi

    secs=$(ps -o etimes= -p "$pid" 2>/dev/null | tr -d ' ')
    printf "  pid=%-8s %6ss  %s\n" "$pid" "${secs:-?}" "$(echo "$cmd" | cut -c1-72)"
    found=1
done

if [ "$found" -eq 0 ]; then
    echo "  nothing running"
    exit 1
fi
exit 0
