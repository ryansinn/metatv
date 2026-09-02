"""Sidebar sections show everything and scroll. There is no other mode.

There used to be a second one, behind ``sidebar_show_more_row``: hide the rows
that did not fit and end the list with a "Show N more" row that grew the section
by taking pixels from its neighbours. It was off by default — owner: *"should
really load the whole list with scroll bars at the start, no? otherwise it's
kind of misleading?"* — and it was kept on an argument written twice in
``row_budget.py``: *"wheeling the list reveals more (see eventFilter)"*.

**There was no eventFilter.** Budgeted rows were ``setHidden(True)``, so no
amount of scrolling could reach them; the tail row was the only way. The mode's
stated audience — people who cannot use a scroll wheel — was the one group it
failed. Removed 2026-09-02 on the owner's call: *"why not always show
everything"*.

This file is what stops it growing back, in three ways: the behaviour is
asserted, the setting is asserted absent, and the code is asserted free of the
machinery. The third matters because the first two would still pass against a
half-reverted version that hid rows with no way to reveal them.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

import pytest

from metatv.core.config import Config
from metatv.gui.sidebar.history import HISTORY_ROW_LIMIT, HistorySection
from tests.conftest import destroy_widget


@pytest.fixture
def section(qapp, tmp_path):
    """A parentless section, freed afterwards.

    ``deleteLater()`` alone is not enough — a leaked top-level is repainted by
    every later ``apply_theme()``, and one per test is what segfaulted a CI
    shard. The drain lives in ``tests/conftest.destroy_widget``.
    """
    made = []

    def build(rows=40):
        sec = HistorySection(Config(config_dir=tmp_path), db=None)
        for i in range(rows):
            sec.history_list.addItem(QListWidgetItem(f"row {i}"))
        sec.resize(300, 120)
        made.append(sec)
        return sec, sec.history_list

    yield build
    destroy_widget(*made)


def _hidden(lst):
    return sum(1 for i in range(lst.count()) if lst.item(i).isHidden())


def test_every_row_is_present_and_the_section_scrolls(section):
    section, lst = section()

    section.apply_row_budget(lst)

    assert _hidden(lst) == 0, "rows were hidden with nothing to reveal them"
    assert lst.count() == 40, "a marker row was appended to the list"
    # The SECTION scrolls, not the list. A list scrolling inside the section's
    # own scroll area is the nested scrollbar R13 forbids.
    assert lst.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert section.content_scroll.verticalScrollBarPolicy() == (
        Qt.ScrollBarPolicy.ScrollBarAsNeeded
    )
    # ...and the list is tall enough to hold what it is showing, or the section
    # would scroll past rows drawn on top of each other.
    assert lst.height() >= 40 * 1, "the list was not sized to its rows"


def test_rows_hidden_by_anything_else_are_restored(section):
    """Sizing a view is also what un-hides it — including after an upgrade.

    Someone running the old build with the setting ON has 20 hidden rows in
    their session the moment this version loads. They have to come back.
    """
    section, lst = section()
    for i in range(20, 40):
        lst.item(i).setHidden(True)

    section.apply_row_budget(lst)

    assert _hidden(lst) == 0


def test_the_setting_is_gone(qapp, tmp_path):
    """No config field, so nothing can turn a second behaviour back on."""
    config = Config(config_dir=tmp_path)
    assert not hasattr(config, "sidebar_show_more_row")


def test_the_budget_machinery_is_gone(qapp):
    """The names, not the behaviour — a half-revert would pass the tests above.

    Hiding rows again while leaving the tail out would satisfy "every row
    present" only until a section overflowed, which is exactly the state the
    owner called misleading.
    """
    import inspect

    from metatv.gui.sidebar import base, row_budget

    src = inspect.getsource(row_budget)
    for name in ("_wants_more_row", "_tail_text", "_can_grow", "_on_more_row_clicked",
                 "rows_hidden_total", "_MORE_ROW = ", "_MORE_ROLE = "):
        assert name not in src, f"{name} is back in row_budget.py"

    assert not hasattr(row_budget.RowBudgetMixin, "_wants_more_row")
    assert not hasattr(base.CollapsibleSection, "rows_hidden_total")

    from metatv.gui import main_window
    assert "_grow_sidebar_section" not in inspect.getsource(main_window), (
        "the splitter arithmetic that only the tail row used is back")


def test_history_loads_deep_enough_to_scroll_back_through(qapp):
    """30 was the ceiling a viewer hit, not a height anyone chose.

    Asserts the named constant rather than grepping source for a literal:
    "limit=30" is a SUBSTRING of "limit=300", so the obvious guard passes and
    fails for the same reason.
    """
    assert HISTORY_ROW_LIMIT >= 200
