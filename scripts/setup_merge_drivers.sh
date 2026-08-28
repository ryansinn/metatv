#!/usr/bin/env bash
# Register this repo's git merge drivers in the local clone.
#
# A merge driver is NAMED in .gitattributes but DEFINED in git config, which is
# not versioned — so every clone runs this once. Idempotent.
#
# Without it nothing breaks: git reports a normal conflict on
# tests/code_health_baseline.json, exactly the old behaviour.
#
# The command is stored with a RELATIVE script path on purpose. Git runs a merge
# driver from the top of the working tree, and this config is shared by every
# worktree of the clone — an absolute path recorded from inside a throwaway
# worktree would point at a directory that gets deleted.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
rel="scripts/merge_code_health_baseline.py"

if [ ! -f "$repo_root/$rel" ]; then
    echo "setup_merge_drivers: $rel not found under $repo_root" >&2
    exit 1
fi

python="$(command -v python3 || command -v python)"

git config merge.codehealthbaseline.name \
    "resolve tests/code_health_baseline.json by per-key maximum"
git config merge.codehealthbaseline.driver "$python $rel %O %A %B"

echo "setup_merge_drivers: registered 'codehealthbaseline'"
git config --get merge.codehealthbaseline.driver | sed 's/^/  driver: /'
echo "  tests/code_health_baseline.json now auto-resolves on merge/rebase."
