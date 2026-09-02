#!/usr/bin/env bash
# Answer "which tests should I run for this change?" from the diff, not from memory.
#
# WHY
# ---
# The choice was being made by feel, and feel is wrong in a specific direction:
# it selects tests that NAME the thing you changed. On 2026-09-02 that missed
# eight tests in test_migration_center.py, which reached `channel_mod.time` — a
# name channel.py only imported. Sharing a helper deleted that import and every
# one of them raised AttributeError. Nothing in the file named `watchlist` or
# `db_lock`, so no keyword list would have contained it.
#
# The rule that falls out, and the only judgement this encodes:
#
#   * changed a function BODY          -> the tests naming the module are enough
#   * added/REMOVED a module-level name -> other modules reach THROUGH this one;
#                                          local selection cannot see them, so
#                                          push and let CI answer
#
# Plus one unconditional addition: the ratchet guards. They are named for the
# RULE they enforce (code_health, skeleton probes, composed contrast, drift),
# never for the feature, so no feature keyword can reach them and they are the
# ones a new named thing trips.
#
# Usage:  scripts/tests_for_change.sh [base]      # default: origin/main
#         scripts/pytest_verdict.sh $(scripts/tests_for_change.sh)
set -u
cd "$(git rev-parse --show-toplevel)" || exit 1
BASE="${1:-origin/main}"
SEL="$(mktemp -t metatv-tests-for-change.XXXXXX)"
trap 'rm -f "$SEL"' EXIT

changed="$(git diff --name-only "$BASE"...HEAD; git diff --name-only; git diff --cached --name-only)"
changed="$(printf '%s\n' "$changed" | sort -u | grep -E '^(metatv|tests|scripts)/' || true)"
[ -n "$changed" ] || { echo "# nothing changed against $BASE" >&2; exit 0; }

# Everything below prints test FILE PATHS on stdout and nothing else, so the
# output can be pasted straight into pytest_verdict.sh. Notes go to stderr.
{
    # 1. changed test files always run
    printf '%s\n' "$changed" | grep -E '^tests/test_.*\.py$' || true

    # 2. tests that NAME a changed production module.
    #
    #    conftest.py is deliberately NOT searched for: every test file imports
    #    from it, so it would select all 1,000 of them and the answer would be
    #    "run everything" dressed up as a selection. A conftest change IS the
    #    everything case, and says so on stderr below.
    for f in $(printf '%s\n' "$changed" | grep -E '^metatv/.*\.py$'); do
        mod="$(basename "$f" .py)"
        case "$mod" in __init__|conftest) continue ;; esac
        grep -rl -- "$mod" tests/ --include='test_*.py' 2>/dev/null || true
    done

    # 3. the ratchets — named for the RULE they enforce, never for a feature,
    #    so no feature keyword can reach them. Seconds to run, and they fire on
    #    precisely the mistakes that feel like correct Python.
    for t in test_code_health_ratchet test_skeleton_host_attribute_probes \
             test_widget_composed_contrast test_registries_are_derived \
             test_theme_style_registry test_local_gates_have_one_path \
             test_mainwindow_launch_smoke; do
        [ -f "tests/$t.py" ] && echo "tests/$t.py"
    done
} | grep -vE '__pycache__' | grep -E '^tests/test_[A-Za-z0-9_]+\.py$' | sort -u > "$SEL"

# A selection that selects nearly everything is not a selection, and printing it
# would be the worst outcome: a list that LOOKS considered and costs the same
# ten minutes as running the lot. This branch produced 513 files, because it
# changed a module called `base` and every test mentions it.
total_tests="$(ls tests/test_*.py 2>/dev/null | wc -l | tr -d ' ')"
picked="$(wc -l < "$SEL" | tr -d ' ')"
if [ "$picked" -gt $(( total_tests / 4 )) ]; then
    {
      echo
      echo "NOTE: selection picked $picked of $total_tests test files."
      echo "  That is not a selection. It happens when a changed module has a"
      echo "  short generic name (base, config, theme) that most tests mention."
      echo "  Push and read CI rather than running a quarter of the suite here."
    } >&2
    rm -f "$SEL"
    exit 0
fi
cat "$SEL"; rm -f "$SEL"

# 4. the honest limits of local selection, on stderr so the list stays pasteable
if printf '%s\n' "$changed" | grep -qE '^tests/conftest\.py$'; then
    {
      echo
      echo "NOTE: tests/conftest.py changed — every test file uses it."
      echo "  There is no useful selection here. Push and read CI."
    } >&2
fi

removed_names="$(git diff -U0 "$BASE"...HEAD -- 'metatv/*.py' \
    | grep -E '^-(import |from .* import |[A-Za-z_]+ *=|def |class )' || true)"
if [ -n "$removed_names" ]; then
    {
      echo
      echo "NOTE: this change REMOVES module-level names:"
      printf '%s\n' "$removed_names" | sed 's/^/    /' | head -12
      echo
      echo "  A test can reach a name through a module that merely imported it"
      echo "  (monkeypatch.setattr(some_mod.time, ...)), and no selection based"
      echo "  on the modules you changed can see that. Push and read CI — it is"
      echo "  the only thing that runs everything, and it does both platforms"
      echo "  in parallel."
    } >&2
fi
