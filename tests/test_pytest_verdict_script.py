"""The test-running script must keep the two properties it exists for.

Both were learned the same day. A full local suite duplicates the CI gate that
runs on every PR, and a grep of a pytest summary reported "1 failed, 8044
passed" as GREEN — twice. A script fixes those only while it still has them,
so they are asserted rather than trusted.
"""

import pathlib
import subprocess

SCRIPT = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "pytest_verdict.sh"


def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/pytest_verdict.sh is gone"
    assert SCRIPT.stat().st_mode & 0o111, "not executable"


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
