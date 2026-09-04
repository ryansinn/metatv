#!/usr/bin/env bash
# open_batch.sh — bump the What's New batch label, but only when main earned it.
#
# WHY THIS EXISTS. `__version__` is the label a batch of What's New entries ships
# under. The bump used to live inside ship_batch.sh's "release chore"; rolling
# releases made that script's tag-and-publish ceremony obsolete, the day-to-day
# merge stopped calling it, and the bump left with the ceremony. Sixty-one
# entries piled up under 0.41.0 over four days and nine merges — a label that
# identifies nothing.
#
# THE THREE CONDITIONS. A bump is owed when ALL hold:
#
#   1. main has moved since the label was opened (metatv/whats_new/batch.py's
#      OPENED_AT_SHA). Re-running this on the same commit is a REBUILD of what
#      already shipped under this label, and a rebuild must not invent a new
#      one — the build identifier (<version>+<date>.<sha>) already tells two
#      builds of the same code apart.
#
#   2. There are What's New entries past OPENED_AT_ID. A refactor-only merge
#      changes nothing a user can see, so it does not deserve its own label.
#
#   3. The batch is FINISHED — no other open, non-draft PR against the trunk.
#      A label should name a set of changes the tester receives together, not
#      count merges: bumping per PR would have produced nine labels in one day
#      and turned the version into a commit counter. "Nothing left in flight"
#      is the one signal for "this batch is done" that a script can read, and
#      it needs no flag anyone has to remember. --force overrides it.
#
# Any condition unmet → exits 0 having done nothing, and says which one.
#
#   scripts/open_batch.sh                  Bump the minor (0.41.0 -> 0.42.0) when owed.
#   scripts/open_batch.sh 0.50.0           Open that exact label instead (a jump).
#   scripts/open_batch.sh --dry-run        Say what it would do; change nothing.
#   scripts/open_batch.sh --push           Also push the chore commit to the trunk.
#   scripts/open_batch.sh --force          Bump even with PRs still open.
#   scripts/open_batch.sh --exclude-pr N   Do not count PR N as still open
#                                          (merge_pr.sh passes the PR it just
#                                          merged; GitHub still lists it).
#   scripts/open_batch.sh -h | --help      Show this help.
#
# Config knobs (via repo-root .devscripts.conf, all optional):
#   BASE_BRANCH   Trunk to read and push. Unset → auto from origin/HEAD, else main.

set -u

usage() { sed -n '2,32p' "$0" | sed 's/^# \{0,1\}//'; }

EXPLICIT=""
DRY=0
PUSH=0
FORCE=0
# A PR number to discount from "still open" — see condition 3 below.
EXCLUDE_PR=""
_want_exclude=0
for arg in "$@"; do
    if [ "$_want_exclude" = 1 ]; then EXCLUDE_PR="$arg"; _want_exclude=0; continue; fi
    case "$arg" in
        -h|--help) usage; exit 0 ;;
        --dry-run) DRY=1 ;;
        --push)    PUSH=1 ;;
        --force)   FORCE=1 ;;
        --exclude-pr) _want_exclude=1 ;;
        --exclude-pr=*) EXCLUDE_PR="${arg#*=}" ;;
        [0-9]*.[0-9]*.[0-9]*) EXPLICIT="$arg" ;;
        *) echo "open_batch.sh: unknown argument '$arg'" >&2; usage >&2; exit 2 ;;
    esac
done
if [ "$_want_exclude" = 1 ]; then
    echo "open_batch.sh: --exclude-pr needs a PR number" >&2; exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The SHARED main repository — never a worktree. `_main_repo` (from
# scripts/repo_python.sh, GATE-7) uses `--git-common-dir`, which resolves to
# the ONE .git every linked worktree shares, unlike `--show-toplevel`, which
# returns whichever worktree happens to contain SCRIPT_DIR. This script
# commits (and optionally pushes), so getting that wrong doesn't just read
# the wrong tree — it STRANDS the version-bump commit on whatever branch is
# checked out in that worktree. It did, twice, on 2026-09-02: merge_pr.sh
# invoked via a relative path from an agent worktree's cwd, so SCRIPT_DIR
# resolved inside the worktree, and the old `show-toplevel` logic here
# landed the commit on the worktree's feature branch while origin/main never
# moved.
source "$SCRIPT_DIR/repo_python.sh"
main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "open_batch.sh: not inside a git repository." >&2; exit 2; }

conf="$main/.devscripts.conf"
# shellcheck disable=SC1090
[ -f "$conf" ] && . "$conf"
base_branch="${BASE_BRANCH:-$(git -C "$main" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')}"
base_branch="${base_branch:-main}"

# A commit lands on whatever branch is checked out where it runs. $main is now
# always the shared repo (never a worktree) — but that repo itself can have
# ANY branch checked out, and a feature branch there would just as silently
# take the bump. Refuse rather than commit to the wrong place.
main_branch="$(git -C "$main" symbolic-ref --short -q HEAD 2>/dev/null || echo '')"
if [ "$main_branch" != "$base_branch" ]; then
    echo "open_batch.sh: refusing — $main has '${main_branch:-a detached HEAD}' checked out, not the trunk ('$base_branch'). Check out $base_branch there before opening a batch label." >&2
    exit 2
fi

init_py="$main/metatv/__init__.py"
batch_py="$main/metatv/whats_new/batch.py"
for f in "$init_py" "$batch_py"; do
    [ -f "$f" ] || { echo "open_batch.sh: missing $f" >&2; exit 2; }
done

# Dirty in a way that blocks the bump: uncommitted changes to the exact files
# this script writes would get swept into its automated commit as if they
# were part of the version-bump chore.
dirty="$(git -C "$main" status --porcelain -- "$init_py" "$batch_py" 2>/dev/null)"
if [ -n "$dirty" ]; then
    echo "open_batch.sh: refusing — $main has uncommitted changes to the files this bump writes:" >&2
    printf '%s\n' "$dirty" | sed 's/^/  /' >&2
    exit 2
fi

current="$(sed -nE 's/^__version__ = "([^"]+)".*/\1/p' "$init_py" | head -1)"
opened_sha="$(sed -nE 's/^OPENED_AT_SHA: str = "([^"]+)".*/\1/p' "$batch_py" | head -1)"
opened_id="$(sed -nE 's/^OPENED_AT_ID: int = ([0-9]+).*/\1/p' "$batch_py" | head -1)"
head_sha="$(git -C "$main" rev-parse --short HEAD)"
# The repo's venv if there is one — metatv.whats_new imports loguru, which a
# bare system python3 will not have. $main is always the shared repo (see
# above), so there is no separate worktree-vs-shared venv to fall back to.
py=""
[ -x "$main/venv/bin/python" ] && py="$main/venv/bin/python"
[ -n "$py" ] || py="$(command -v python3)"
latest_id="$(cd "$main" && "$py" -c 'from metatv.whats_new import latest_id; print(latest_id())' 2>/dev/null)"

[ -n "$current" ] && [ -n "$opened_sha" ] && [ -n "$opened_id" ] && [ -n "$latest_id" ] || {
    echo "open_batch.sh: could not read the current label state." >&2; exit 2; }

echo "open_batch.sh: label $current opened at $opened_sha (entry $opened_id); HEAD $head_sha, latest entry $latest_id."

# ── condition 1: has main moved? ─────────────────────────────────────────────
if [ "$head_sha" = "$opened_sha" ]; then
    echo "open_batch.sh: HEAD is the commit this label was opened at — a rebuild, not a new batch. Nothing to do."
    exit 0
fi

# ── condition 2: is there anything a user would see? ──────────────────────────
if [ "$latest_id" -le "$opened_id" ]; then
    echo "open_batch.sh: no What's New entries since $opened_id — nothing user-visible shipped. Nothing to do."
    exit 0
fi

# ── condition 3: is the batch actually finished? ──────────────────────────────
# A label names what the tester receives together. Anything still open is part of
# this batch, so closing the label now would split it across two names.
#
# ``--exclude-pr N`` discounts one number, and merge_pr.sh always passes the PR
# it just merged. Without it this condition could essentially NEVER be satisfied
# from the one place that calls this script: GitHub's PR list is eventually
# consistent, so seconds after a squash-merge the PR it just landed still comes
# back as open, and the bump is skipped on EXACTLY the merge that finishes a
# batch. Observed twice out of two on 2026-09-02 — both times the label had to
# be opened by hand afterwards, which is the manual step this script exists to
# remove.
if [ "$FORCE" = 0 ] && command -v gh >/dev/null 2>&1; then
    still_open="$(gh pr list --state open --base "$base_branch" --draft=false \
        --json number --jq \
        "map(select(.number != (\"${EXCLUDE_PR:-0}\" | tonumber))) | length" \
        2>/dev/null || echo "")"
    if [ -n "$still_open" ] && [ "$still_open" -gt 0 ]; then
        echo "open_batch.sh: $still_open PR(s) still open against $base_branch — the batch is not finished. Nothing to do (--force overrides)."
        exit 0
    fi
fi

# ── the new label ────────────────────────────────────────────────────────────
if [ -n "$EXPLICIT" ]; then
    next="$EXPLICIT"
else
    major="${current%%.*}"; rest="${current#*.}"; minor="${rest%%.*}"
    next="$major.$((minor + 1)).0"
fi

covered=$((latest_id - opened_id))
echo "open_batch.sh: $covered entr$([ "$covered" = 1 ] && echo y || echo ies) owed a label → $current -> $next"

if [ "$DRY" = 1 ]; then
    echo "open_batch.sh: --dry-run, nothing written."
    exit 0
fi

"$py" - "$init_py" "$batch_py" "$current" "$next" "$head_sha" "$latest_id" <<'PY'
import re, sys
init_py, batch_py, current, nxt, sha, latest = sys.argv[1:7]
s = open(init_py).read()
assert f'__version__ = "{current}"' in s, "version line not found"
open(init_py, "w").write(s.replace(f'__version__ = "{current}"', f'__version__ = "{nxt}"', 1))
b = open(batch_py).read()
b = re.sub(r'^OPENED_AT_SHA: str = "[^"]+"', f'OPENED_AT_SHA: str = "{sha}"', b, count=1, flags=re.M)
b = re.sub(r'^OPENED_AT_ID: int = \d+', f'OPENED_AT_ID: int = {latest}', b, count=1, flags=re.M)
open(batch_py, "w").write(b)
PY

git -C "$main" add metatv/__init__.py metatv/whats_new/batch.py
git -C "$main" commit -q -m "chore: open the $next batch

$covered What's New entries shipped under $current after it was opened at
$opened_sha. This closes that label and opens $next at $head_sha, so the next
public build carries a name that matches what is in it.

A rebuild of $head_sha will NOT bump again — open_batch.sh compares HEAD
against OPENED_AT_SHA precisely so re-running it is a no-op."
echo "open_batch.sh: committed $(git -C "$main" log -1 --format=%h) on $(git -C "$main" rev-parse --abbrev-ref HEAD)."

if [ "$PUSH" = 1 ]; then
    git -C "$main" push -q origin "HEAD:$base_branch" && echo "open_batch.sh: pushed to origin/$base_branch."
fi
