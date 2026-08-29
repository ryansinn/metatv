"""``run.sh`` says when the checkout it is about to run is behind its remote.

It deliberately does not pull — running THIS tree is the point when you are
testing a change. The failure mode is the silent one: a checkout drifts behind
and every launch quietly re-runs bugs that were fixed days ago. That cost a
whole evening — nine commits behind, repeatedly hitting a crash whose fix was
already on main and already in the shipped build.

So the rule is report, never act. A fetch or pull here would be worse than the
problem, because it would change the code under someone who ran this script
precisely to test what they have.
"""

from __future__ import annotations

import shutil
import os
import subprocess
import tempfile
from pathlib import Path

import pytest

RUN_SH = Path(__file__).resolve().parents[1] / "run.sh"
pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("bash") is None,
    reason="needs git and bash",
)


def _sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def _extract_function(name: str) -> str:
    """Return just *name*'s definition from run.sh, as text.

    Sliced in PYTHON rather than with ``source <(sed -n ...)``. That version
    passed on Linux and failed on every macOS CI run with
    ``warn_if_behind: command not found`` — the extraction silently produced
    nothing, so the test reported a missing function rather than anything about
    the behaviour it guards. Process substitution and sed dialects are two
    portability bets this test never needed to make.
    """
    lines = RUN_SH.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}()"))
    end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith("}"))
    return "\n".join(lines[start:end + 1])


def _call_notice(cwd: Path, target: Path) -> str:
    """Run only warn_if_behind, so nothing launches the app."""
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
        fh.write(_extract_function("warn_if_behind"))
        fn_path = fh.name
    try:
        out = _sh(
            "bash", "-c", f'source "{fn_path}"; warn_if_behind "{target}"', cwd=cwd
        )
    finally:
        os.unlink(fn_path)
    return out.stdout + out.stderr


def test_the_function_is_actually_extracted():
    """Guards the harness itself.

    The macOS failures were the extraction returning nothing, which every other
    test in this file then reported as "command not found" — a harness fault
    wearing the costume of a behaviour fault.
    """
    body = _extract_function("warn_if_behind")
    assert body.startswith("warn_if_behind()")
    assert body.rstrip().endswith("}")
    assert len(body.splitlines()) > 3, "extracted an empty or truncated function"


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A clone whose branch tracks an 'origin' that moves ahead."""
    origin, work = tmp_path / "origin", tmp_path / "work"
    origin.mkdir()
    _sh("git", "init", "-q", "-b", "main", str(origin))
    _sh("git", "config", "user.email", "t@e.com", cwd=origin)
    _sh("git", "config", "user.name", "T", cwd=origin)
    (origin / "f.txt").write_text("one")
    _sh("git", "add", "-A", cwd=origin)
    _sh("git", "commit", "-qm", "one", cwd=origin)
    _sh("git", "clone", "-q", str(origin), str(work))
    _sh("git", "config", "user.email", "t@e.com", cwd=work)
    _sh("git", "config", "user.name", "T", cwd=work)
    return work


def test_silent_when_up_to_date(repo):
    assert _call_notice(repo, repo).strip() == "", (
        "a current checkout must print nothing"
    )


def test_reports_when_behind(repo, tmp_path):
    origin = tmp_path / "origin"
    for i in range(2):
        (origin / "f.txt").write_text(f"more {i}")
        _sh("git", "add", "-A", cwd=origin)
        _sh("git", "commit", "-qm", f"c{i}", cwd=origin)
    _sh("git", "fetch", "-q", cwd=repo)

    out = _call_notice(repo, repo)
    assert "2 commit(s) behind" in out, f"no notice; got {out!r}"
    assert "never pulls" in out, "must say it will not fix this itself"
    assert "pull --ff-only" in out, "must say how to catch up"


def test_it_does_not_fetch_or_pull(repo, tmp_path):
    """The notice must never change the tree it is describing."""
    origin = tmp_path / "origin"
    (origin / "f.txt").write_text("moved")
    _sh("git", "add", "-A", cwd=origin)
    _sh("git", "commit", "-qm", "moved", cwd=origin)

    before = _sh("git", "rev-parse", "HEAD", cwd=repo).stdout
    remote_before = _sh("git", "rev-parse", "origin/main", cwd=repo).stdout
    _call_notice(repo, repo)

    assert _sh("git", "rev-parse", "HEAD", cwd=repo).stdout == before, (
        "the notice moved HEAD"
    )
    assert _sh("git", "rev-parse", "origin/main", cwd=repo).stdout == remote_before, (
        "the notice fetched — it must use refs already on disk so an offline "
        "or slow start costs nothing"
    )


def test_silent_outside_a_git_repo(tmp_path):
    """A release checkout or an extracted tarball must launch unchanged."""
    plain = tmp_path / "plain"
    plain.mkdir()
    assert _call_notice(plain, plain).strip() == ""


def test_silent_on_a_detached_head(repo):
    sha = _sh("git", "rev-parse", "HEAD", cwd=repo).stdout.strip()
    _sh("git", "checkout", "-q", sha, cwd=repo)
    assert _call_notice(repo, repo).strip() == "", (
        "a detached HEAD has no upstream to compare against"
    )


def test_the_launch_path_actually_calls_it():
    """A perfect notice nobody calls is the same as no notice.

    The other tests exercise warn_if_behind directly, so deleting its call from
    run_dir left every one of them green — which is exactly the shape of bug
    this whole file exists to prevent, one level up.
    """
    text = RUN_SH.read_text(encoding="utf-8")
    body = text[text.index("run_dir() {"):]
    body = body[:body.index("\n}")]
    assert "warn_if_behind" in body, (
        "run_dir launches the app without checking whether this checkout is "
        "behind — the notice exists but nothing invokes it"
    )


def test_the_notice_runs_before_the_exec():
    """After exec, nothing runs — order is the whole behaviour here."""
    text = RUN_SH.read_text(encoding="utf-8")
    body = text[text.index("run_dir() {"):]
    body = body[:body.index("\n}")]
    assert body.index("warn_if_behind") < body.index("exec "), (
        "the notice is placed after exec, so it can never print"
    )
