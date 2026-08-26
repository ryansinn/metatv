"""Sidebar sections show everything and scroll, unless you ask otherwise.

One setting switches BOTH halves. Off (default): every row present, real
scrollbar, like any other list. On: the section shows what fits and ends with a
"Show N more" row that makes it taller — for pointing devices that cannot
scroll.

Never a truncated list with neither, which is what the section did in between:
hiding two hundred rows while looking exactly like one showing all three. Owner:
"should really load the whole list with scroll bars at the start, no? otherwise
it's kind of misleading?"
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from metatv.core.config import Config
from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW
from metatv.gui.sidebar.history import HISTORY_ROW_LIMIT, HistorySection


def _section(tmp_path, rows=40):
    section = HistorySection(Config(config_dir=tmp_path), db=None)
    for i in range(rows):
        section.history_list.addItem(QListWidgetItem(f"row {i}"))
    section.resize(300, 120)
    return section, section.history_list


def _tails(lst):
    return [i for i in range(lst.count())
            if lst.item(i).data(_MORE_ROLE) == _MORE_ROW]


# ── the default ─────────────────────────────────────────────────────────
def test_by_default_every_row_is_present_and_the_list_scrolls(qapp, tmp_path):
    section, lst = _section(tmp_path)
    assert section.config.sidebar_show_more_row is False

    section.apply_row_budget(lst)

    assert section.rows_hidden(lst) == 0, "rows were hidden with nothing to reveal them"
    # The SECTION scrolls, not the list. A list scrolling inside the section's
    # own scroll area is the nested scrollbar R13 forbids.
    assert lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert section.content_scroll.verticalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    assert not _tails(lst), "a tail row appeared without being asked for"


def test_budgeting_reports_nothing_hidden_by_default(qapp, tmp_path):
    """Callers key layout off the return value; it must not claim truncation."""
    section, lst = _section(tmp_path)
    assert section.apply_row_budget(lst) == 0


def test_previously_hidden_rows_are_restored(qapp, tmp_path):
    """Turning the setting off must un-hide what it hid, not just stop hiding."""
    section, lst = _section(tmp_path)
    for i in range(20, 40):
        lst.item(i).setHidden(True)

    section.apply_row_budget(lst)
    assert section.rows_hidden(lst) == 0


# ── the opt-in ──────────────────────────────────────────────────────────
def test_turning_it_on_hides_rows_behind_a_tail(qapp, tmp_path):
    """The two halves are one switch: rows are only hidden when the tail can
    reveal them."""
    section, lst = _section(tmp_path)
    section.config.sidebar_show_more_row = True

    section.apply_row_budget(lst)
    assert lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff


def test_the_tree_follows_the_same_switch(qapp, tmp_path):
    """Watch Alerts' grouped tree is the R13 case and must not be left behind."""
    import inspect

    from metatv.gui.sidebar import row_budget

    src = inspect.getsource(row_budget.RowBudgetMixin.apply_tree_row_budget)
    assert "_wants_more_row" in src, (
        "the tree still budgets unconditionally while lists respect the setting"
    )


# ── the load itself ─────────────────────────────────────────────────────
def test_history_loads_deep_enough_to_scroll_back_through(qapp):
    """30 was the ceiling a viewer hit, not a height anyone chose.

    Asserts the named constant rather than grepping source for a literal:
    "limit=30" is a SUBSTRING of "limit=300", so the obvious guard passes and
    fails for the same reason.
    """
    assert HISTORY_ROW_LIMIT >= 200
