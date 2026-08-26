"""Scrolling a truncated sidebar list reveals more; the row is opt-in.

Sidebar lists deliberately have no scrollbar — a scroll area inside the
sidebar's own was the jam the row budget exists to remove — so a wheel gesture
over one used to do nothing at all, which reads as broken rather than complete.
Wheeling now grows the section.

The "Show N more" row is the same action as a clickable control, for pointing
devices that cannot scroll. Owner: "who doesn't have scrolling capabilities in
2026 … that way people without a scroll wheel can turn it on but normal humans
with modern interface devices don't have to see it." So it is OFF by default.
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


# ── the setting ─────────────────────────────────────────────────────────
def test_the_more_row_is_off_by_default(qapp, tmp_path):
    """A scroll wheel already does this; the row would be standing clutter."""
    section, _lst = _section(tmp_path)
    assert section.config.sidebar_show_more_row is False
    assert section._wants_more_row() is False


def test_turning_it_on_brings_the_row_back(qapp, tmp_path):
    section, _lst = _section(tmp_path)
    section.config.sidebar_show_more_row = True
    assert section._wants_more_row() is True


# ── the wheel ───────────────────────────────────────────────────────────
def test_wheeling_down_a_truncated_list_asks_for_room(qapp, tmp_path):
    section, lst = _section(tmp_path)
    asked = []
    section.grow_request = lambda s, rows=None, probe=False: (
        True if probe else (asked.append(rows), True)[1]
    )
    qapp.sendEvent(lst.viewport(), _wheel(-120))
    assert asked == [section.WHEEL_REVEAL_ROWS], (
        "a wheel notch should reveal a few rows, not jump to full height"
    )


def test_the_wheel_works_with_the_more_row_switched_off(qapp, tmp_path):
    """The row serves people who CANNOT wheel — gating the wheel on it would
    be exactly backwards, and an early return once did precisely that."""
    section, lst = _section(tmp_path)
    section.config.sidebar_show_more_row = False
    asked = []
    section.grow_request = lambda s, rows=None, probe=False: (
        True if probe else (asked.append(rows), True)[1]
    )
    qapp.sendEvent(lst.viewport(), _wheel(-120))
    assert asked, "turning the row off also disabled scrolling"


def test_wheeling_up_never_grows(qapp, tmp_path):
    section, lst = _section(tmp_path)
    asked = []
    section.grow_request = lambda s, rows=None, probe=False: (
        True if probe else (asked.append(rows), True)[1]
    )
    qapp.sendEvent(lst.viewport(), _wheel(120))
    assert not asked


def test_wheeling_a_complete_list_is_left_alone(qapp, tmp_path):
    """Nothing hidden — the event must propagate untouched."""
    section, lst = _section(tmp_path, hidden=0)
    asked = []
    section.grow_request = lambda s, rows=None, probe=False: (
        True if probe else (asked.append(rows), True)[1]
    )
    qapp.sendEvent(lst.viewport(), _wheel(-120))
    assert not asked


def test_a_section_with_no_host_wiring_does_not_crash(qapp, tmp_path):
    section, lst = _section(tmp_path)
    qapp.sendEvent(lst.viewport(), _wheel(-120))   # no grow_request at all


# ── the label promises what will happen ────────────────────────────────
def test_the_label_says_grow_when_it_can_and_explore_when_it_cannot(qapp, tmp_path):
    """A row saying "Show N more" that opens another view instead is worse
    than either action alone — which is what the owner hit on the SECOND
    click, once the section had no room left to take."""
    section, _lst = _section(tmp_path)

    section.grow_request = lambda s, rows=None, probe=False: True
    assert section._tail_text(4)[0] == "Show 4 more"

    section.grow_request = lambda s, rows=None, probe=False: False
    label, tip = section._tail_text(4)
    assert "→" in label and "See all" in label
    assert "full view" in tip


def test_the_shrink_loop_relabels_through_the_helper(qapp):
    """The regression that caused the report: the loop that shrinks a tail by
    a row rewrote its text with a hardcoded old label, so a correct tail
    reverted to the old wording — and the old action's promise — as soon as
    the budget trimmed it."""
    import inspect

    from metatv.gui.sidebar import row_budget

    src = inspect.getsource(row_budget.RowBudgetMixin.apply_row_budget)
    assert "more  →" not in src, "the shrink loop is hardcoding a tail label again"
    assert src.count("self._tail_text(hidden)") >= 2, (
        "every place that writes the tail's text must go through _tail_text"
    )
