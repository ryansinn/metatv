#!/usr/bin/env bash
# mutate.sh — break the code on purpose, prove the test notices, put it back.
#
# WHY THIS EXISTS
# ---------------
# The hand-rolled version of this is three steps, and step three is a trap:
#
#     python3 -c '...break something...'
#     scripts/pytest_verdict.sh tests/the_test.py
#     git checkout HEAD -- metatv/          # <-- discards UNCOMMITTED work
#
# `git checkout HEAD --` restores from the last COMMIT, so any fix written and
# not yet committed is destroyed. On 2026-09-01 that happened THREE times in one
# session — twice silently, surfacing later as a false RED on an unrelated
# mutation, and once caught only because a grep for a comment came back empty.
# It is written down in CLAUDE.md as "commit before mutation-testing"; writing it
# down did not stop it.
#
# So this refuses to run on a dirty tree. There is nothing to discard if there is
# nothing uncommitted, and the check is one line rather than one more rule.
#
#   scripts/mutate.sh <patch.py> <test path> [test path...]
#
# <patch.py> is a Python script that edits the tree. It should assert its own
# anchor — a mutation that silently fails to apply produces a GREEN run and
# reads as "the test does not catch this", which is the exact wrong conclusion.
#
# Exit 0 when the mutation was CAUGHT (tests went red — what you want).
# Exit 1 when it was MISSED (tests stayed green — the test proves nothing).
set -u

if [ "$#" -lt 2 ]; then
    sed -n '2,30p' "$0" >&2
    exit 64
fi

PATCH="$1"; shift

if [ -n "$(git status --porcelain)" ]; then
    cat >&2 <<'MSG'
REFUSING to mutate a dirty tree.

This restores with `git checkout HEAD --`, which reverts to the last COMMIT and
would destroy anything uncommitted. That has already cost three fixes in one
session, twice without noticing until a later mutation returned a false RED.

Commit first — then a mutation cannot lose anything:

    git add -A && git commit -m "..."
MSG
    exit 64
fi

BEFORE="$(git rev-parse HEAD)"
python3 "$PATCH" || { echo "mutation script failed to apply — nothing was tested" >&2; exit 64; }

if [ -z "$(git status --porcelain)" ]; then
    echo "REFUSING: the mutation changed nothing. A no-op mutation always looks 'caught'." >&2
    exit 64
fi

scripts/pytest_verdict.sh "$@"
rc=$?

git checkout "$BEFORE" -- .
git status --porcelain | grep -q . && echo "WARNING: tree still dirty after restore" >&2

if [ "$rc" -eq 0 ]; then
    echo "MUTATION MISSED — the tests stayed green. They do not detect this change."
    exit 1
fi
echo "MUTATION CAUGHT — the tests went red, as they should."
exit 0
