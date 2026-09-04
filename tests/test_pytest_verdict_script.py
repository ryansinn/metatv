"""The test-running script must keep the two properties it exists for.

Both were learned the same day. A full local suite duplicates the CI gate that
runs on every PR, and a grep of a pytest summary reported "1 failed, 8044
passed" as GREEN — twice. A script fixes those only while it still has them,
so they are asserted rather than trusted.
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "pytest_verdict.sh"
REPO_PYTHON = ROOT / "scripts" / "repo_python.sh"
PRE_PUSH = ROOT / ".githooks" / "pre-push"


def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/pytest_verdict.sh is gone"
    assert SCRIPT.stat().st_mode & 0o111, "not executable"


def test_resolve_py_borrows_the_main_worktrees_venv(tmp_path):
    """``resolve_py()`` (scripts/repo_python.sh) is the one place a python
    interpreter is resolved (GATE-7): a hardcoded ``venv/bin/python`` relative
    to CWD is exit-127-wrong the moment CWD is a worktree with no venv
    symlink — two blocked pushes on 2026-09-03.

    A directory that is not even a git checkout must fail cleanly (no path
    printed); the repo root should resolve to its own venv when it has one.
    """
    assert REPO_PYTHON.exists(), "scripts/repo_python.sh is gone"

    # cwd=tmp_path: resolve_py's git-lookup failure branch falls back to a
    # bare "./venv/bin/python" (dirname of an empty _main_repo() is "."), so
    # the check is only meaningful relative to a CWD that is not itself the
    # main checkout — otherwise this repo's own venv would false-positive.
    not_a_checkout = subprocess.run(
        ["bash", "-c", f'source "{REPO_PYTHON}"; resolve_py "{tmp_path}"'],
        capture_output=True, text=True, timeout=30, cwd=tmp_path,
    )
    assert not_a_checkout.returncode != 0, (
        "resolve_py must fail outside any git checkout, not guess a path")
    assert not_a_checkout.stdout == "", (
        f"resolve_py printed a path for a non-checkout dir: {not_a_checkout.stdout!r}")

    venv_py = ROOT / "venv" / "bin" / "python"
    if not venv_py.exists():
        pytest.skip("this checkout has no venv/bin/python to resolve")
    repo_root = subprocess.run(
        ["bash", "-c", f'source "{REPO_PYTHON}"; resolve_py "{ROOT}"'],
        capture_output=True, text=True, timeout=30, cwd=ROOT,
    )
    assert repo_root.returncode == 0, repo_root.stderr
    assert repo_root.stdout.strip() == str(venv_py)


def test_pre_push_log_is_per_checkout():
    """Two worktrees pushing at once used to clobber one shared
    ``/tmp/prepush-guards.log`` — a linked worktree's git-dir is its own
    ``.git/worktrees/<name>/``, so keying the log off ``git rev-parse
    --git-dir`` makes it per-checkout instead."""
    body = PRE_PUSH.read_text(encoding="utf-8")
    assert "rev-parse --git-dir" in body
    assert "/tmp/prepush-guards.log" not in body, (
        "the shared /tmp log path is still hardcoded somewhere in the hook")


def test_it_refuses_a_full_suite_with_no_reason():
    """The whole point: running everything must be a deliberate act."""
    result = subprocess.run(
        [str(SCRIPT)], capture_output=True, text=True, timeout=60,
        cwd=SCRIPT.parent.parent, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 64, (
        f"expected the no-reason refusal (64), got {result.returncode}")
    assert "REFUSING" in result.stderr


def test_it_decides_on_the_exit_code_not_a_grep():
    """The false-GREEN came from parsing the summary. Assert it does not.

    Reading the script rather than running a failing suite: what matters is
    that the verdict branch tests ``$code``, and that no ``grep`` output is
    ever assigned to something the verdict depends on.
    """
    src = SCRIPT.read_text()
    assert 'if [ "$code" -eq 0 ]' in src, (
        "the verdict must branch on pytest's exit code")
    assert 'exit "$code"' in src, "the script must propagate pytest's exit code"
    verdict = src[src.index("# The verdict is the exit code"):]
    assert "grep" not in verdict, (
        "a grep appeared in the verdict section — that is the exact bug this "
        "script was written to prevent")


def test_ci_never_uses_a_gnu_only_xargs_flag():
    """`xargs -a` is a GNU extension; BSD xargs on macos-14 has no such flag.

    All four macOS shards died in seventeen seconds with a usage message the
    first time this ran. Cheap to assert, and invisible on Linux — which is the
    whole reason the matrix runs both platforms.
    """
    import pathlib

    import yaml

    ci_path = (pathlib.Path(__file__).resolve().parent.parent
               / ".github" / "workflows" / "ci.yml")
    spec = yaml.safe_load(ci_path.read_text())

    # Only the COMMANDS, and with shell comments stripped: the comment
    # explaining why `xargs -a` must not be used legitimately contains the
    # string, and a whole-file search cannot tell prose from a command. That
    # distinction has already produced one false failure in this session.
    for job in spec["jobs"].values():
        for step in job.get("steps", []):
            run = step.get("run")
            if not run:
                continue
            commands = "\n".join(
                line for line in run.splitlines()
                if not line.lstrip().startswith("#"))
            assert "xargs -a" not in commands, (
                f"step {step.get('name')!r} uses xargs -a, which is GNU-only "
                f"and fails on the macOS runners")


def test_the_shard_split_is_complete_and_disjoint():
    """Every test file in exactly one shard — silently dropping a file would
    make the gate pass by not running things."""
    import pathlib
    import subprocess
    import sys

    root = pathlib.Path(__file__).resolve().parent.parent
    seen: list[str] = []
    for shard in (1, 2, 3, 4):
        out = subprocess.run(
            [sys.executable, "scripts/ci_shard.py", "--shard", str(shard), "--of", "4"],
            capture_output=True, text=True, cwd=root, timeout=60,
        )
        assert out.returncode == 0, out.stderr
        seen.extend(out.stdout.split())

    expected = sorted(str(p.relative_to(root))
                      for p in (root / "tests").glob("test_*.py"))
    assert sorted(seen) == expected, (
        f"shards cover {len(seen)} files, tests/ has {len(expected)} — the "
        f"split is dropping or duplicating files")
