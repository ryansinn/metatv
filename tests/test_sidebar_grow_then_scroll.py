"""A sidebar list grows its section first, then scrolls — never dead-ends.

Owner: "now it's not loading the full lists, just the initial render. the whole
lists should load." Two separate ceilings were behind that.

A section can only grow until its neighbours reach their own floors. Past that,
rows stayed hidden with nothing to reveal them — and with the "Show N more" row
now off by default, the gesture simply stopped working.
"""

import pathlib
import tempfile

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QListWidgetItem

from metatv.core.config import Config
from metatv.gui.sidebar.history import HistorySection


def _section(tmp_path, *, hidden=4, total=12):
    section = HistorySection(Config(config_dir=tmp_path), db=None)
    lst = section.history_list
    for i in range(total):
        lst.addItem(QListWidgetItem(f"row {i}"))
    for i in range(total - hidden, total):
        lst.item(i).setHidden(True)
    lst.viewport().installEventFilter(section)
    return section, lst


def _wheel(dy):
    return QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def _can_grow(section, allowed):
    section.grow_request = lambda s, rows=None, probe=False: allowed


def test_growing_is_preferred_while_there_is_room(qapp, tmp_path):
    """The section opening up reads better than a scrollbar appearing."""
    section, lst = _section(tmp_path)
    grown = []
    section.grow_request = lambda s, rows=None, probe=False: (
        True if probe else (grown.append(rows), True)[1]
    )
    qapp.sendEvent(lst.viewport(), _wheel(-120))

    assert grown, "it scrolled instead of growing while there was room"
    assert not section._scrolling(lst)
    assert section.rows_hidden(lst) == 4, "growing should not reveal everything at once"


def test_it_hands_over_to_the_scrollbar_when_it_cannot_grow(qapp, tmp_path):
    """The dead end this exists to remove."""
    section, lst = _section(tmp_path)
    _can_grow(section, False)
    qapp.sendEvent(lst.viewport(), _wheel(-120))

    assert section._scrolling(lst)
    assert section.rows_hidden(lst) == 0, "rows stayed hidden with no way to reach them"
    assert (
        lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
    ), "the list revealed its rows but still cannot be scrolled"


def test_the_more_row_is_removed_when_scrolling_takes_over(qapp, tmp_path):
    """The tail promises to reveal rows that are already revealed."""
    from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW

    section, lst = _section(tmp_path)
    tail = QListWidgetItem("Show 4 more")
    tail.setData(_MORE_ROLE, _MORE_ROW)
    lst.addItem(tail)

    _can_grow(section, False)
    qapp.sendEvent(lst.viewport(), _wheel(-120))

    remaining = [
        lst.item(i).data(_MORE_ROLE) for i in range(lst.count())
    ]
    assert _MORE_ROW not in remaining


def test_budgeting_stops_once_a_list_is_scrolling(qapp, tmp_path):
    """A resize must not re-hide rows the viewer has already scrolled to."""
    section, lst = _section(tmp_path)
    _can_grow(section, False)
    qapp.sendEvent(lst.viewport(), _wheel(-120))

    assert section.apply_row_budget(lst) == 0
    assert section.rows_hidden(lst) == 0


def test_a_rebuild_returns_the_list_to_budgeting(qapp, tmp_path):
    """Otherwise a section stays expanded forever because it was scrolled once."""
    section, lst = _section(tmp_path)
    _can_grow(section, False)
    qapp.sendEvent(lst.viewport(), _wheel(-120))
    assert section._scrolling(lst)

    section.leave_scroll_mode(lst)
    assert not section._scrolling(lst)
    assert lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_history_loads_deep_enough_to_scroll_back_through(qapp):
    """30 rows was the ceiling a viewer hit, not a height anyone chose."""
    import inspect

    from metatv.gui.sidebar import history

    src = inspect.getsource(history.HistorySection._load_rows)
    assert "limit=30" not in src
    assert "limit=300" in src
