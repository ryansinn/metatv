"""An empty sidebar section is its header, not a guess at how big a list would be.

Owner, 2026-09-01, with a screenshot of the sidebar: *"recording and downloads
side panel; headers are oversized by default, they shouldn't grow beyond the
standard size, clicking on them gets them to conform to the proper size."*

Measured cause, not theorised: ``QAbstractItemView.viewportSizeHint()`` on an
EMPTY ``QListWidget`` does not return 0 — it returns a default viewport, 72px
here. ``fit_to_rows`` passed that straight through, so an empty section's
content measured 82px and ``max_useful_height()`` came out at **108px against a
28px floor** — about 80px of blank panel under a header reading "0".

The cap was working exactly as designed; it was being handed a fabricated
content height. So the fix is at the measurement, not the cap.

Both halves are asserted, because "empty is small" is trivially satisfiable by
a change that makes every section small: a populated section must still claim
its rows.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QListWidgetItem, QSplitter, QWidget

from metatv.core.config import Config
from tests.conftest import destroy_widget

TALL = 900     # room for a section to exceed its content if uncapped

#: Height given to each fake row. Deliberately NOT read from
#: ``CollapsibleSection.CONTENT_ROW_H``: the point is that the fit follows the
#: ITEMS' own size hints, so borrowing the class's number would let a section
#: that ignores its rows entirely still satisfy the assertion.
ROW_PX = 41


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _rig(qapp, tmp_path, factory):
    """One section in a splitter with far more room than it can fill.

    The sink is a plain QWidget for the reason recorded in
    ``test_section_content_cap``: a rig made only of capped sections has
    nowhere to put the slack, so the splitter forces sizes instead of
    honouring them, and the test then measures the container.
    """
    splitter = QSplitter(Qt.Orientation.Vertical)
    sec = factory(Config(config_dir=tmp_path), MagicMock())
    sink = QWidget()
    splitter.addWidget(sec)
    splitter.addWidget(sink)
    splitter.resize(300, TALL)
    splitter.show()
    for _ in range(4):
        qapp.processEvents()
    return splitter, sec


def _sections():
    from metatv.gui.sidebar.downloads import DownloadsSection
    from metatv.gui.sidebar.recordings import RecordingsSection
    return [
        pytest.param(RecordingsSection, id="recordings"),
        pytest.param(DownloadsSection, id="downloads"),
    ]


def _fill(qapp, sec, n):
    lst = sec.budgeted_list()
    lst.clear()
    for i in range(n):
        item = QListWidgetItem(f"Row {i}")
        item.setSizeHint(QSize(200, ROW_PX))
        lst.addItem(item)
    sec.reapply_row_budget()
    for _ in range(4):
        qapp.processEvents()
    return lst


@pytest.mark.parametrize("factory", _sections())
def test_an_empty_section_does_not_claim_a_list_it_does_not_have(
        qapp, tmp_path, factory):
    """The rendered height, not just the declared cap."""
    splitter, sec = _rig(qapp, tmp_path, factory)
    try:
        assert not sec.is_collapsed, "the rig must measure an EXPANDED section"
        floor = sec.min_expanded_height()

        # The declared maximum. Margins around a zero-height list are the only
        # thing above the floor, so a small tolerance rather than an exact px:
        # a later spacing change must not turn this into a red gate.
        assert sec.max_useful_height() <= floor + 12, (
            f"an empty {type(sec).__name__} claims "
            f"{sec.max_useful_height()}px against a {floor}px floor"
        )

        # And what the user actually sees. This is the assertion that fails
        # against the pre-fix code (108 > 40).
        assert sec.height() <= floor + 12, (
            f"an empty {type(sec).__name__} RENDERS {sec.height()}px tall"
        )

        # It must be the empty-content path doing this, not the section simply
        # never asking for room: MIN_ROWS still wants three rows.
        assert sec.preferred_expanded_height() > floor + 12
    finally:
        destroy_widget(splitter)


@pytest.mark.parametrize("factory", _sections())
def test_a_populated_section_still_claims_room_for_its_rows(
        qapp, tmp_path, factory):
    """The property that would break if "empty is small" were over-applied."""
    splitter, sec = _rig(qapp, tmp_path, factory)
    try:
        lst = _fill(qapp, sec, 3)
        assert lst.height() >= 3 * ROW_PX, (
            f"three rows fit into {lst.height()}px")
        assert sec.max_useful_height() >= sec.HEADER_H + 3 * ROW_PX

        # ...and it gives the room back when the rows go away, which is the
        # round trip the owner's session actually performs.
        _fill(qapp, sec, 0)
        assert lst.height() == 0
        assert sec.max_useful_height() <= sec.min_expanded_height() + 12
    finally:
        destroy_widget(splitter)


def test_fit_to_rows_gives_no_height_to_a_view_with_nothing_visible(qapp):
    """The helper's own contract, tested where the budget cannot mask it.

    Driving this through a section would prove nothing: with the default
    settings ``apply_row_budget`` takes the ``_show_all_rows`` branch, which
    un-hides every row before measuring. The hidden-row case is real for the
    TREE path — ``alerts_epg`` folds a sub-group by hiding its top-level items
    rather than removing them — so the helper is asserted directly.
    """
    from PyQt6.QtWidgets import QListWidget, QTreeWidget, QTreeWidgetItem

    from metatv.gui.sidebar.row_budget import RowBudgetMixin

    empty_list = QListWidget()
    RowBudgetMixin.fit_to_rows(empty_list)
    assert empty_list.height() == 0

    hidden_list = QListWidget()
    for i in range(3):
        item = QListWidgetItem(f"Row {i}")
        item.setSizeHint(QSize(200, ROW_PX))
        hidden_list.addItem(item)
        item.setHidden(True)
    RowBudgetMixin.fit_to_rows(hidden_list)
    assert hidden_list.height() == 0

    # ...and a view with something to show is untouched, so the helper cannot
    # be satisfied by always answering zero.
    hidden_list.item(0).setHidden(False)
    RowBudgetMixin.fit_to_rows(hidden_list)
    assert hidden_list.height() >= ROW_PX

    folded_tree = QTreeWidget()
    group = QTreeWidgetItem(["Upcoming"])
    folded_tree.addTopLevelItem(group)
    group.addChild(QTreeWidgetItem(["A programme"]))
    group.setHidden(True)
    RowBudgetMixin.fit_to_rows(folded_tree)
    assert folded_tree.height() == 0

    group.setHidden(False)
    RowBudgetMixin.fit_to_rows(folded_tree)
    assert folded_tree.height() > 0

    destroy_widget(empty_list, hidden_list, folded_tree)
