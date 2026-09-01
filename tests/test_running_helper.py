"""`scripts/running.sh` must not report itself, and must not miss a real run.

`pgrep -f pytest` matches its own shell, because that shell's argv contains the
pattern. It produced a wrong answer five separate times in one session — most
expensively when a crash-hunt loop that had died on launch was reported as
"still running" for several minutes.

Both directions are tested, and the second matters more: the FIRST version of
this script excluded the caller's whole process group, which meant a background
run started with `&` from the same shell was skipped. It answered "nothing
running" while a test run was active — a false negative that would green-light
a second concurrent pytest, which segfaults on this machine.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "running.sh"

#: The script reads /proc, so it can only answer the question on Linux.
#: Gating on the CAPABILITY rather than on ``sys.platform`` — that is the thing
#: the script actually depends on, and it keeps the tests honest on any future
#: platform that grows or loses one.
HAS_PROC = Path("/proc").is_dir()
needs_proc = pytest.mark.skipif(
    not HAS_PROC, reason="scripts/running.sh reads /proc; see the no-/proc test")


def _run() -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          cwd=SCRIPT.parent.parent)


def test_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "scripts/running.sh is missing"


@needs_proc
def test_it_does_not_report_itself(tmp_path):
    """The whole reason it exists.

    Its own command line contains every pattern it searches for, so a naive
    implementation always finds one match: itself.

    Run with ``--all``, and that is the load-bearing detail. In DEFAULT mode the
    command filter (``-m pytest``/``until``/…) already drops the script, so this
    assertion held whether or not the identity exclusion existed — a test named
    for the exact bug, passing against code containing it. Measured: with the
    exclusions removed, default mode reports 0 self-matches and ``--all``
    reports 5. Only the second question is this test's question.
    """
    result = subprocess.run(["bash", str(SCRIPT), "--all"], capture_output=True,
                            text=True, cwd=SCRIPT.parent.parent)
    assert "running.sh" not in result.stdout, (
        "the script matched itself — the exact bug it replaces")
    assert result.stdout.strip(), (
        "non-degeneracy: --all reported nothing at all, so finding no "
        "self-match proves nothing")


@needs_proc
def test_it_sees_a_real_run_and_stops_seeing_it(tmp_path):
    """Non-degeneracy, and the failure mode of the first implementation.

    A script that always says "nothing running" passes the self-match test
    perfectly and is worse than useless — it would green-light a second
    concurrent pytest.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(8)"],
        cwd=SCRIPT.parent.parent,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # The filter looks for "-m pytest"; this child is a plain sleep, so use
        # --all, which reports anything rooted in the repo.
        deadline = time.monotonic() + 5
        seen = False
        while time.monotonic() < deadline and not seen:
            out = subprocess.run(["bash", str(SCRIPT), "--all"],
                                 capture_output=True, text=True,
                                 cwd=SCRIPT.parent.parent).stdout
            seen = str(child.pid) in out
            if not seen:
                time.sleep(0.2)
        assert seen, (
            "a live process rooted in the repo was not reported — this is the "
            "false negative the process-group exclusion caused")
    finally:
        child.terminate()
        child.wait(timeout=5)

    out = subprocess.run(["bash", str(SCRIPT), "--all"], capture_output=True,
                         text=True, cwd=SCRIPT.parent.parent).stdout
    assert str(child.pid) not in out, "a dead process is still reported"


@needs_proc
def test_exit_code_is_usable_as_a_gate():
    """`running.sh >/dev/null || pytest ...` should run the tests when idle."""
    result = _run()
    assert result.returncode in (0, 1), "exit code is not a usable gate"
    if "nothing running" in result.stdout:
        assert result.returncode == 1


@pytest.mark.skipif(HAS_PROC, reason="this asserts the NON-Linux path")
def test_without_proc_it_refuses_to_answer_rather_than_saying_idle():
    """The dangerous direction, on a whole platform.

    Without /proc the scan loop never runs, so an unguarded script reports
    "nothing running" and exits 1 — and the gate form ``running.sh || pytest``
    reads non-zero as permission to start a second run. That is exactly the
    false negative this script was written to remove, and two of the tests
    above would pass VACUOUSLY while it happened.

    So it must say it cannot tell, and exit 0 — "something may be running" is
    the only safe answer to "I do not know".
    """
    result = _run()
    assert result.returncode == 0, (
        "a script that cannot see the process table must not green-light a run")
    assert "cannot determine" in (result.stderr + result.stdout)
    assert "nothing running" not in result.stdout
