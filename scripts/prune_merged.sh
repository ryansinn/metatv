#!/usr/bin/env bash
# prune_merged.sh — project-agnostic cleanup of merged-PR worktrees & branches.
#
# Scope: worktrees under <main>/.claude/worktrees/, sibling <main>-pr-* PR
# worktrees, and local branches that have no worktree.
#
# Prunable rules (a LIVE worktree is treated conservatively — a freshly created
# agent branch has no commits of its own, so its tip is trivially an ancestor of
# the trunk; ancestry alone must NOT read as "merged" for it, or an agent between
# `worktree add` and its first commit could be removed mid-task):
#   • ATTACHED worktree → prunable ONLY on merged/closed-PR evidence: gh reports
#     a MERGED PR for its branch (catches squash-merges), or a <main>-pr-<N>
#     worktree whose PR is MERGED/CLOSED. Tip-is-ancestor alone → KEPT (no unique
#     commits — possibly active agent).
#   • Local BRANCH with no worktree → prunable when its tip is an ancestor of the
#     trunk (orphaned bookkeeping) or gh reports a MERGED PR (squash-merge).
#
# NEVER pruned: the trunk, the current worktree, PROTECTED patterns, a worktree
# whose branch has no merged/closed PR, and any branch with commits not in the
# trunk — reported as "KEPT (unmerged)" / "KEPT (no unique commits …)". A worktree
# with uncommitted changes is SKIPPED with a warning, except when its only change
# is an untracked venv/ (per-worktree venv noise), which is force-removed.
# --force overrides the dirty check.
#
# PORTABLE: nothing project-specific is hardcoded. Configuration resolves as
#   (a) a repo-root `.devscripts.conf` (plain KEY=VALUE bash, sourced if present)
#   (b) auto-detection, then (c) safe defaults. See scripts/README.md.
#
#   scripts/prune_merged.sh            Prune now.
#   scripts/prune_merged.sh --dry-run  Show every action; change nothing.
#   scripts/prune_merged.sh --remote   ALSO delete remote branches whose PR is
#                                      MERGED (opt-in — affects every clone).
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
  scripts/prune_merged.sh --remote   Also delete REMOTE branches whose PR is
                                     merged. Opt-in: a remote ref is shared, so
                                     this affects every clone. Closed-but-never-
                                     merged branches are reported, never deleted.
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
REMOTE=0
for arg in "$@"; do
    case "$arg" in
        -h|--help|help) usage; exit 0 ;;
        --dry-run|-n) DRY=1 ;;
        --force|-f) FORCE=1 ;;
        --remote) REMOTE=1 ;;
        *) echo "prune_merged.sh: unexpected argument '$arg'" >&2; usage >&2; exit 64 ;;
    esac
done

# Display labels are driven by the SAME truth as the behavior gates
# (`[ "$DRY" = 1 ]`). Do NOT use `${DRY:+…}`: DRY is "0"/"1", and the ":+"
# form expands on any non-empty value — so "0" would falsely print "dry-run".
if [ "$DRY" = 1 ]; then
    dry_tag="  (dry-run)"
    dry_summary_tag=" (dry-run — nothing changed)"
else
    dry_tag=""
    dry_summary_tag=""
fi

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Absolute path of the main worktree for any checkout dir (mirrors run.sh).
_main_repo() { dirname "$(git -C "$1" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)"; }

main="$(_main_repo "$SCRIPT_DIR")"
[ -n "$main" ] || { echo "prune_merged.sh: not inside a git repo." >&2; exit 1; }

# Current worktree(s) to protect: where the script lives + where it's invoked.
current_wt="$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null || true)"
script_wt="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null || true)"

# ── load config: repo-root .devscripts.conf → auto-detect → defaults ──────────
# Sourced from the checkout the script runs from (its conf is versioned with it),
# falling back to the main worktree; removals/branch ops still target $main.
repo_root="${script_wt:-${current_wt:-$main}}"
conf="$repo_root/.devscripts.conf"
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

echo "prune_merged.sh: main=$main  trunk=$BASE_REF  protected=[${PROTECTED[*]}]${dry_tag}"
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
    # git status --porcelain reports an untracked dir as `?? venv` (no trailing
    # slash) here, though some gits/configs print `?? venv/` — accept both.
    non_venv="$(printf '%s\n' "$st" | grep -vE '^\?\? venv/?$' || true)"
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
kept_foreign=()
kept_unmerged=()
kept_active=()       # attached worktrees with no unique commits (possibly live)
kept_protected=()
skipped_dirty=()

# ── pass 1: worktrees in scope ────────────────────────────────────────────────
# Branches held by a worktree this script does NOT manage. Recorded so pass 2
# can REPORT them rather than silently skip them.
# Branch -> worktree path, as TAB-separated lines.
#
# NOT an associative array: macOS ships bash 3.2, which does not have them.
# The second one below predates this change, which means the script had never
# actually run on a stock macOS shell — it dies with "declare: usage:" and then
# an "unbound variable" on the first subscript write. Nothing noticed, because
# nothing executed the script in CI until tests/test_prune_sees_every_branch.py
# did, and it failed there on its first run.
foreign_wt_lines=""

foreign_wt_put() {  # branch, path
    foreign_wt_lines="${foreign_wt_lines}$1	$2
"
}

foreign_wt_get() {  # branch -> path on stdout; empty when absent
    [ -n "$foreign_wt_lines" ] || return 0
    printf '%s' "$foreign_wt_lines" | awk -F'\t' -v b="$1" '$1 == b { print $2; exit }'
}

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
    if [ "$in_scope" != 1 ]; then
        # A worktree somewhere else — a session scratchpad, a manual `git
        # worktree add`. Pass 1 does not touch it (it is not this script's to
        # manage), but its BRANCH must not therefore become invisible: pass 2
        # used to skip every branch that had a worktree anywhere, so a branch
        # parked in an out-of-scope worktree fell through BOTH passes and was
        # never pruned by anything. That is how 33 local and 248 remote
        # branches accumulated behind a script whose whole job was to prevent
        # exactly that.
        if [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ]; then
            foreign_wt_put "$wt_branch" "$wt_path"
        fi
        return 0
    fi

    local label="$wt_path"
    if [ -n "$pr_n" ]; then label="$wt_path (PR #$pr_n)"
    elif [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ]; then label="$wt_path [$wt_branch]"; fi

    # ── prunable? (a worktree is ATTACHED by definition — only merged/closed-PR
    #    evidence may prune it; ancestry alone is NOT proof, see header) ──
    local prunable=0 reason="" keep_kind="unmerged"
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
        if [ "$wt_detached" = 0 ] && [ -n "$wt_branch" ] && branch_has_merged_pr "$wt_branch"; then
            prunable=1; reason="merged PR"
        elif is_ancestor "$tip"; then
            # Tip is an ancestor but the branch has no unique commits — could be a
            # brand-new agent branch. Do NOT prune on this alone.
            keep_kind="no_unique"; reason="no unique commits — possibly active agent"
        else
            reason="unmerged"
        fi
    fi

    if [ "$prunable" != 1 ]; then
        if [ "$keep_kind" = "no_unique" ]; then
            echo "KEPT (no unique commits — possibly active agent): $label"
            kept_active+=( "$label" )
        else
            echo "KEPT (unmerged): $label — $reason"
            kept_unmerged+=( "$label" )
        fi
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
# Only branches whose worktree pass 1 actually PROCESSED are "handled" — a
# branch in an out-of-scope worktree is not, and must be reported.
wt_branch_lines=""
while IFS= read -r b; do
    [ -n "$b" ] || continue
    [ -n "$(foreign_wt_get "$b")" ] && continue
    wt_branch_lines="${wt_branch_lines}${b}
"
done < <(git -C "$main" worktree list --porcelain | sed -n 's#^branch refs/heads/##p')

wt_branch_has() {  # branch -> 0 when pass 1 already handled it
    [ -n "$wt_branch_lines" ] || return 1
    printf '%s' "$wt_branch_lines" | grep -qxF "$1"
}

while IFS= read -r br; do
    [ -n "$br" ] || continue
    wt_branch_has "$br" && continue                       # handled in pass 1
    foreign_path="$(foreign_wt_get "$br")"
    if [ -n "$foreign_path" ]; then
        # Cannot delete a checked-out branch, and this script does not own that
        # worktree — so say so out loud instead of skipping in silence.
        echo "KEPT (worktree outside scope): branch $br — $foreign_path"
        kept_foreign+=( "branch $br ($foreign_path)" ); continue
    fi
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

# ── pass 3: REMOTE branches whose PR is merged ────────────────────────────────
# Opt-in (--remote), because deleting a remote ref affects everyone with a clone.
#
# There was no remote pass at all, and nothing else deletes these: `gh pr merge
# --delete-branch` only covers PRs merged through THIS script, so every PR
# merged from the GitHub web UI left its branch behind. 248 of them had
# accumulated by 2026-08-29 against 6 open PRs. The durable fix is the
# repository's own `delete_branch_on_merge` setting (now enabled), which covers
# every merge path including the UI; this pass exists to sweep up if it is ever
# turned off again, or for a repo that cannot set it.
#
# Only MERGED is swept. A CLOSED PR's branch holds work that never landed —
# deleting it discards the only copy — so those are reported, never removed.
if [ "$REMOTE" = 1 ] && [ "$have_origin" = 1 ] && gh_ok; then
    echo
    echo "── pass 3: remote branches with a MERGED PR ──"
    remote_deleted=0
    while IFS= read -r rb; do
        [ -n "$rb" ] || continue
        [ "$rb" = "$BASE_REF" ] && continue
        is_protected "$rb" && { echo "KEPT (protected): origin/$rb"; continue; }
        st="$(gh pr list --state all --head "$rb" --limit 1 --json state \
              --jq '.[0].state' 2>/dev/null || echo "")"
        case "$st" in
            MERGED)
                if [ "$DRY" = 1 ]; then
                    echo "  [dry-run] WOULD delete origin/$rb (PR merged)"
                else
                    if git -C "$main" push origin --delete "$rb" >/dev/null 2>&1; then
                        echo "PRUNE: origin/$rb — PR merged"
                        remote_deleted=$(( remote_deleted + 1 ))
                        removed+=( "origin/$rb" )
                    else
                        echo "  warning: failed to delete origin/$rb" >&2
                    fi
                fi
                ;;
            CLOSED) echo "KEPT (PR closed, never merged — holds unlanded work): origin/$rb" ;;
            OPEN)   echo "KEPT (PR open): origin/$rb" ;;
            *)      echo "KEPT (no PR): origin/$rb" ;;
        esac
    done < <(git -C "$main" ls-remote --heads origin 2>/dev/null | sed 's#.*refs/heads/##')
    echo "  remote branches deleted: $remote_deleted"
fi

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
echo "── summary${dry_summary_tag} ──"
print_bucket "removed       " ${removed[@]+"${removed[@]}"}
print_bucket "kept-unmerged " ${kept_unmerged[@]+"${kept_unmerged[@]}"}
print_bucket "skipped-dirty " ${skipped_dirty[@]+"${skipped_dirty[@]}"}
if [ "${#kept_active[@]}" -gt 0 ]; then
    print_bucket "kept-active   " "${kept_active[@]}"
fi
if [ "${#kept_protected[@]}" -gt 0 ]; then
    print_bucket "kept-protected" "${kept_protected[@]}"
fi
if [ "${#kept_foreign[@]}" -gt 0 ]; then
    print_bucket "kept-foreign-wt" "${kept_foreign[@]}"
fi
