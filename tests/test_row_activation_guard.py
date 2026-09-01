"""Row activation has ONE wiring, and drift is a test failure.

``currentItemChanged`` does not fire when the clicked row is already current,
so a list wired with it alone cannot be re-opened once the details pane has
moved on. That mistake was made in **ten** places before anyone noticed, and
the owner hit it as: one search result, auto-highlighted, an unrelated film in
the details pane, and no click that would fix it.

Fixing ten call sites by hand is the pattern this project keeps paying for —
the ``refresh_theme`` sweep, the hand-listed test stubs, ``_SETTINGS_APPLIED_
HOOKS``. **An enumeration never sees what nobody remembered to add.** So this
guard is an AST walk, not a grep: any bare ``currentItemChanged.connect``
outside ``row_activation.py`` fails the suite, and the fix is to route through
``connect_row_activation``.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent / "metatv"
_ALLOWED = {"row_activation.py"}


def _bare_connections(path: pathlib.Path) -> list[int]:
    """Return line numbers of ``<x>.currentItemChanged.connect(...)`` calls."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:                       # pragma: no cover
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "connect"):
            continue
        inner = fn.value
        if isinstance(inner, ast.Attribute) and inner.attr == "currentItemChanged":
            hits.append(node.lineno)
    return hits


def test_no_module_wires_currentitemchanged_by_hand():
    offenders: list[str] = []
    for path in sorted(_ROOT.rglob("*.py")):
        if path.name in _ALLOWED:
            continue
        for line in _bare_connections(path):
            offenders.append(f"{path.relative_to(_ROOT.parent)}:{line}")

    assert not offenders, (
        "these wire currentItemChanged directly, so a re-click on the already-"
        "current row does nothing:\n  " + "\n  ".join(offenders) +
        "\n\nUse metatv.gui.row_activation.connect_row_activation(widget, handler)"
    )


def test_the_guard_can_actually_see_a_violation(tmp_path):
    """Mutation check: a guard that cannot fail is not a guard."""
    bad = tmp_path / "bad.py"
    bad.write_text("w = object()\nw.currentItemChanged.connect(h)\n")
    assert _bare_connections(bad) == [2]

    good = tmp_path / "good.py"
    good.write_text("connect_row_activation(w, h)\n")
    assert _bare_connections(good) == []


class TestTheHelperItself:

    def test_both_signals_reach_the_handler(self, qapp_row):
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        from metatv.gui.row_activation import connect_row_activation

        lw = QListWidget()
        for t in ("A", "B"):
            lw.addItem(QListWidgetItem(t))
        seen: list[str] = []
        connect_row_activation(lw, lambda cur, prev: seen.append(cur.text()))

        lw.setCurrentRow(0)                      # keyboard / programmatic
        assert seen == ["A"]
        lw.itemClicked.emit(lw.item(0))          # re-click the SAME row
        assert seen == ["A", "A"], (
            "a re-click on the current row was swallowed — the exact bug")

    def test_a_raising_handler_does_not_escape_the_click(self, qapp_row):
        """A click must not take the UI down if a handler misbehaves."""
        from PyQt6.QtWidgets import QListWidget, QListWidgetItem
        from metatv.gui.row_activation import connect_row_activation

        lw = QListWidget()
        lw.addItem(QListWidgetItem("A"))

        def _boom(cur, prev):
            raise RuntimeError("handler exploded")

        connect_row_activation(lw, _boom)
        lw.itemClicked.emit(lw.item(0))          # must not raise


@pytest.fixture(scope="module")
def qapp_row():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app
