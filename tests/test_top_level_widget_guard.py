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
import os
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
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
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
