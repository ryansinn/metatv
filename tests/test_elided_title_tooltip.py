"""Ledger WIP-6: a shortened sidebar title shows in full on hover.

A sidebar row is mouse-transparent so its list item keeps clicks and selection,
which also means the title label's own full-title tooltip never receives the
hover — the item answers, and in Recommended its tooltip is reason · rating ·
genres with no title at all. The row now registers a filter on whichever view
hosts it, which prepends the full title to the item's tooltip when the title is
elided. These drive a real ``QHelpEvent`` through the viewport, so they cover
the hover path rather than the string helper alone.
"""

from __future__ import annotations

from unittest.mock import patch

from PyQt6.QtCore import QEvent, QSize
from PyQt6.QtGui import QHelpEvent
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QWidget,
)

from metatv.gui.chip_row import build_chip_row, row_title_label

_LONG = "The Extraordinarily Long Title Of A Film That Will Never Fit The Sidebar (2026)"


def _hover(view, index) -> str | None:
    """Send a tooltip event at *index*'s centre; return what was shown (None = Qt default)."""
    pos = view.visualRect(index).center()
    ev = QHelpEvent(QEvent.Type.ToolTip, pos, view.viewport().mapToGlobal(pos))
    with patch("metatv.gui.chip_row.QToolTip.showText") as shown:
        QApplication.sendEvent(view.viewport(), ev)
    return shown.call_args.args[1] if shown.called else None


def _list(qtbot, width: int, *, item_tip: str = "", wrap: bool = False, row_tip: str = ""):
    lst = QListWidget()
    qtbot.addWidget(lst)
    lst.resize(width, 120)
    item = QListWidgetItem()
    if item_tip:
        item.setToolTip(item_tip)
    row = build_chip_row(title=_LONG)
    if row_tip:
        row.setToolTip(row_tip)
    host = row
    if wrap:  # Watch Alerts mounts the built row inside its own widget
        host = QWidget()
        QHBoxLayout(host).addWidget(row)
    item.setSizeHint(QSize(0, row.sizeHint().height()))
    lst.addItem(item)
    lst.setItemWidget(item, host)
    lst.show()
    qtbot.waitExposed(lst)
    return lst, lst.indexFromItem(item), row


def test_elided_title_leads_the_item_tooltip(qtbot):
    lst, index, row = _list(qtbot, 160, item_tip="Because you liked Heat\nGenres: Crime")
    assert row_title_label(row).is_elided(), "fixture: the title must be shortened"
    assert _hover(lst, index) == f"{_LONG}\nBecause you liked Heat\nGenres: Crime"


def test_full_width_title_leaves_the_item_tooltip_alone(qtbot):
    lst, index, row = _list(qtbot, 1600, item_tip="Double-click to play")
    assert not row_title_label(row).is_elided(), "fixture: the title must fit"
    assert _hover(lst, index) is None


def test_wrapped_row_in_a_tree_gets_it_too(qtbot):
    """Watch Alerts: a QTreeWidget, and the chip row nested in a wrapper widget."""
    tree = QTreeWidget()
    qtbot.addWidget(tree)
    tree.setHeaderHidden(True)
    tree.resize(160, 120)
    item = QTreeWidgetItem(tree)
    item.setToolTip(0, "Airs tonight")
    host = QWidget()
    QHBoxLayout(host).addWidget(build_chip_row(title=_LONG))
    tree.setItemWidget(item, 0, host)
    tree.show()
    qtbot.waitExposed(tree)
    assert _hover(tree, tree.indexFromItem(item, 0)) == f"{_LONG}\nAirs tonight"


def test_wrapped_row_in_a_list(qtbot):
    lst, index, _row = _list(qtbot, 160, item_tip="Matched", wrap=True)
    assert _hover(lst, index) == f"{_LONG}\nMatched"


def test_row_tooltip_shows_when_the_item_has_none(qtbot):
    """Transfers put their tooltip on the transparent row, where it never showed."""
    lst, index, _row = _list(qtbot, 1600, row_tip="Downloading — 42%")
    assert _hover(lst, index) == "Downloading — 42%"


def test_title_alone_when_nothing_else_to_say(qtbot):
    lst, index, _row = _list(qtbot, 160)
    assert _hover(lst, index) == _LONG
