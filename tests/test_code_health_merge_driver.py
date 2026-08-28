"""The baseline merge driver resolves the conflict every branch creates.

``tests/code_health_baseline.json`` is derived data: any branch touching a
tracked file rewrites it, so any two such branches conflict.  The resolution is
mechanical, so a driver does it.  These tests drive REAL git — a throwaway repo,
two diverging branches, an actual merge — because a unit test of the merge
function alone would pass even if the driver were never wired up.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "scripts" / "merge_code_health_baseline.py"
BASELINE = "tests/code_health_baseline.json"


def _baseline(files: dict[str, int], calls: int = 79) -> str:
    return json.dumps(
        {"_comment": "test", "file_lines": files, "get_session_calls": calls},
        indent=2,
    ) + "\n"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the driver registered, as setup would."""
    r = tmp_path / "repo"
    (r / "tests").mkdir(parents=True)
    _git(r.parent, "init", "-q", str(r))
    _git(r, "config", "user.email", "t@example.com")
    _git(r, "config", "user.name", "T")
    _git(r, "config", "merge.codehealthbaseline.name", "regen")
    _git(r, "config", "merge.codehealthbaseline.driver",
         f"{sys.executable} '{DRIVER}' %O %A %B")
    (r / ".gitattributes").write_text(f"{BASELINE} merge=codehealthbaseline\n")
    (r / BASELINE).write_text(_baseline({"a.py": 1000, "b.py": 2000}))
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "base")
    return r


def _diverge(repo: Path, ours: str, theirs: str) -> None:
    """Write conflicting baselines on main and a side branch."""
    _git(repo, "checkout", "-qb", "side")
    (repo / BASELINE).write_text(theirs)
    _git(repo, "commit", "-qam", "side")
    _git(repo, "checkout", "-q", "master" if _has(repo, "master") else "main")
    (repo / BASELINE).write_text(ours)
    _git(repo, "commit", "-qam", "ours")


def _has(repo: Path, branch: str) -> bool:
    return _git(repo, "rev-parse", "--verify", branch, check=False).returncode == 0


def test_a_conflicting_merge_resolves_without_human_help(repo: Path):
    """The headline: two branches that both rewrote the baseline just merge."""
    _diverge(
        repo,
        ours=_baseline({"a.py": 1010, "b.py": 2000}),
        theirs=_baseline({"a.py": 1000, "b.py": 2050}),
    )
    res = _git(repo, "merge", "side", "-m", "merge", check=False)
    assert res.returncode == 0, f"merge still conflicted:\n{res.stdout}{res.stderr}"

    got = json.loads((repo / BASELINE).read_text())["file_lines"]
    assert got == {"a.py": 1010, "b.py": 2050}, (
        f"each file must keep the larger limit, got {got}"
    )


def test_the_resolution_can_never_fail_the_ratchet(repo: Path):
    """Safety property: the merged limit is >= both sides for every file.

    Each side's number already passed the ratchet on its own branch, so a
    limit at least as large as both cannot fail either.  This is what makes
    'maximum' the safe choice over regenerating mid-merge.
    """
    ours_f = {"a.py": 1010, "b.py": 2000, "only_ours.py": 1300}
    theirs_f = {"a.py": 1000, "b.py": 2050, "only_theirs.py": 1400}
    _diverge(repo, ours=_baseline(ours_f), theirs=_baseline(theirs_f))
    assert _git(repo, "merge", "side", "-m", "m", check=False).returncode == 0

    got = json.loads((repo / BASELINE).read_text())["file_lines"]
    for side in (ours_f, theirs_f):
        for path, limit in side.items():
            assert got[path] >= limit, f"{path}: {got[path]} < {limit}"
    assert set(got) == set(ours_f) | set(theirs_f), "a file was dropped"


def test_a_rebase_resolves_too(repo: Path):
    """Rebase is the path that actually hurt — five by hand in one evening."""
    _diverge(
        repo,
        ours=_baseline({"a.py": 1010, "b.py": 2000}),
        theirs=_baseline({"a.py": 1000, "b.py": 2050}),
    )
    _git(repo, "checkout", "-q", "side")
    res = _git(repo, "rebase", "master" if _has(repo, "master") else "main",
               check=False)
    assert res.returncode == 0, f"rebase conflicted:\n{res.stdout}{res.stderr}"
    got = json.loads((repo / BASELINE).read_text())["file_lines"]
    assert got["a.py"] == 1010 and got["b.py"] == 2050, got


def test_get_session_calls_takes_the_larger_count(repo: Path):
    _diverge(
        repo,
        ours=_baseline({"a.py": 1000}, calls=77),
        theirs=_baseline({"a.py": 1000}, calls=79),
    )
    assert _git(repo, "merge", "side", "-m", "m", check=False).returncode == 0
    assert json.loads((repo / BASELINE).read_text())["get_session_calls"] == 79


def test_the_driver_is_bound_to_the_path_in_gitattributes():
    """The wiring, not just the script: .gitattributes must name the driver."""
    text = (REPO / ".gitattributes").read_text()
    assert f"{BASELINE} merge=codehealthbaseline" in text, text


def test_output_stays_valid_json_the_ratchet_can_load():
    """The real loader must accept what the driver writes."""
    sys.path.insert(0, str(REPO))
    from scripts.merge_code_health_baseline import merge_baselines

    merged = merge_baselines(
        json.loads(_baseline({"a.py": 1010})),
        json.loads(_baseline({"b.py": 2050})),
    )
    round_tripped = json.loads(json.dumps(merged))
    assert round_tripped["file_lines"] == {"a.py": 1010, "b.py": 2050}
    assert isinstance(round_tripped["get_session_calls"], int)
