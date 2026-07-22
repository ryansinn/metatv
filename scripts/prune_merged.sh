#!/usr/bin/env bash
# prune_merged.sh — project-agnostic cleanup of merged-PR worktrees & branches.
#
# Scope: worktrees under <main>/.claude/worktrees/, sibling <main>-pr-* PR
# worktrees, and local branches that have no worktree.
#
# A worktree/branch is PRUNABLE when any of:
#   • its tip is an ancestor of the trunk (git merge-base --is-ancestor), or
#   • gh reports a MERGED PR for its branch (catches squash-merges whose tip
#     never becomes an ancestor), or
#   • for a <main>-pr-<N> worktree: PR #N's state is MERGED or CLOSED.
#
# NEVER pruned: the trunk, the current worktree, PROTECTED patterns, and any
# branch with commits not in the trunk and no merged/closed PR — those are
# reported as "KEPT (unmerged)". A worktree with uncommitted changes is SKIPPED
# with a warning, except when its only change is an untracked venv/ (per-worktree
# venv noise), which is force-removed. --force overrides the dirty check.
#
# PORTABLE: nothing project-specific is hardcoded. Configuration resolves as
#   (a) a repo-root `.devscripts.conf` (plain KEY=VALUE bash, sourced if present)
#   (b) auto-detection, then (c) safe defaults. See scripts/README.md.
#
#   scripts/prune_merged.sh            Prune now.
#   scripts/prune_merged.sh --dry-run  Show every action; change nothing.
#   scripts/prune_merged.sh --force    Remove prunable worktrees even if dirty.
#   scripts/prune_merged.sh -h|--help  Show this help.
#
# Config knobs (via .devscripts.conf, all optional):
#   PROTECTED_BRANCHES  Extra never-prune globs, APPENDED to the built-in
#                       defaults (main master develop).
#   BASE_BRANCH         Trunk to measure "merged" against; unset → auto from
#                       origin/HEAD, else main.
#
# _main_repo mirrors run.sh.

set -u

usage() {
    cat <<'EOF'
prune_merged.sh — safe merged-worktree/branch cleanup (project-agnostic)

USAGE
  scripts/prune_merged.sh            Prune merged-PR worktrees & stale branches.
  scripts/prune_merged.sh --dry-run  Print every action it WOULD take; touch
                                     nothing.
  scripts/prune_merged.sh --force    Remove prunable worktrees even if they have
                                     uncommitted changes.
  scripts/prune_merged.sh -h|--help  Show this help and exit.

CONFIG (repo-root .devscripts.conf, all optional)
  PROTECTED_BRANCHES  Extra never-prune globs, appended to defaults
                      (main master develop).
  BASE_BRANCH         Trunk to measure "merged" against; unset → auto from
                      origin/HEAD, else main.
EOF
}

# ── argument parsing ──────────────────────────────────────────────────────────
DRY=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --dry-run|-n) DRY=1 ;;
        --force|-f) FORCE=1 ;;
        *) echo "prune_merged.sh: unexpected argument '$arg'" >&2; usage >&2; exit 64 ;;
    esac
done

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Absolute path of the main worktree for any checkout dir (mirrors run.sh).
_main_repo() { dirname "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; }

main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "prune_merged.sh: not inside a git repo." >&2; exit 1; }

# ── load config: repo-root .devscripts.conf → auto-detect → defaults ──────────
conf="$main/.devscripts.conf"
if [ -f "$conf" ]; then
    echo "prune_merged.sh: sourcing $conf"
    # shellcheck source=/dev/null
    . "$conf"
fi

# Protected patterns: built-in defaults + any appended by the conf.
PROTECTED=( main master develop )
if [ -n "${PROTECTED_BRANCHES:-}" ]; then
    # shellcheck disable=SC2206  # intentional word-split of glob patterns
    PROTECTED+=( ${PROTECTED_BRANCHES} )
fi

# Trunk branch: explicit BASE_BRANCH, else origin/HEAD, else main.
if [ -n "${BASE_BRANCH:-}" ]; then
    base_branch="$BASE_BRANCH"
else
    base_branch="$(git -C "$main" symbolic-ref -q --short refs/remotes/origin/HEAD 2>/dev/null)"
    base_branch="${base_branch#origin/}"
    [ -n "$base_branch" ] || base_branch="main"
fi
BASE_REF="origin/$base_branch"

# Current worktree(s) to protect: where the script lives + where it's invoked.
current_wt="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
script_wt="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

echo "prune_merged.sh: main=$main  trunk=$BASE_REF  protected=[${PROTECTED[*]}]${DRY:+  (dry-run)}"
echo

# ── sync origin so merge state is current (read-only; nothing removed here) ───
have_origin=0
if git -C "$main" remote | grep -qx origin; then
    have_origin=1
    git -C "$main" fetch origin -q || echo "  warning: git fetch origin failed; using local refs" >&2
else
    echo "prune_merged.sh: no 'origin' remote — merge state limited to local ancestry." >&2
fi

have_base=0
git -C "$main" rev-parse --verify -q "$BASE_REF" >/dev/null 2>&1 && have_base=1
[ "$have_base" = 1 ] || echo "prune_merged.sh: $BASE_REF not found — ancestry checks disabled (only gh/PR state can prune)." >&2

# ── helpers ───────────────────────────────────────────────────────────────────
gh_ok() { command -v gh >/dev/null 2>&1; }

is_protected() {
    local b="$1" pat
    for pat in "${PROTECTED[@]}"; do
        # shellcheck disable=SC2254  # $pat is an intentional glob pattern
        case "$b" in $pat) return 0 ;; esac
    done
    return 1
}

is_ancestor() {  # is $1 an ancestor of the trunk?
    [ "$have_base" = 1 ] || return 1
    git -C "$main" merge-base --is-ancestor "$1" "$BASE_REF" 2>/dev/null
}

pr_state() {  # PR number → state (OPEN/MERGED/CLOSED) or empty
    gh_ok || return 1
    gh pr view "$1" --json state --jq '.state' 2>/dev/null
}

branch_has_merged_pr() {  # branch name → 0 if a MERGED PR exists for it
    gh_ok || return 1
    local n
    n="$(gh pr list --state merged --head "$1" --json number --jq 'length' 2>/dev/null)"
    [ -n "$n" ] && [ "$n" != "0" ]
}

worktree_dirty_state() {  # path → clean | venv_only | dirty
    local p="$1" st non_venv
    st="$(git -C "$p" status --porcelain 2>/dev/null)"
    [ -z "$st" ] && { echo clean; return; }
    non_venv="$(printf '%s\n' "$st" | grep -vE '^\?\? venv/$' || true)"
    if [ -z "$non_venv" ]; then echo venv_only; else echo dirty; fi
}

remove_worktree() {  # path, force(0/1)
    local p="$1" force="$2"
    if [ "$DRY" = 1 ]; then
        echo "  [dry-run] WOULD remove worktree: $p$( [ "$force" = 1 ] && echo ' (force)')"
        return 0
    fi
    if [ "$force" = 1 ]; then git -C "$main" worktree remove --force "$p"
    else git -C "$main" worktree remove "$p"; fi
}

delete_branch() {  # name (confirmed prunable → -D is safe)
    local b="$1"
    if [ "$DRY" = 1 ]; then echo "  [dry-run] WOULD delete branch: $b"; return 0; fi
    git -C "$main" branch -D "$b"
}

# ── result trackers ───────────────────────────────────────────────────────────
removed=()
kept_unmerged=()
kept_protected=()
skipped_dirty=()

# ── pass 1: worktrees in scope ────────────────────────────────────────────────
wt_path=""; wt_head=""; wt_branch=""; wt_detached=0

reset_record() { wt_path=""; wt_head=""; wt_branch=""; wt_detached=0; }

process_worktree() {
    [ -n "$wt_path" ] || return 0
    [ "$wt_path" = "$main" ] && return 0        # never the main worktree

    local in_scope=0 pr_n=""
    case "$wt_path" in
        "$main"/.claude/worktrees/*) in_scope=1 ;;
        "$main"-pr-*) in_scope=1; pr_n="${wt_path##*-pr-}" ;;
    esac
    [ "$in_scope" = 1 ] || return 0

    local label="$wt_path"
    if [ -n "$pr_n" ]; then label="$wt_path (PR #$pr_n)"
    elif [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ]; then label="$wt_path [$wt_branch]"; fi

    # ── prunable? ──
    local prunable=0 reason=""
    if [ -n "$pr_n" ]; then
        local st; st="$(pr_state "$pr_n")"
        case "$st" in
            MERGED|CLOSED) prunable=1; reason="PR #$pr_n $st" ;;
            OPEN)          reason="PR #$pr_n still OPEN" ;;
            *)             reason="PR #$pr_n state unknown (gh unavailable?)" ;;
        esac
    else
        local tip="$wt_head"
        [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ] && tip="$wt_branch"
        if is_ancestor "$tip"; then
            prunable=1; reason="merged (ancestor of $BASE_REF)"
        elif [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ] && branch_has_merged_pr "$wt_branch"; then
            prunable=1; reason="squash-merged PR"
        else
            reason="unmerged"
        fi
    fi

    if [ "$prunable" != 1 ]; then
        echo "KEPT (unmerged): $label — $reason"
        kept_unmerged+=( "$label" )
        return 0
    fi

    # ── prunable → protection guards ──
    if [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ] && is_protected "$wt_branch"; then
        echo "KEPT (protected): $label"
        kept_protected+=( "$label" ); return 0
    fi
    if [ "$wt_path" = "$current_wt" ] || [ "$wt_path" = "$script_wt" ]; then
        echo "KEPT (current worktree): $label"
        kept_protected+=( "$label" ); return 0
    fi

    # ── dirty check ──
    local dstate; dstate="$(worktree_dirty_state "$wt_path")"
    local force=0
    if [ "$FORCE" = 1 ]; then force=1
    elif [ "$dstate" = "venv_only" ]; then force=1
    elif [ "$dstate" = "dirty" ]; then
        echo "SKIPPED (dirty): $label — uncommitted changes (use --force to override)"
        skipped_dirty+=( "$label" ); return 0
    fi

    echo "PRUNE: $label — $reason"
    if remove_worktree "$wt_path" "$force"; then
        removed+=( "$label" )
        # An attached, non-protected worktree leaves an orphan branch — remove it.
        if [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ] && ! is_protected "$wt_branch"; then
            delete_branch "$wt_branch"
        fi
    else
        echo "  warning: failed to remove $wt_path" >&2
        skipped_dirty+=( "$label" )
    fi
}

while IFS= read -r line; do
    case "$line" in
        "worktree "*)   wt_path="${line#worktree }" ;;
        "HEAD "*)       wt_head="${line#HEAD }" ;;
        "branch "*)     wt_branch="${line#branch refs/heads/}"; wt_detached=0 ;;
        "detached")     wt_detached=1 ;;
        "")             process_worktree; reset_record ;;
    esac
done < <( { git -C "$main" worktree list --porcelain; printf '\n'; } )

# ── pass 2: local branches with no worktree ───────────────────────────────────
declare -A wt_branches=()
while IFS= read -r b; do
    [ -n "$b" ] && wt_branches["$b"]=1
done < <(git -C "$main" worktree list --porcelain | sed -n 's#^branch refs/heads/##p')

while IFS= read -r br; do
    [ -n "$br" ] || continue
    [ -n "${wt_branches[$br]:-}" ] && continue            # handled in pass 1
    if is_protected "$br"; then
        echo "KEPT (protected): branch $br"
        kept_protected+=( "branch $br" ); continue
    fi
    local_reason=""
    if is_ancestor "$br"; then
        local_reason="merged (ancestor of $BASE_REF)"
    elif branch_has_merged_pr "$br"; then
        local_reason="squash-merged PR"
    else
        echo "KEPT (unmerged): branch $br — unmerged"
        kept_unmerged+=( "branch $br" ); continue
    fi
    echo "PRUNE: branch $br — $local_reason"
    if delete_branch "$br"; then
        removed+=( "branch $br" )
    else
        echo "  warning: failed to delete branch $br" >&2
    fi
done < <(git -C "$main" for-each-ref --format='%(refname:short)' refs/heads/)

# ── tidy bookkeeping ──────────────────────────────────────────────────────────
echo
if [ "$DRY" = 1 ]; then
    echo "[dry-run] WOULD run: git worktree prune"
    [ "$have_origin" = 1 ] && echo "[dry-run] WOULD run: git remote prune origin"
else
    git -C "$main" worktree prune && echo "pruned stale worktree bookkeeping"
    if [ "$have_origin" = 1 ]; then
        git -C "$main" remote prune origin >/dev/null 2>&1 && echo "pruned stale remote-tracking refs"
    fi
fi

# ── summary ───────────────────────────────────────────────────────────────────
print_bucket() {  # label, items...
    local label="$1"; shift
    echo "$label: $#"
    local x
    for x in "$@"; do echo "    $x"; done
}

echo
echo "── summary${DRY:+ (dry-run — nothing changed)} ──"
print_bucket "removed       " ${removed[@]+"${removed[@]}"}
print_bucket "kept-unmerged " ${kept_unmerged[@]+"${kept_unmerged[@]}"}
print_bucket "skipped-dirty " ${skipped_dirty[@]+"${skipped_dirty[@]}"}
if [ "${#kept_protected[@]}" -gt 0 ]; then
    print_bucket "kept-protected" "${kept_protected[@]}"
fi
