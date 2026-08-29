"""Every Tools menu entry must lead somewhere.

The menu carried two entries whose handlers logged a line and returned:

    def show_diagnostics(self):
        logger.info("Show diagnostics")

    def manage_filters(self):
        logger.info("Manage filters")

Owner: *"there's no point to having a diagnostics menu item that goes no where
and a stream diagnostic menu item, they should be merged or one removed."*

``manage_filters`` was the worse of the two, because it was not only a menu
entry: the details pane's version context menu emits ``manage_filters_requested``
straight into it, so that item had been inert as well — a click with no dialog,
no error and no log the user would ever see.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "metatv" / "gui" / "main_window.py"


def _function_body(name: str) -> list[ast.stmt]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.body
    raise AssertionError(f"{name} not found in main_window.py")


def _is_log_only(body: list[ast.stmt]) -> bool:
    """True when a body does nothing but a docstring plus logger calls."""
    for stmt in body:
        if isinstance(stmt, ast.Expr):
            value = stmt.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                continue  # docstring
            if (isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Attribute)
                    and isinstance(value.func.value, ast.Name)
                    and value.func.value.id == "logger"):
                continue  # a logger.* call
        return False
    return True


def test_the_dead_diagnostics_stub_is_gone():
    """Two diagnostics entries, one of which did nothing — the dead one went."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "show_diagnostics" not in names, (
        "show_diagnostics is back; the working entry is on_diagnose_clicked"
    )


def test_manage_filters_opens_the_real_dialog():
    """It must delegate to the one opener that also runs the refresh tail."""
    body = _function_body("manage_filters")
    assert not _is_log_only(body), (
        "manage_filters is a log-only stub again — the Tools entry AND the "
        "details pane's 'Manage Global Exclusions…' both dead-end into it"
    )
    calls = {
        node.func.attr
        for node in ast.walk(ast.Module(body=body, type_ignores=[]))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_open_global_filter_dialog" in calls, (
        "manage_filters must delegate to _open_global_filter_dialog, which is "
        "the path that also refreshes every dependent view afterwards"
    )


def test_manage_filters_is_reachable_on_the_real_class(qapp):
    """The delegation target must actually exist on MainWindow.

    An AST test alone would pass if the method were renamed out from under it.
    """
    from metatv.gui.main_window import MainWindow

    assert hasattr(MainWindow, "manage_filters")
    assert hasattr(MainWindow, "_open_global_filter_dialog"), (
        "manage_filters delegates to a method MainWindow does not have"
    )
    assert hasattr(MainWindow, "on_diagnose_clicked")


def test_manage_filters_actually_calls_through(qapp):
    """Execute it — the stub bug was invisible to every static check."""
    from metatv.gui.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    opened = []
    win._open_global_filter_dialog = lambda: opened.append(1)
    MainWindow.manage_filters(win)
    assert opened == [1], "manage_filters did not open anything"


@pytest.mark.parametrize("handler", ["manage_filters"])
def test_no_tools_handler_is_log_only(handler):
    """The shape guard: a handler that only logs is a dead menu entry."""
    assert not _is_log_only(_function_body(handler)), (
        f"{handler} does nothing but log — the menu entry that calls it is dead"
    )
