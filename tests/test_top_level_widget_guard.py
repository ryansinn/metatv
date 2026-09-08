"""Guard: `_top_level_widget_guard` (tests/conftest.py) actually fails a leak.

A leaked top-level widget can only be observed by tearing a test down, and
the fixture under test is itself autouse in THIS session — if we leaked a
widget directly in one of this file's own tests, our own copy of
``_top_level_widget_guard`` would fail that test for real, not hand us
anything to assert on. So this proves the mechanism with a REAL nested pytest
run against a throwaway test module that deliberately leaks a widget.

The nested run is a SUBPROCESS (``pytester.runpytest_subprocess``), not the
in-process runner it used until 2026-09-07. In-process, the nested session
shared this session's ``QApplication``: its leaked widgets and deferred
deletes landed in OUR event queue, and pytest-qt's teardown ``_process_events``
then segfaulted — intermittently, depending on which Qt test ran just before
this file (three CI shards on three PRs, one local reproduction). A guard that
shares a process with the thing it guards is order-dependent; a subprocess is
not, at the cost of a second interpreter start per case.

The nested module reuses the REAL fixture rather than a copy of it: the repo
root goes on the subprocess's ``PYTHONPATH`` so ``import tests.conftest`` works
there exactly as it does here (``tests`` is a PEP 420 namespace package), and
the module rebinds ``_rc._top_level_widget_guard`` under its own name, which
is enough for pytest to treat it as an autouse fixture for that module. The
allowlist is set INSIDE the nested module (module-level assignment on the
imported conftest), since a subprocess cannot see this process's monkeypatch.
"""
import pathlib

pytest_plugins = ["pytester"]

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# A real, deliberately-uncleaned top-level widget. ``qtbot.addWidget()`` is
# NOT called, and nothing calls ``destroy_widget()`` — exactly the shape the
# guard exists to catch. Appending to a module-level list is what makes it
# survive past the nested test function's own scope (a bare local widget with
# no persistent reference is reclaimed by ordinary refcounting before any
# fixture teardown runs at all, so it would never actually reach the guard).
_LEAK_BODY = """
import tests.conftest as _rc
from PyQt6.QtWidgets import QWidget

_rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = frozenset({allowlist!r})
_top_level_widget_guard = _rc._top_level_widget_guard
_KEEP_ALIVE = []


def test_{name}(qtbot):
    _KEEP_ALIVE.append(QWidget())


def test_zz_after_the_leak():
    # Runs AFTER the leaking test's teardown, in the same process, so it can
    # see what the guard recorded there.
    recorded = "test_case.py::test_{name}" in _rc._LEAK_ALLOWLIST_STILL_LEAKING
    assert recorded == {expect_recorded!r}, (
        f"recorded={{recorded}} still_leaking={{sorted(_rc._LEAK_ALLOWLIST_STILL_LEAKING)}}"
    )
"""


def _run_nested(pytester, monkeypatch, source: str):
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytester.makepyfile(test_case=source)
    return pytester.runpytest_subprocess("-p", "no:cacheprovider")


def test_an_unallowlisted_leak_fails(pytester, monkeypatch):
    """A widget leaked by a test NOT in the allowlist fails that test."""
    result = _run_nested(pytester, monkeypatch, _LEAK_BODY.format(
        name="leaks_unallowlisted", allowlist=[], expect_recorded=False,
    ))
    # pytest.fail() raised from a fixture's post-yield code is a TEARDOWN
    # failure, which pytest reports as an "error" against the test, not a
    # "failed" — the test's own body passed; its teardown did not.
    result.assert_outcomes(passed=2, errors=1)
    result.stdout.fnmatch_lines(
        ["*New top-level widget(s) leaked past teardown*QWidget*"]
    )


def test_an_allowlisted_leak_is_recorded_not_failed(pytester, monkeypatch):
    """A widget leaked by an ALLOWLISTED nodeid is recorded, never failed."""
    nodeid = "test_case.py::test_leaks_allowlisted"
    result = _run_nested(pytester, monkeypatch, _LEAK_BODY.format(
        name="leaks_allowlisted", allowlist=[nodeid], expect_recorded=True,
    ))
    result.assert_outcomes(passed=2, errors=0)


def test_no_leak_passes_cleanly(pytester, monkeypatch):
    """A test that never creates a stray top-level widget is unaffected."""
    result = _run_nested(pytester, monkeypatch, """
        def test_clean():
            assert True
    """)
    result.assert_outcomes(passed=1, errors=0, failed=0)


# ---------------------------------------------------------------------------
# QT-2: ``_leak_allowlist_freshness_check`` (session-end companion, tests/
# conftest.py) reports stale allowlist candidates instead of failing on them,
# unless METATV_LEAK_GUARD_JUDGE opts a run into judging the list.
# ---------------------------------------------------------------------------
#
# Unlike the per-test ``_top_level_widget_guard`` above, this fixture is
# SESSION-scoped and its report comes out of ``pytest_terminal_summary`` — a
# real HOOK, not a fixture. Fixtures rebound onto a plain test module are
# picked up by pytest's fixture manager regardless of where they're defined
# (that's what ``_LEAK_BODY`` above relies on), but hook implementations are
# only discovered from files pytest registers as plugins — a conftest.py, not
# an arbitrary imported module. So this nested session gets its own REAL
# ``conftest.py`` (via ``pytester.makeconftest``) that imports the actual
# ``tests/conftest.py`` and rebinds both the fixture and the hook under their
# own names — same "reuse the real thing" approach as ``_LEAK_BODY``, just at
# the file pytest actually scans for hooks.

_STALE_CONFTEST = """
import tests.conftest as _rc
from PyQt6.QtWidgets import QApplication

# ``_top_level_widget_guard`` is a no-op when QApplication.instance() is
# None (nothing to snapshot) — true only for the FIRST Qt-touching test in a
# real session; every later one, including a plain non-Qt test, finds an
# instance already up. Recreate that condition here so the allowlist check
# actually runs for our plain (non-Qt) stale-candidate test below. MUST be
# held by a module-level name: an unassigned QApplication([]) is garbage
# collected immediately (nothing keeps its Python wrapper alive), which
# silently drops the underlying instance back to None.
_QAPP = QApplication.instance() or QApplication([])

_rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = frozenset({allowlist!r})

_top_level_widget_guard = _rc._top_level_widget_guard
_leak_allowlist_freshness_check = _rc._leak_allowlist_freshness_check
pytest_terminal_summary = _rc.pytest_terminal_summary
"""

# A clean test (no leaked widget) whose nodeid IS in the allowlist — exactly
# the "ran this session, did NOT leak" shape the freshness check reports as a
# stale candidate.
_STALE_TEST_BODY = """
def test_{name}():
    assert True
"""


def _run_stale_candidate(pytester, monkeypatch, name, *, judge=False, partial=False):
    monkeypatch.setenv("PYTHONPATH", str(_REPO_ROOT))
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    if judge:
        monkeypatch.setenv("METATV_LEAK_GUARD_JUDGE", "1")
    nodeid = f"test_case.py::test_{name}"
    pytester.makeconftest(_STALE_CONFTEST.format(allowlist=[nodeid]))
    pytester.makepyfile(test_case=_STALE_TEST_BODY.format(name=name))
    args = ["-p", "no:cacheprovider"]
    if partial:
        args.append(nodeid)
    result = pytester.runpytest_subprocess(*args)
    return result, nodeid


def test_stale_candidate_reported_not_failed_on_full_run(pytester, monkeypatch):
    """An ordinary full run reports a stale candidate; it does NOT fail.

    This is the macOS release build's exact shape: no file/nodeid on the
    command line, ``METATV_LEAK_GUARD_JUDGE`` unset. Before this fix, a
    stale-looking entry here was a hard `pytest.fail` — proven by
    ``test_stale_candidate_fails_under_judge_env_var`` below reproducing that
    same failure, opt-in only.
    """
    result, nodeid = _run_stale_candidate(pytester, monkeypatch, "stale_reported")
    result.assert_outcomes(passed=1, errors=0, failed=0)
    # The report must name the candidate AND say plainly it is not proof —
    # never phrase this so it could pass for "list judged and clean".
    result.stdout.fnmatch_lines(["*Leak allowlist freshness*"])
    result.stdout.fnmatch_lines([f"*{nodeid}*"])
    result.stdout.fnmatch_lines(["*NOT proof*"])


def test_stale_candidate_fails_under_judge_env_var(pytester, monkeypatch):
    """METATV_LEAK_GUARD_JUDGE=1 turns the same candidate into a hard failure.

    This is today's (pre-fix) behaviour on ``main``, now opt-in only: proves
    the judging path still exists and still names the offending nodeid.
    """
    result, nodeid = _run_stale_candidate(pytester, monkeypatch, "stale_judged", judge=True)
    # Same "teardown failure reports as an error" shape as the widget-leak
    # tests above — this fixture also raises pytest.fail from post-yield code.
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines([f"*stale entries*{nodeid}*"])


def test_stale_candidate_not_judged_on_partial_run(pytester, monkeypatch):
    """A file/nodeid on the command line still judges nothing — JUDGE or not.

    Same rule as before this fix (partial runs never judge); asserted here
    WITH the judge flag set to prove partial-run detection still wins.
    """
    result, nodeid = _run_stale_candidate(
        pytester, monkeypatch, "stale_partial", judge=True, partial=True
    )
    result.assert_outcomes(passed=1, errors=0, failed=0)
    result.stdout.no_fnmatch_line("*Leak allowlist freshness*")
