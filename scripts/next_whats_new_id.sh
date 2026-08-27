#!/usr/bin/env bash
# next_whats_new_id.sh — the next FREE What's New id, across main AND open PRs.
#
# WHY THIS EXISTS. The documented way to pick an id is
#
#     python -c "from metatv.whats_new import latest_id; print(latest_id() + 1)"
#
# and it is wrong whenever two branches are open at once. Each runs it against
# its own base, both bases predate the other's merge, and both get the same
# number. A CORRECT COMMAND AGAINST A STALE BASE RETURNS A TAKEN NUMBER.
#
# It has happened three times:
#   #507/#508  both took 392 — shipped, and took main RED after merge.
#   #509/#510  both took 394 — caught before merge, by hand.
#
# The uniqueness guard in tests/test_whats_new.py cannot see it: each branch is
# internally consistent, so both are green until they meet on main.
#
# This looks at every entry file on the trunk AND on every open PR's head, so
# the number it returns is free everywhere, not just here.
#
#   scripts/next_whats_new_id.sh          Print the next free id.
#   scripts/next_whats_new_id.sh --show   Also list which branch holds each of
#                                         the highest few, to spot a collision
#                                         that already exists.
set -u

SHOW=0
[ "${1:-}" = "--show" ] && SHOW=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
cd "$repo" || exit 2

base="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
base="${base:-main}"
git fetch -q origin 2>/dev/null || true

ids_on() {  # $1 = ref
    git ls-tree -r "$1" --name-only 2>/dev/null \
        | grep -oE 'entries/0*[0-9]+' | grep -oE '[0-9]+$'
}

trunk_ids="$(ids_on "origin/$base" | sort -u)"
all="$trunk_ids"
# Ids each open PR ADDS on top of the trunk. Comparing full lists would report
# every shared id as a collision, since every branch carries main's history —
# only what a branch adds can collide with what another branch adds.
added_all=""

if command -v gh >/dev/null 2>&1; then
    while read -r head; do
        [ -n "$head" ] || continue
        added="$(comm -13 <(echo "$trunk_ids") <(ids_on "origin/$head" | sort -u))"
        [ -n "$added" ] || continue
        all="$all
$added"
        added_all="$added_all
$added"
        [ "$SHOW" = 1 ] && echo "  $head adds: $(echo "$added" | tr '\n' ' ')" >&2
    done < <(gh pr list --state open --json headRefName --jq '.[].headRefName' 2>/dev/null)
fi

highest="$(echo "$all" | grep -E '^[0-9]+$' | sort -n | tail -1)"
[ -n "$highest" ] || { echo "next_whats_new_id.sh: found no entries." >&2; exit 2; }

if [ "$SHOW" = 1 ]; then
    dupes="$(echo "$added_all" | grep -E '^[0-9]+$' | sort -n | uniq -d)"
    if [ -n "$dupes" ]; then
        echo "  COLLISION between open PRs: $(echo "$dupes" | tr '\n' ' ')" >&2
        echo "  (these will make main red the moment the second one merges)" >&2
    fi
    echo "  highest anywhere: $highest" >&2
fi

echo $((10#$highest + 1))
