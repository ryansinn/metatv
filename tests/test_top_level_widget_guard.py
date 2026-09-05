"""Guard: `_top_level_widget_guard` (tests/conftest.py) actually fails a leak.

A leaked top-level widget can only be observed by tearing a test down, and
the fixture under test is itself autouse in THIS session — if we leaked a
widget directly in one of this file's own tests, our own copy of
``_top_level_widget_guard`` would fail that test for real, not hand us
anything to assert on. So this proves the mechanism with a REAL nested pytest
run (in-process, never a second ``pytest`` process on the suite — pytester's
``runpytest_inprocess``, the same tool pytest itself uses to test its own
plugins) against a throwaway test module that deliberately leaks a widget.

The nested run reuses the REAL fixture rather than a copy of it: this
session has already imported ``tests/conftest.py`` as the module
``tests.conftest`` (this project's pytest resolves module names by the
dotted path from rootdir, not a bare ``conftest`` — there is no
``tests/__init__.py``, but ``tests`` still works as a PEP 420 namespace
package since the repo root is on ``sys.path`` via ``python -m pytest``), so
the nested module below just does ``import tests.conftest as _rc`` and
rebinds ``_rc._top_level_widget_guard`` under its own name, which is enough
for pytest to treat it as an autouse fixture for that module (the same
mechanism any plugin uses to share a fixture).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tests.conftest as _rc

pytest_plugins = ["pytester"]


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

_top_level_widget_guard = _rc._top_level_widget_guard

_KEEP_ALIVE = []


def test_{name}(qtbot):
    w = QWidget()
    w.show()
    _KEEP_ALIVE.append(w)
"""


def _widget_addr(w):
    return _rc._widget_addr(w)


def _new_top_level_widgets(app, pre_ids):
    """Every top-level widget not present in ``pre_ids`` (see ``_widget_addr``)."""
    return [
        w
        for w in app.topLevelWidgets()
        if _widget_addr(w) not in pre_ids and _widget_addr(w) is not None
    ]


def test_an_unallowlisted_leak_fails(pytester, qapp):
    """A widget leaked by a test NOT in the allowlist fails that test."""
    pre_ids = {a for a in (_widget_addr(w) for w in qapp.topLevelWidgets()) if a is not None}
    old_allowlist = _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST
    _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = frozenset()
    try:
        pytester.makepyfile(test_case=_LEAK_BODY.format(name="leaks_unallowlisted"))
        result = pytester.runpytest_inprocess()
    finally:
        _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = old_allowlist
        destroy_widget = _rc.destroy_widget
        destroy_widget(*_new_top_level_widgets(qapp, pre_ids))

    # pytest.fail() raised from a fixture's post-yield code is a TEARDOWN
    # failure, which pytest reports as an "error" against the test, not a
    # "failed" — the test's own body passed; its teardown did not.
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(
        ["*New top-level widget(s) leaked past teardown*QWidget*"]
    )


def test_an_allowlisted_leak_is_recorded_not_failed(pytester, qapp):
    """A widget leaked by an ALLOWLISTED nodeid is recorded, never failed."""
    pre_ids = {a for a in (_widget_addr(w) for w in qapp.topLevelWidgets()) if a is not None}
    nodeid = "test_case.py::test_leaks_allowlisted"
    old_allowlist = _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST
    old_ran = set(_rc._LEAK_ALLOWLIST_RAN)
    old_leaking = set(_rc._LEAK_ALLOWLIST_STILL_LEAKING)
    _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = frozenset({nodeid})
    try:
        pytester.makepyfile(test_case=_LEAK_BODY.format(name="leaks_allowlisted"))
        result = pytester.runpytest_inprocess()
        assert nodeid in _rc._LEAK_ALLOWLIST_STILL_LEAKING, (
            "the allowlisted nodeid should have been recorded as still leaking"
        )
    finally:
        _rc._TOP_LEVEL_WIDGET_LEAK_ALLOWLIST = old_allowlist
        _rc._LEAK_ALLOWLIST_RAN = old_ran
        _rc._LEAK_ALLOWLIST_STILL_LEAKING = old_leaking
        destroy_widget = _rc.destroy_widget
        destroy_widget(*_new_top_level_widgets(qapp, pre_ids))

    result.assert_outcomes(passed=1, errors=0)


def test_no_leak_passes_cleanly(pytester, qapp):
    """A test that never creates a stray top-level widget is unaffected."""
    pytester.makepyfile(
        test_case="""
        def test_clean():
            assert True
        """
    )
    result = pytester.runpytest_inprocess()
    result.assert_outcomes(passed=1, errors=0, failed=0)
