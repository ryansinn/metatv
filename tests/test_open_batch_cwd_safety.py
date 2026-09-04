"""GATE-6: ``open_batch.sh`` must never write to the wrong repo/branch.

On 2026-09-02, ``scripts/merge_pr.sh <PR>`` was run twice while the shell's cwd
was an agent WORKTREE (a linked worktree with a feature branch checked out).
The remote merge worked fine — ``gh`` talks straight to the remote — but the
``open_batch.sh --push`` step it chains afterward committed the ``__version__``
bump onto the WORKTREE's checked-out feature branch instead of ``origin/main``.
The console printed "batch label: 0.84.0 -> 0.85.0" both times; origin's main
never moved, and the bump had to be redone by hand from the real checkout.

Root cause: ``open_batch.sh`` resolved its writable repo with
``git rev-parse --show-toplevel`` off its own ``SCRIPT_DIR``. That is
per-WORKTREE — it returns whichever worktree happens to contain the running
copy of the script file, not the shared main repo. ``merge_pr.sh`` invoked as
a relative path (``scripts/merge_pr.sh <PR>``) with cwd inside a worktree
resolves ITS ``SCRIPT_DIR`` into that worktree too, so the worktree's own
(otherwise identical) copy of ``open_batch.sh`` inherited the same
worktree-local ``SCRIPT_DIR`` and committed there. A ``git commit`` always
lands on whatever branch is checked out at the directory it targets — so the
false "batch label: X -> Y" success line was a real commit, just stranded on
an already-merged branch.

The fix anchors ``open_batch.sh`` to the SHARED main repo via
``git rev-parse --git-common-dir`` (mirroring ``verify_pr.sh``'s and
``merge_pr.sh``'s ``_main_repo``), which resolves to the one ``.git`` every
linked worktree shares regardless of which worktree's copy of the script ran —
and adds an explicit refusal when that shared repo does not have the trunk
checked out, so a future variant of the same mistake gets a loud error instead
of a silent commit to the wrong branch.

This drives the REAL script against a throwaway git sandbox (bare "origin" +
a main clone + one linked worktree on a feature branch) and asserts on what
actually landed where — reading the script would not have caught this; the
2026-09-02 incident happened with the (pre-fix) code in plain view.
"""

from __future__ import annotations

import os
import pathlib
import stat
import subprocess

_ROOT = pathlib.Path(__file__).resolve().parent.parent
OPEN_BATCH = _ROOT / "scripts" / "open_batch.sh"
# GATE-7: open_batch.sh sources this library for _main_repo/resolve_py, so a
# staged copy of the script needs its one dependency staged beside it.
REPO_PYTHON = _ROOT / "scripts" / "repo_python.sh"
MERGE_PR = _ROOT / "scripts" / "merge_pr.sh"


def _git(args: list[str], cwd: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], env=env,
        capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, (
        f"git -C {cwd} {' '.join(args)} failed:\n{result.stdout}\n{result.stderr}")
    return result


def _make_executable(path: pathlib.Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _write_repo_files(repo: pathlib.Path, version: str, opened_sha: str,
                       opened_id: int, latest_id: int) -> None:
    """The minimum ``open_batch.sh`` actually reads: ``__version__``, the two
    ``batch.py`` markers, and ``metatv.whats_new.latest_id()`` — no real
    WhatsNewEntry machinery is needed since the script never imports it."""
    pkg = repo / "metatv"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text(f'__version__ = "{version}"\n', encoding="utf-8")

    whats_new = pkg / "whats_new"
    whats_new.mkdir(exist_ok=True)
    (whats_new / "__init__.py").write_text(
        f"def latest_id() -> int:\n    return {latest_id}\n", encoding="utf-8")
    (whats_new / "batch.py").write_text(
        "from __future__ import annotations\n\n"
        f'OPENED_AT_SHA: str = "{opened_sha}"\n'
        f"OPENED_AT_ID: int = {opened_id}\n",
        encoding="utf-8")

    scripts = repo / "scripts"
    scripts.mkdir(exist_ok=True)
    dest = scripts / "open_batch.sh"
    dest.write_text(OPEN_BATCH.read_text(encoding="utf-8"), encoding="utf-8")
    _make_executable(dest)
    (scripts / "repo_python.sh").write_text(
        REPO_PYTHON.read_text(encoding="utf-8"), encoding="utf-8")


def _stub_gh(tmp_path: pathlib.Path) -> pathlib.Path:
    """A ``gh`` that always reports zero open PRs, so condition 3 ("batch
    finished") is satisfied deterministically — no network call, no auth."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    gh = bindir / "gh"
    gh.write_text("#!/usr/bin/env bash\necho 0\n", encoding="utf-8")
    _make_executable(gh)
    return bindir


def _make_env(tmp_path: pathlib.Path, stub_bin: pathlib.Path) -> dict[str, str]:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env["HOME"] = str(home)                       # isolate from the real ~/.gitconfig
    env["PATH"] = f"{stub_bin}:{env['PATH']}"      # our gh stub shadows the real one
    env["GIT_AUTHOR_NAME"] = "Sandbox"
    env["GIT_AUTHOR_EMAIL"] = "sandbox@example.com"
    env["GIT_COMMITTER_NAME"] = "Sandbox"
    env["GIT_COMMITTER_EMAIL"] = "sandbox@example.com"
    return env


def _build_sandbox(tmp_path: pathlib.Path):
    """bare origin.git <- clone (main, checked out) <- one linked worktree on
    a feature branch — the exact shape of the 2026-09-02 incident.

    Returns (origin, clone, worktree, env).
    """
    origin = tmp_path / "origin.git"
    clone = tmp_path / "clone"
    stub_bin = _stub_gh(tmp_path)
    env = _make_env(tmp_path, stub_bin)

    _git(["init", "--bare", "-q", "-b", "main", str(origin)], cwd=tmp_path, env=env)
    _git(["init", "-q", "-b", "main", str(clone)], cwd=tmp_path, env=env)
    _git(["config", "user.email", "sandbox@example.com"], cwd=clone, env=env)
    _git(["config", "user.name", "Sandbox"], cwd=clone, env=env)

    # First commit — its sha becomes OPENED_AT_SHA, so the second commit below
    # makes HEAD have "moved since the label was opened" (condition 1).
    (clone / ".gitkeep").write_text("", encoding="utf-8")
    _git(["add", "-A"], cwd=clone, env=env)
    _git(["commit", "-q", "-m", "initial"], cwd=clone, env=env)
    first_sha = _git(["rev-parse", "--short", "HEAD"], cwd=clone, env=env).stdout.strip()

    # Second commit: the stub app, opened at the FIRST commit with
    # OPENED_AT_ID=1 and latest_id()=42 — conditions 1 and 2 both owed.
    _write_repo_files(clone, version="0.1.0", opened_sha=first_sha, opened_id=1, latest_id=42)
    _git(["add", "-A"], cwd=clone, env=env)
    _git(["commit", "-q", "-m", "add stub app"], cwd=clone, env=env)

    _git(["remote", "add", "origin", str(origin)], cwd=clone, env=env)
    _git(["push", "-q", "-u", "origin", "main"], cwd=clone, env=env)
    _git(["symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
         cwd=clone, env=env)

    worktree = tmp_path / "clone-worktree"
    _git(["worktree", "add", "-b", "feature/agent-slice", str(worktree), "main"],
         cwd=clone, env=env)

    return origin, clone, worktree, env


def _run_open_batch(cwd: pathlib.Path, env: dict[str, str]) -> subprocess.CompletedProcess:
    # Relative path + cwd inside the target dir, exactly how the incident's
    # `scripts/merge_pr.sh <PR>` was typed — this is what makes BASH_SOURCE[0]
    # resolve relative to cwd rather than to some fixed install location.
    return subprocess.run(
        ["bash", "scripts/open_batch.sh", "--push"],
        cwd=cwd, env=env, capture_output=True, text=True, timeout=30)


def test_bash_syntax_is_valid():
    for script in (OPEN_BATCH, MERGE_PR):
        result = subprocess.run(["bash", "-n", str(script)],
                                 capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, f"{script.name}: {result.stderr}"


def test_cwd_in_worktree_bumps_main_not_the_worktree_branch(tmp_path):
    """The exact regression: cwd = agent worktree, feature branch checked out."""
    origin, clone, worktree, env = _build_sandbox(tmp_path)
    before_wt_head = _git(["rev-parse", "HEAD"], cwd=worktree, env=env).stdout.strip()

    result = _run_open_batch(worktree, env)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    # The bump commit landed on the CLONE's main —
    subject = _git(["log", "-1", "--format=%s"], cwd=clone, env=env).stdout.strip()
    assert subject.startswith("chore: open the"), (
        f"no bump commit on the main clone; got {subject!r}")
    clone_init = (clone / "metatv" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.2.0"' in clone_init

    # — and it reached origin (--push) —
    origin_main = _git(["rev-parse", "refs/heads/main"], cwd=origin, env=env).stdout.strip()
    clone_main = _git(["rev-parse", "refs/heads/main"], cwd=clone, env=env).stdout.strip()
    assert origin_main == clone_main, "the --push bump never reached origin/main"

    # — while the worktree's feature branch is completely untouched.
    after_wt_head = _git(["rev-parse", "HEAD"], cwd=worktree, env=env).stdout.strip()
    assert after_wt_head == before_wt_head, (
        "the worktree's feature branch moved — the bump was stranded there, "
        "which is the exact 2026-09-02 incident")
    wt_init = (worktree / "metatv" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.1.0"' in wt_init, "the worktree's own files were rewritten"


def test_cwd_in_main_clone_is_unchanged_behavior(tmp_path):
    """Run FROM the main checkout: still bumps main, same as before the fix."""
    origin, clone, _worktree, env = _build_sandbox(tmp_path)

    result = _run_open_batch(clone, env)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"

    subject = _git(["log", "-1", "--format=%s"], cwd=clone, env=env).stdout.strip()
    assert subject.startswith("chore: open the")
    clone_init = (clone / "metatv" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "0.2.0"' in clone_init

    origin_main = _git(["rev-parse", "refs/heads/main"], cwd=origin, env=env).stdout.strip()
    clone_main = _git(["rev-parse", "refs/heads/main"], cwd=clone, env=env).stdout.strip()
    assert origin_main == clone_main


def test_a_feature_branch_in_the_main_clone_is_refused(tmp_path):
    """The main repo itself on the wrong branch: refuse, don't commit anywhere."""
    origin, clone, _worktree, env = _build_sandbox(tmp_path)
    _git(["checkout", "-q", "-b", "feature/oops"], cwd=clone, env=env)
    before_head = _git(["rev-parse", "HEAD"], cwd=clone, env=env).stdout.strip()
    before_origin_main = _git(["rev-parse", "refs/heads/main"], cwd=origin, env=env).stdout.strip()

    result = _run_open_batch(clone, env)

    assert result.returncode != 0, (
        f"expected a refusal, got exit 0:\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    combined = result.stdout + result.stderr
    assert "not the trunk" in combined, combined

    after_head = _git(["rev-parse", "HEAD"], cwd=clone, env=env).stdout.strip()
    assert after_head == before_head, "a commit landed despite the trunk not being checked out"
    after_origin_main = _git(["rev-parse", "refs/heads/main"], cwd=origin, env=env).stdout.strip()
    assert after_origin_main == before_origin_main, "origin/main moved despite the refusal"
