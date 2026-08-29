"""`prune_merged.sh` must not lose sight of a branch it cannot prune.

The bug this guards
-------------------
The script has two passes. Pass 1 walks worktrees but only ACTS on those under
``<main>/.claude/worktrees/`` or a sibling ``<main>-pr-*``. Pass 2 walks local
branches and skipped any branch that appeared in ``git worktree list``.

A branch whose worktree lives anywhere else — a session scratchpad, a manual
``git worktree add`` — therefore fell through BOTH: out of scope for pass 1,
"already handled" for pass 2. It could never be pruned, and nothing said so.

That is how branches accumulated behind a script whose entire job is to stop
them accumulating. The fix does not delete those branches (the script does not
own that worktree, and git refuses to delete a checked-out branch anyway) — it
REPORTS them, so the invisible becomes visible.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "scripts" / "prune_merged.sh"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A real git repo with a commit on main — the script needs genuine refs."""
    main = tmp_path / "repo"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "T")
    (main / "f.txt").write_text("one\n")
    _git(main, "add", "-A")
    _git(main, "commit", "-qm", "first")
    # The script resolves its own repo root (and any .devscripts.conf) from
    # where it LIVES, not from the cwd — so it has to be copied in, or it would
    # cheerfully inspect the developer's real checkout instead of this fixture.
    (main / "scripts").mkdir()
    shutil.copy(SOURCE, main / "scripts" / "prune_merged.sh")
    return main


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_a_branch_in_an_out_of_scope_worktree_is_reported(repo: Path, tmp_path: Path) -> None:
    """The branch must appear in the output, not vanish between the two passes."""
    outside = tmp_path / "elsewhere"
    _git(repo, "worktree", "add", "-b", "feature/parked", str(outside), "-q")

    res = subprocess.run(
        ["bash", "scripts/prune_merged.sh", "--dry-run"],
        cwd=repo, capture_output=True, text=True,
    )
    combined = res.stdout + res.stderr

    assert "feature/parked" in combined, (
        "a branch parked in an out-of-scope worktree produced NO output at all "
        f"— it is invisible to both passes.\n{combined}"
    )
    assert "worktree outside scope" in combined, (
        f"the branch was mentioned but not explained as out-of-scope:\n{combined}"
    )


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_dry_run_deletes_nothing(repo: Path, tmp_path: Path) -> None:
    """The safety property the whole script rests on."""
    outside = tmp_path / "elsewhere2"
    _git(repo, "worktree", "add", "-b", "feature/keep-me", str(outside), "-q")

    before = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")
    subprocess.run(["bash", "scripts/prune_merged.sh", "--dry-run"], cwd=repo,
                   capture_output=True, text=True)
    after = _git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/")

    assert before == after, "--dry-run changed the branch list"


@pytest.mark.skipif(not shutil.which("bash"), reason="bash required")
def test_remote_pass_is_opt_in(repo: Path) -> None:
    """Without --remote the script must not even consider remote refs.

    Deleting a remote branch affects every clone, so it cannot be the default.
    """
    res = subprocess.run(["bash", "scripts/prune_merged.sh", "--dry-run"], cwd=repo,
                         capture_output=True, text=True)
    assert "pass 3" not in (res.stdout + res.stderr), (
        "the remote pass ran without --remote"
    )


def test_no_script_uses_a_bash_4_associative_array() -> None:
    """macOS ships bash 3.2, which has no ``declare -A``.

    ``prune_merged.sh`` carried one for months. It was never caught because
    nothing in CI executed the script — the moment a test did, macOS failed
    with::

        declare: usage: declare [-afFirtx] [-p] [name[=value] ...]
        prune_merged.sh: line 241: feature: unbound variable

    and Linux passed the same commit, because bash 4+ is fine with it. That
    asymmetry is the whole reason this guard scans the SOURCE rather than
    relying on a run: a green Linux job proves nothing about the shell the
    other half of CI uses.

    Scanning every script, not a list of known ones, so a new script is
    covered the day it is added.
    """
    import re

    scripts = sorted((Path(__file__).resolve().parent.parent / "scripts").glob("*.sh"))
    assert scripts, "no shell scripts found — has the directory moved?"

    offenders = []
    for script in scripts:
        for n, line in enumerate(script.read_text(encoding="utf-8").splitlines(), 1):
            if re.match(r"\s*declare\s+-A\b", line):
                offenders.append(f"{script.name}:{n}")

    assert not offenders, (
        "bash 3.2 (the macOS system shell) has no associative arrays, so these "
        f"lines abort the script there: {offenders}. Use TAB-separated lines "
        "plus a small awk/grep lookup, as prune_merged.sh does."
    )
