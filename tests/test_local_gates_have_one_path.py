"""Every local gate has ONE sanctioned path, and a new hand-rolled one fails here.

The project's recurring failure is not that a rule is unknown — it is that a
rule with no script gets re-derived from memory at the moment it is needed, and
the re-derivation is wrong in a way that reads as success:

* 2026-08-31 — a full suite ending ``1 failed, 8044 passed`` was reported GREEN
  twice, because the verdict came from a grep of the summary. Answer:
  ``scripts/pytest_verdict.sh``, which decides on the exit code only.
* 2026-09-01 — "run the four CI shards locally" was typed out by hand as
  ``python scripts/ci_shard.py --shard N --of 4`` and its exit code checked.
  ``ci_shard.py`` PRINTS the file list; CI pipes it into pytest. Four shards
  ran zero tests and the run reported ``ALL SHARDS exit=0``. Answer:
  ``scripts/ci_shards_local.sh``.
* Five test files each wrote their own ``deleteLater`` + ``DeferredDelete``
  drain. Answer: ``tests/conftest.py``'s ``destroy_widget``.

Each answer only holds while nothing quietly grows a second path, which prose
cannot promise. The counts below are SHRINK-ONLY, the same ratchet
``code_health_baseline.json`` and ``test_watchlist_settled_design_holds`` use:
the known copies are recorded so the debt sits in CI rather than in a document,
and a NEW one fails immediately.
"""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_TESTS = _ROOT / "tests"
_SCRIPTS = _ROOT / "scripts"

#: Test files that drain DeferredDelete themselves instead of importing
#: ``tests.conftest.destroy_widget``. Shrink-only: migrating these is a tidy-up
#: slice, growing the list is a review failure.
#:
#: ``conftest.py`` is not in the count — it is where the shared one lives.
_KNOWN_PRIVATE_TEARDOWNS = {
    "test_filter_only_and_none.py",
    "test_lightbox_badges_and_watch_later.py",
    "test_lightbox_metadata_lens.py",
    "test_toggle_chip_paints_setchecked.py",
    "test_watch_rule_editor.py",
}

#: Scripts that invoke pytest without going through ``pytest_verdict.sh``.
#: Shrink-only, and both are on the way out:
#:
#: ``ship_batch.sh``  — the pre-rolling-release chore; retired by
#:                      ``.github/workflows/release.yml`` but still on disk.
#: ``verify_pr.sh``   — predates the verdict script and carries its own strict
#:                      summary parse, which is the very thing the verdict
#:                      script exists to replace.
_KNOWN_BARE_PYTEST_SCRIPTS = {"ship_batch.sh", "verify_pr.sh"}

_DRAIN = re.compile(r"sendPostedEvents\(\s*None\s*,\s*(?:QEvent\.Type\.)?DeferredDelete\s*\)")
_BARE_PYTEST = re.compile(r"(?<!scripts/)\bpytest\b[^\n]*", re.M)


def test_no_new_private_widget_teardown_helper():
    """``destroy_widget`` is in conftest; nobody writes a sixth copy.

    A parentless top-level left alive is repainted by every later
    ``apply_theme()``, and one per test segfaulted a CI shard — so this is not
    style, it is the thing that turns a green suite into exit 139.
    """
    found = {
        path.name
        for path in sorted(_TESTS.glob("test_*.py"))
        if _DRAIN.search(path.read_text(encoding="utf-8"))
    }
    new = found - _KNOWN_PRIVATE_TEARDOWNS
    assert not new, (
        "these test files drain DeferredDelete themselves instead of using "
        f"tests.conftest.destroy_widget: {sorted(new)}"
    )
    # Shrink-only: when one is migrated, delete it from the set above.
    assert found <= _KNOWN_PRIVATE_TEARDOWNS
    stale = _KNOWN_PRIVATE_TEARDOWNS - found
    assert not stale, (
        f"these no longer have a private drain — remove them from the list: {sorted(stale)}")


def test_no_new_script_runs_pytest_outside_the_verdict_script():
    """One place decides whether a test run passed."""
    offenders = set()
    for path in sorted(_SCRIPTS.glob("*.sh")):
        if path.name == "pytest_verdict.sh":
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "pytest_verdict.sh" in stripped:
                continue
            # A `case` alternation is the one place "-m pytest" appears as DATA
            # rather than as a command: running.sh matches it to exclude the
            # pytest processes it must not count. Matching it here would push
            # someone to "fix" the process detector, which is the opposite of
            # what this guard wants.
            if re.search(r"\)\s*;;\s*$", stripped):
                continue
            if re.search(r"-m\s+pytest\b", stripped):
                offenders.add(path.name)
    new = offenders - _KNOWN_BARE_PYTEST_SCRIPTS
    assert not new, (
        "these scripts run pytest without scripts/pytest_verdict.sh, so their "
        f"verdict is decided somewhere new: {sorted(new)}"
    )


def test_the_local_shard_runner_exists_and_routes_through_the_verdict_script():
    """The 2026-09-01 false GREEN, pinned so it cannot be re-derived by hand."""
    runner = _SCRIPTS / "ci_shards_local.sh"
    assert runner.exists(), (
        "CLAUDE.md tells you to run the four CI shards locally before pushing a "
        "shared change; without a script that instruction gets typed from "
        "memory, and the last time it was, it ran zero tests and passed."
    )
    body = runner.read_text(encoding="utf-8")
    assert "pytest_verdict.sh" in body, "the shard runner must not decide its own verdict"
    assert "ci_shard.py" in body
    # The specific lie it exists to prevent: an empty shard reading as a pass.
    assert re.search(r'-eq 0\b', body) and "0 test files" in body, (
        "the runner must fail on a shard that lists no files")


def test_the_shard_runner_refuses_when_ci_is_already_answering():
    """The waste this gate exists to stop, and the two ways it leaked.

    ``ci_shards_local.sh`` runs ONE platform's shards sequentially, ~10 minutes.
    CI runs the same files on both platforms in eight parallel jobs. So a local
    run is only worth anything when CI is not going to answer.

    The script shipped without this refusal and burned ten minutes twice in an
    hour. Two later versions of the guard ALSO let it through, both because the
    condition keyed on "clean tree AND everything pushed" — and both times the
    tree was dirty with an edit to the script itself. The condition is now "is
    a PR open with nothing failing", which does not care what the tree looks
    like, because the answer to a local change is to push it.
    """
    body = (_SCRIPTS / "ci_shards_local.sh").read_text(encoding="utf-8")
    assert "should_refuse()" in body, "the refusal has been removed"
    assert "gh pr view" in body and "gh pr checks" in body, (
        "the refusal must key on whether CI is answering")
    assert "METATV_SHARDS_ANYWAY" in body, "an override must exist and be named"
    # The specific regression: the condition that leaked twice.
    for gone in ("git status --porcelain", "@{u}..HEAD"):
        assert gone not in body, (
            f"the refusal is keyed on {gone!r} again — that is the condition "
            "that let a full run through twice on 2026-09-02")


def test_a_script_answers_which_tests_to_run():
    """Choosing tests by feel selects the ones that NAME what you changed.

    That missed eight tests in ``test_migration_center.py`` on 2026-09-02: they
    reached ``channel_mod.time``, a name ``channel.py`` only imported, and
    nothing in the file named the modules being changed.
    """
    picker = _SCRIPTS / "tests_for_change.sh"
    assert picker.exists(), (
        "there is no script for 'which tests should I run', so the answer gets "
        "guessed — and the guess has a known blind spot")
    body = picker.read_text(encoding="utf-8")
    # Assert the MECHANISM, not the prose. The first version of this checked for
    # the phrase "not a selection" — which also appears in the comment ABOVE the
    # guard, so deleting the guard itself left the test green. Caught by
    # mutation, which is the only reason it is written this way.
    assert "total_tests / 4" in body, (
        "no saturation threshold — the picker will emit a list that looks "
        "considered and costs as much as running everything")
    assert 'git diff -U0' in body and "'^-(import |from .* import" in body, (
        "the picker no longer detects a REMOVED module-level name, which is "
        "the case local selection cannot see")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell hook")
def test_the_pre_commit_hook_refuses_a_co_authored_by_trailer(tmp_path):
    """The owner's standing instruction, against a tool that adds one by default.

    Executed, not read: a hook that parses is not a hook that runs.
    """
    hook = _ROOT / ".githooks" / "pre-commit"
    assert hook.exists()

    bad = tmp_path / "bad.txt"
    bad.write_text("a commit\n\nCo-Authored-By: Someone <a@b.c>\n", encoding="utf-8")
    result = subprocess.run(["bash", str(hook), str(bad)], cwd=_ROOT,
                            capture_output=True, text=True)
    assert result.returncode != 0, "the trailer was allowed through"
    assert "Co-Authored-By" in result.stderr

    good = tmp_path / "good.txt"
    good.write_text("a commit\n", encoding="utf-8")
    result = subprocess.run(["bash", str(hook), str(good)], cwd=_ROOT,
                            capture_output=True, text=True)
    # Not asserting exit 0: the hook's OTHER rule (no branch work in the
    # owner's own checkout) legitimately fires in some checkouts, including
    # CI's. What must be true is that a clean message is not blamed for a
    # trailer it does not have.
    assert "Co-Authored-By" not in result.stderr


def test_auto_merge_refuses_when_the_repo_setting_would_make_it_immediate():
    """``--auto`` is only safe while ``allow_auto_merge`` is true, so it checks.

    Executed against a stubbed API, not read: on 2026-09-02 this repo had
    ``allow_auto_merge: false``, and ``gh pr merge --auto`` therefore did not
    queue anything — it merged on the spot with nine of ten jobs still running.
    The rule "never merge on pending CI" was written in CLAUDE.md and in the
    agent's own notes, naming that exact ``--auto`` behaviour, and was broken
    anyway within minutes of being read.

    So the flag may exist only alongside a refusal that fires when the setting
    is off. This drives the script with ``gh`` shadowed by a stub reporting
    ``false``, which is the state that caused the incident.
    """
    script = _ROOT / "scripts" / "merge_pr.sh"
    assert script.exists()
    assert "--auto" in script.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp) / "gh"
        # Answers the two calls the script makes before it would ever merge:
        # the repo setting (false), and the PR's state (OPEN). Any `pr merge`
        # reaching this stub is itself the failure, and says so.
        stub.write_text(
            '#!/usr/bin/env bash\n'
            'case "$*" in\n'
            '  *allow_auto_merge*) echo false ;;\n'
            '  *"pr view"*state*)  echo OPEN ;;\n'
            '  *"pr checks"*)      echo "[]" ;;\n'
            '  *"pr merge"*)       echo "STUB REACHED THE MERGE" >&2; exit 99 ;;\n'
            '  *)                  echo "{}" ;;\n'
            'esac\n', encoding="utf-8")
        stub.chmod(0o755)

        env = {**os.environ, "PATH": f"{tmp}:{os.environ['PATH']}"}
        result = subprocess.run(
            ["bash", str(script), "999", "--auto", "--skip-verify"],
            cwd=_ROOT, capture_output=True, text=True, env=env, timeout=120)

    assert "STUB REACHED THE MERGE" not in result.stderr, (
        "merge_pr.sh --auto called `gh pr merge` with allow_auto_merge false — "
        "that merges IMMEDIATELY, which is the 2026-09-02 incident exactly.")
    assert result.returncode != 0, "--auto was allowed through with the setting off"
    assert "allow_auto_merge" in result.stderr, (
        f"refused, but not for the auto-merge reason:\n{result.stderr[-600:]}")
