#!/usr/bin/env bash
# ship_batch.sh — batch merge + release + publish as one command (project-specific).
#
# Sequences multiple PRs into a release cut: verifies each PR is OPEN, merges them
# into a temp worktree with conflict detection, applies the release chore (version
# bump + what's-new entries), runs the full test gate, merges each PR, cherry-picks
# the chore onto fresh main, tags, and publishes a release. Without --dry-run, also
# pushes to main and GitHub. --dry-run performs steps 1–4 (all checks) and prints
# WOULD-SHIP.
#
# This is release tooling for maintainers, not a day-to-day merge tool. It assumes
# the staging PRs exist and are verified independently beforehand — this script's
# job is to batch them, apply the release metadata, gate once on the full suite,
# and ship.
#
#   scripts/ship_batch.sh 0.15.0 123 124 125          Merge PRs 123/124/125, apply
#                                                     v0.15.0 release chore, test,
#                                                     merge each, tag & release.
#   scripts/ship_batch.sh 0.15.0 123 124 125 --dry-run   Steps 1–4 only (checks
#                                                        + gate); abort on RED or
#                                                        conflict; print WOULD-SHIP.
#   scripts/ship_batch.sh -h | --help                 Show this help.
#
# Config knobs (via .devscripts.conf, all optional):
#   BASE_BRANCH    Trunk to merge into & push from. Unset → auto from origin/HEAD,
#                  else main.
#   RELEASE_NOTES  Path to a file with release notes (passed to `gh release edit`
#                  as --notes-file). Unset → empty notes.
#
# Exit codes:
#   0  Released, all PRs merged, tag pushed, release created.
#   1  RED gate, merge conflict, merge failure, or test failure.
#   2  A PR is not OPEN (merged/closed) — refused.

set -u

usage() {
    cat <<'EOF'
ship_batch.sh — batch merge + release + publish (MetaTV)

USAGE
  scripts/ship_batch.sh <version> <PR#> [<PR#>...]    Merge PRs into a temp
                                                       worktree, apply release
                                                       chore, test, merge each
                                                       PR, tag, publish release.
  scripts/ship_batch.sh <version> <PR#> ... --dry-run   Steps 1–4 only (checks
                                                        + gate); print WOULD-SHIP
                                                        on GREEN.
  scripts/ship_batch.sh -h | --help                    Show this help and exit.

CONFIG (repo-root .devscripts.conf, all optional)
  BASE_BRANCH    Trunk to merge into; unset → auto from origin/HEAD, else main.
  RELEASE_NOTES  Path to release-notes file (passed to `gh release edit`).

EXIT CODES
  0  Released successfully.
  1  RED gate, conflict, merge failure, or test failure.
  2  A PR is not OPEN (merged/closed) — refused.
EOF
}

# ── argument parsing ──────────────────────────────────────────────────────────
DRY_RUN=0
VERSION=""
PRS=()
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --dry-run) DRY_RUN=1 ;;
        ''|*[!0-9]*[!0-9]*)
            if [ -z "$VERSION" ]; then
                VERSION="$arg"
            else
                echo "ship_batch.sh: unexpected argument '$arg'" >&2
                usage >&2
                exit 64
            fi
            ;;
        *)
            PRS+=("$arg")
            ;;
    esac
done

if [ -z "$VERSION" ] || [ ${#PRS[@]} -eq 0 ]; then
    echo "ship_batch.sh: a version and at least one PR number are required." >&2
    usage >&2
    exit 64
fi

# Validate version format
if ! echo "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo "ship_batch.sh: invalid version '$VERSION' (want X.Y.Z)" >&2
    exit 64
fi

command -v gh >/dev/null 2>&1 || { echo "ship_batch.sh: the gh CLI is required." >&2; exit 1; }

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

# _main_repo / resolve_py: the single sourced copy (GATE-7) — see
# scripts/repo_python.sh.
source "$SCRIPT_DIR/repo_python.sh"
main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "ship_batch.sh: not inside a git repo." >&2; exit 1; }

# ── load config: repo-root .devscripts.conf → defaults ────────────────────────
conf="$main/.devscripts.conf"
if [ -f "$conf" ]; then
    echo "ship_batch.sh: sourcing $conf"
    # shellcheck source=/dev/null
    . "$conf"
fi

if [ -n "${BASE_BRANCH:-}" ]; then
    base_branch="$BASE_BRANCH"
else
    base_branch="$(git -C "$main" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)"
    base_branch="${base_branch#origin/}"
    [ -n "$base_branch" ] || base_branch="main"
fi

echo "ship_batch.sh: version=$VERSION  base_branch=$base_branch  PRs=${PRS[*]}  dry_run=$DRY_RUN"

# ── step 1: verify each PR is OPEN ───────────────────────────────────────────
echo
echo "── step 1: verify PR states ──"
for pr in "${PRS[@]}"; do
    state=""
    state="$(gh pr view "$pr" --json state --jq '.state' 2>/dev/null)"
    if [ -z "$state" ]; then
        echo "ship_batch.sh: couldn't fetch PR #$pr (does it exist / is gh authed?)." >&2
        exit 1
    fi
    if [ "$state" != "OPEN" ]; then
        echo "ship_batch.sh: PR #$pr is $state, not OPEN — refusing to ship." >&2
        exit 2
    fi
    echo "  PR #$pr: OPEN"
done

# ── step 2: create temp worktree, fetch & merge each PR sequentially ──────────
echo
echo "── step 2: create temp worktree & merge PRs ──"
wt="/tmp/metatv-ship-${VERSION}"
if [ -d "$wt" ]; then
    echo "Cleaning up stale $wt"
    git worktree list --porcelain | grep -q "worktree $wt" && \
        git worktree remove --force "$wt" 2>/dev/null || true
    rm -rf "$wt"
fi

git fetch origin -q || true
git worktree add --detach "$wt" "origin/$base_branch" || {
    echo "ship_batch.sh: failed to create worktree $wt" >&2; exit 1; }
echo "ship_batch.sh: created $wt at $(git -C "$wt" rev-parse --short HEAD)"

for pr in "${PRS[@]}"; do
    echo
    echo "  Merging PR #$pr into $wt..."
    if ! git -C "$wt" fetch origin "pull/$pr/head:pr-$pr" -q 2>/dev/null; then
        echo "ship_batch.sh: failed to fetch PR #$pr" >&2
        git worktree remove --force "$wt" 2>/dev/null || true
        exit 1
    fi

    mergelog="$(mktemp "${TMPDIR:-/tmp}/ship_batch.merge.$pr.XXXXXX.log")"
    if ! git -C "$wt" -c user.email=ship@local -c user.name=ship-batch \
            merge --no-edit "pr-$pr" >"$mergelog" 2>&1; then
        conflicts="$(git -C "$wt" diff --name-only --diff-filter=U 2>/dev/null)"
        git -C "$wt" merge --abort 2>/dev/null || true
        echo "MERGE CONFLICT — PR #$pr conflicts with the batch tree:"
        if [ -n "$conflicts" ]; then
            printf '%s\n' "$conflicts" | sed 's/^/  /'
        else
            echo "  (merge failed; git output:)"
            sed 's/^/  /' "$mergelog"
        fi
        rm -f "$mergelog"
        echo
        echo "ship_batch.sh: worktree $wt left for manual inspection (remove manually after resolving)."
        echo "  git worktree remove --force \"$wt\""
        exit 1
    fi
    rm -f "$mergelog"
    echo "  PR #$pr merged"
done

# ── step 3: apply release chore ──────────────────────────────────────────────
echo
echo "── step 3: apply release chore ($VERSION) ──"

# Bump __version__ in metatv/__init__.py
init_file="$wt/metatv/__init__.py"
python3 - "$init_file" "$VERSION" <<'PYINIT'
import re, sys, pathlib
path, new = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
text = p.read_text()
text = re.sub(r'(__version__\s*=\s*["\'])([^"\']+)(["\'])', rf'\g<1>{new}\g<3>', text, count=1)
p.write_text(text)
print(f"Bumped __version__ to {new}")
PYINIT

# Update version in what's-new entries added by the merged PRs
echo "Updating version in what's-new entries added by the merged PRs..."
entry_files="$(git -C "$wt" diff --name-only "origin/$base_branch"..HEAD -- 'metatv/whats_new/entries/*.py' 2>/dev/null || true)"
if [ -n "$entry_files" ]; then
    while IFS= read -r entry_file; do
        if [ -f "$wt/$entry_file" ]; then
            # Replace version="anything except VERSION" with version="VERSION"
            python3 - "$wt/$entry_file" "$VERSION" <<'PYENTRY'
import re, sys, pathlib
path, new_version = sys.argv[1], sys.argv[2]
p = pathlib.Path(path)
text = p.read_text()
# Match version="..." but NOT the target version
text = re.sub(
    rf'version="(?!{re.escape(new_version)})[^"]*"',
    f'version="{new_version}"',
    text,
    count=1
)
p.write_text(text)
print(f"  Updated version in {path}")
PYENTRY
        fi
    done <<< "$entry_files"
fi

# Commit the chore
git -C "$wt" add metatv/__init__.py $entry_files 2>/dev/null || true
git -C "$wt" commit -m "chore(release): $VERSION" -q || true
echo "Release chore committed"

# ── step 4: run the test gate ────────────────────────────────────────────────
echo
echo "── step 4: run test gate ──"

# Interpreter resolution: the worktree's own venv, else the main repo's
# (GATE-7 / GATE-7b) — via scripts/repo_python.sh, not a hand-rolled check.
py="$(resolve_py "$wt")" || {
    echo "ship_batch.sh: no venv found" >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    exit 1
}

log="$(mktemp "${TMPDIR:-/tmp}/ship_batch.test.XXXXXX.log")"
trap 'rm -f "$log"' EXIT

echo "Running: $py -m pytest tests/ -q"
if ( cd "$wt" && "$py" -m pytest tests/ -q >"$log" 2>&1 ); then
    verdict="GREEN"
    reason="$(grep -iE ' in [0-9][0-9.]*s' "$log" \
        | grep -iE '(passed|failed|error|no tests ran|skipped|xfailed|xpassed)' \
        | tail -n1)"
else
    verdict="RED"
    reason="pytest exited non-zero"
fi

echo "── test output (last 15 lines) ──"
tail -n 15 "$log"

if [ "$verdict" != "GREEN" ]; then
    echo
    echo "VERDICT: RED — $reason"
    git worktree remove --force "$wt" 2>/dev/null || true
    exit 1
fi

echo
echo "VERDICT: GREEN — $reason"

# ── if --dry-run, stop here ──────────────────────────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
    echo
    echo "WOULD-SHIP: $VERSION (${#PRS[@]} PR${#PRS[@]#1}s)"
    git worktree remove --force "$wt" 2>/dev/null || true
    exit 0
fi

# ── step 5: merge each PR, cherry-pick chore onto main, push ─────────────────
echo
echo "── step 5: merge PRs & cherry-pick chore onto main ──"

chore_sha="$(git -C "$wt" rev-parse HEAD)"
echo "Chore commit: $chore_sha"

for pr in "${PRS[@]}"; do
    echo
    echo "  Merging PR #$pr via gh pr merge..."
    merge_out="$(gh pr merge "$pr" --squash --delete-branch 2>&1)"
    merge_rc=$?
    printf '%s\n' "$merge_out"
    if [ "$merge_rc" -ne 0 ]; then
        if printf '%s' "$merge_out" | grep -qiE 'failed to delete local branch|used by worktree|checked out at'; then
            echo "  (local branch held by worktree — ok)"
        else
            echo "ship_batch.sh: merge failed — aborting." >&2
            git worktree remove --force "$wt" 2>/dev/null || true
            exit 1
        fi
    fi

    # Confirm merge
    post_state="$(gh pr view "$pr" --json state --jq '.state' 2>/dev/null)"
    if [ "$post_state" != "MERGED" ]; then
        echo "ship_batch.sh: PR #$pr is '$post_state' after merge — aborting." >&2
        git worktree remove --force "$wt" 2>/dev/null || true
        exit 1
    fi
done

echo
echo "  All PRs merged. Cherry-picking chore commit onto fresh main..."

# Create a fresh main-based worktree for the cherry-pick
wt_main="/tmp/metatv-ship-main"
if [ -d "$wt_main" ]; then
    git worktree list --porcelain | grep -q "worktree $wt_main" && \
        git worktree remove --force "$wt_main" 2>/dev/null || true
    rm -rf "$wt_main"
fi

git fetch origin -q || true
git worktree add --detach "$wt_main" "origin/$base_branch" || {
    echo "ship_batch.sh: failed to create worktree $wt_main" >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    exit 1
}

# Cherry-pick the chore commit (extract its patch from the merge tree)
if ! git -C "$wt_main" cherry-pick "$chore_sha" 2>/dev/null; then
    echo "ship_batch.sh: cherry-pick failed — aborting." >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    git worktree remove --force "$wt_main" 2>/dev/null || true
    exit 1
fi

# Verify the tree is clean (matches main after the PR merges)
if ! git -C "$wt_main" diff --quiet "origin/$base_branch" HEAD; then
    echo "ship_batch.sh: worktree HEAD is dirty vs origin/$base_branch — aborting." >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    git worktree remove --force "$wt_main" 2>/dev/null || true
    exit 1
fi

# Push main-based worktree
echo "Pushing to origin/$base_branch..."
if ! git -C "$wt_main" push origin HEAD:"$base_branch" -q; then
    echo "ship_batch.sh: push failed — aborting." >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    git worktree remove --force "$wt_main" 2>/dev/null || true
    exit 1
fi

# ── step 6: tag, publish release ────────────────────────────────────────────
echo
echo "── step 6: tag & publish release ──"

# Tag on the pushed commit
echo "Creating tag v$VERSION..."
if ! git -C "$wt_main" tag -a "v$VERSION" -m "MetaTV $VERSION" -q; then
    echo "ship_batch.sh: tag creation failed — aborting." >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    git worktree remove --force "$wt_main" 2>/dev/null || true
    exit 1
fi

echo "Pushing tag..."
if ! git -C "$wt_main" push origin "v$VERSION" -q; then
    echo "ship_batch.sh: tag push failed — aborting." >&2
    git worktree remove --force "$wt" 2>/dev/null || true
    git worktree remove --force "$wt_main" 2>/dev/null || true
    exit 1
fi

# Wait for the CI run on the tag
echo "Polling for CI run on tag..."
for attempt in {1..60}; do
    run="$(gh run list --workflow release.yml -L 1 2>/dev/null | grep "v$VERSION" || true)"
    if [ -n "$run" ]; then
        run_id="$(printf '%s' "$run" | awk '{print $NF}')"
        echo "Found run $run_id, waiting for completion..."
        if gh run watch "$run_id" --exit-status 2>/dev/null; then
            break
        fi
    fi
    if [ "$attempt" -lt 60 ]; then
        sleep 2
    fi
done

# Create/edit the release
echo "Creating release v$VERSION..."
release_title="MetaTV $VERSION"
notes_arg=""
if [ -n "${RELEASE_NOTES:-}" ] && [ -f "$RELEASE_NOTES" ]; then
    notes_arg="--notes-file $RELEASE_NOTES"
fi

gh release create "v$VERSION" --title "$release_title" $notes_arg \
    --target "$base_branch" 2>&1 || \
    gh release edit "v$VERSION" --title "$release_title" $notes_arg 2>&1

# Print release URL & assets
echo
release_url="$(gh release view "v$VERSION" --json url --jq '.url')"
echo "Release created: $release_url"

echo
echo "Release assets:"
gh release view "v$VERSION" --json assets --jq '.assets[] | "\(.name) — \(.size) bytes"' || \
    echo "  (no assets yet — check back in a moment)"

# ── step 7: cleanup ──────────────────────────────────────────────────────────
echo
echo "── cleanup ──"
git worktree remove --force "$wt" 2>/dev/null || true
git worktree remove --force "$wt_main" 2>/dev/null || true
echo "Cleaned up temp worktrees"

echo
echo "SHIPPED v$VERSION (${#PRS[@]} PR${#PRS[@]#1}s)"
exit 0
