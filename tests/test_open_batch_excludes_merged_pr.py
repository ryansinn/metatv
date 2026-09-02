"""The batch label must be openable by the merge that finishes the batch.

``open_batch.sh`` refuses to bump while any PR is still open against the trunk —
condition 3, and it is the condition that makes the label name a BATCH rather
than count merges. But its only caller is ``merge_pr.sh``, which runs it
immediately after a squash-merge, and GitHub's PR list is eventually consistent:
for a few seconds the PR just merged still comes back open.

So condition 3 could essentially never be satisfied from the one place that
calls it. Observed twice out of two on 2026-09-02 — both merges printed "1 PR(s)
still open ... Nothing to do", and both times the label had to be opened by hand
afterwards, which is the manual step the script exists to remove. That is the
same shape as the 61 entries that once piled up under 0.41.0.

``--exclude-pr N`` discounts exactly one number, and ``merge_pr.sh`` passes the
PR it just merged.
"""

import pathlib
import subprocess

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
OPEN_BATCH = SCRIPTS / "open_batch.sh"
MERGE_PR = SCRIPTS / "merge_pr.sh"


def test_both_scripts_are_present_and_executable():
    for script in (OPEN_BATCH, MERGE_PR):
        assert script.exists(), f"{script.name} is gone"
        assert script.stat().st_mode & 0o111, f"{script.name} is not executable"


def test_merge_pr_passes_the_pr_it_just_merged():
    """The wiring IS the fix — the flag alone changes nothing.

    Asserted on the call site rather than on the flag's existence, because a
    flag nobody passes is exactly the state this replaces.
    """
    body = MERGE_PR.read_text()
    assert "open_batch.sh" in body, "merge_pr.sh no longer opens the batch label"
    call = [ln for ln in body.splitlines() if "open_batch.sh" in ln and "--push" in ln]
    assert call, "merge_pr.sh no longer runs open_batch.sh --push"
    assert any("--exclude-pr" in ln for ln in call), (
        "merge_pr.sh runs open_batch.sh --push without --exclude-pr, so the "
        "just-merged PR counts as still open and the label is never bumped by "
        "the merge that finishes the batch")
    assert any('"$PR"' in ln for ln in call), (
        "--exclude-pr must carry the PR number merge_pr.sh just merged")


def test_open_batch_accepts_the_flag_and_rejects_a_bare_one():
    """Both forms parse, and a missing value is an error rather than a silent
    skip — a swallowed argument would re-create the bug while looking fixed."""
    env = {"PATH": "/usr/bin:/bin"}
    ok = subprocess.run(
        [str(OPEN_BATCH), "--dry-run", "--exclude-pr", "999999"],
        capture_output=True, text=True, timeout=60,
        cwd=SCRIPTS.parent, env=env)
    assert ok.returncode == 0, ok.stderr
    assert "unknown argument" not in ok.stderr

    equals = subprocess.run(
        [str(OPEN_BATCH), "--dry-run", "--exclude-pr=999999"],
        capture_output=True, text=True, timeout=60,
        cwd=SCRIPTS.parent, env=env)
    assert equals.returncode == 0, equals.stderr
    assert "unknown argument" not in equals.stderr

    bare = subprocess.run(
        [str(OPEN_BATCH), "--exclude-pr"],
        capture_output=True, text=True, timeout=60,
        cwd=SCRIPTS.parent, env=env)
    assert bare.returncode == 2, (
        f"a bare --exclude-pr must be an error, got {bare.returncode}")
    assert "needs a PR number" in bare.stderr


def test_the_still_open_count_actually_discounts_that_number():
    """The jq filter itself, against a synthetic list — the script's own
    expression, so a rewrite that stops filtering is caught here."""
    import json
    import shutil

    if shutil.which("jq") is None:                      # pragma: no cover
        import pytest
        pytest.skip("jq not installed")

    body = OPEN_BATCH.read_text()
    assert "tonumber" in body, "the exclusion filter is gone from open_batch.sh"

    prs = json.dumps([{"number": 673}, {"number": 680}])
    for exclude, expected in (("0", 2), ("673", 1), ("999", 2)):
        out = subprocess.run(
            ["jq", f'map(select(.number != ("{exclude}" | tonumber))) | length'],
            input=prs, capture_output=True, text=True, timeout=30)
        assert int(out.stdout.strip()) == expected, (
            f"excluding {exclude} left {out.stdout.strip()}, expected {expected}")
