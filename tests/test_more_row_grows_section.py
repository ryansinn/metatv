"""The "Show N more" row grows its section instead of opening Explore.

The duplicate the owner spotted: the tail row fired ``exploreClicked``, which is
exactly what the header's ``Explore →`` button already does — two controls, one
action, one of them hidden at the bottom of a list.

The rows were never capped, only unallocated. ``apply_row_budget``'s contract has
always been "show what fits, render more when the section gets taller", so
dragging the splitter handle already worked — and was undiscoverable. The tail
row now performs that drag. The sub-lists cannot scroll (nested scrollbars are
the jam the whole budget exists to remove), so growing in place is the only way
to reveal them without leaving the sidebar.
"""

from PyQt6.QtWidgets import QSplitter, QWidget
from PyQt6.QtCore import Qt

from metatv.gui.main_window import MainWindow
from metatv.gui.sidebar.base import _MORE_ROLE, _MORE_ROW


class _Panel(QWidget):
    """A splitter child that reports a floor, like a real section.

    A section declares TWO limits. ``preferred_expanded_height`` is the one
    automatic redistribution honours — growing a section must not take a
    neighbour below what it asks for — and it is what this double is here to
    model. ``min_expanded_height`` (the header-only hard floor, for user drags)
    is carried too so the double answers the whole contract; a double missing
    the preferred one reports a floor of 0 and every sibling looks like it has
    room to give.
    """

    def __init__(self, floor: int):
        super().__init__()
        self._floor = floor

    def preferred_expanded_height(self) -> int:
        return self._floor

    def min_expanded_height(self) -> int:
        return self._floor


class _Host:
    """Just enough MainWindow for _grow_sidebar_section to run against."""

    def __init__(self, splitter):
        self.__dict__["sidebar_splitter"] = splitter
        self.saves = 0

    def _schedule_layout_save(self):
        self.saves += 1


def _grow(host, section):
    return MainWindow._grow_sidebar_section(host, section)


def _splitter(sizes, floors, qapp):
    sp = QSplitter(Qt.Orientation.Vertical)
    panels = []
    for floor in floors:
        panel = _Panel(floor)
        sp.addWidget(panel)
        panels.append(panel)
    sp.resize(200, sum(sizes))
    sp.show()
    qapp.processEvents()
    sp.setSizes(sizes)
    qapp.processEvents()
    return sp, panels


# ── the redistribution ──────────────────────────────────────────────────
def test_growing_takes_from_siblings_and_conserves_total_height(qapp):
    sp, panels = _splitter([100, 300, 300], [80, 80, 80], qapp)
    target = panels[0]
    target.rows_hidden_total = lambda: 5
    target.CONTENT_ROW_H = 40
    host = _Host(sp)

    before = sum(sp.sizes())
    assert _grow(host, target) is True
    after = sp.sizes()

    assert sum(after) == before, "growing the section invented or lost height"
    assert after[0] > 100, "the section did not actually grow"
    assert after[1] >= 80 and after[2] >= 80, "a sibling was pushed below its floor"


def test_no_growth_when_every_sibling_is_already_at_its_floor(qapp):
    """The click must fall back rather than silently doing nothing."""
    sp, panels = _splitter([100, 80, 80], [80, 80, 80], qapp)
    target = panels[0]
    target.rows_hidden_total = lambda: 5
    target.CONTENT_ROW_H = 40
    assert _grow(_Host(sp), target) is False


def test_no_growth_when_nothing_is_hidden(qapp):
    sp, panels = _splitter([100, 300, 300], [80, 80, 80], qapp)
    target = panels[0]
    target.rows_hidden_total = lambda: 0
    target.CONTENT_ROW_H = 40
    assert _grow(_Host(sp), target) is False


def test_a_section_not_in_the_splitter_is_refused(qapp):
    sp, _panels = _splitter([100, 300], [80, 80], qapp)
    stray = _Panel(80)
    stray.rows_hidden_total = lambda: 5
    stray.CONTENT_ROW_H = 40
    assert _grow(_Host(sp), stray) is False


def test_growing_persists_the_new_layout(qapp):
    sp, panels = _splitter([100, 300, 300], [80, 80, 80], qapp)
    target = panels[0]
    target.rows_hidden_total = lambda: 5
    target.CONTENT_ROW_H = 40
    host = _Host(sp)
    _grow(host, target)
    assert host.saves == 1, "a resize the user asked for must survive a restart"


# ── the click routes to growth, not to Explore ─────────────────────────
def test_the_tail_click_grows_before_it_explores(qapp, tmp_path):
    from metatv.gui.sidebar.history import HistorySection
    from PyQt6.QtWidgets import QListWidgetItem

    section = HistorySection.__new__(HistorySection)
    grown, explored = [], []
    # Same signature as MainWindow._grow_sidebar_section, which is what the
    # section actually calls: (section, rows, *, probe). A one-argument
    # double raises TypeError from inside the production call instead of
    # exercising it.
    section.__dict__["grow_request"] = (
        lambda s, rows=None, *, probe=False: (grown.append(1), True)[1]
    )
    section.__dict__["_more_handler"] = lambda: explored.append(1)

    tail = QListWidgetItem("Show 4 more")
    tail.setData(_MORE_ROLE, _MORE_ROW)
    section._on_more_row_clicked(tail)

    assert grown, "the tail did not ask for room"
    assert not explored, "the tail still opened Explore, duplicating the arrow"


def test_the_tail_falls_back_to_explore_when_it_cannot_grow(qapp):
    from metatv.gui.sidebar.history import HistorySection
    from PyQt6.QtWidgets import QListWidgetItem

    section = HistorySection.__new__(HistorySection)
    explored = []
    section.__dict__["grow_request"] = lambda s, rows=None, *, probe=False: False
    section.__dict__["_more_handler"] = lambda: explored.append(1)

    tail = QListWidgetItem("Show 4 more")
    tail.setData(_MORE_ROLE, _MORE_ROW)
    section._on_more_row_clicked(tail)
    assert explored, "no room to grow AND no fallback — the click was dead"


def test_a_normal_row_click_is_ignored(qapp):
    from metatv.gui.sidebar.history import HistorySection
    from PyQt6.QtWidgets import QListWidgetItem

    section = HistorySection.__new__(HistorySection)
    touched = []
    section.__dict__["grow_request"] = (
        lambda s, rows=None, *, probe=False: touched.append(1)
    )
    section.__dict__["_more_handler"] = lambda: touched.append(1)
    section._on_more_row_clicked(QListWidgetItem("It's Always Sunny"))
    assert not touched


# ── the label stopped promising a departure ────────────────────────────
def test_the_tail_no_longer_reads_like_a_link_away(qapp):
    """The tail says what clicking it will DO.

    Asserted on the text the row produces, not by grepping the module source.
    The grep version pinned one exact construction expression and broke the
    moment the label gained its second form — while the behaviour it names was
    still correct. A source grep cannot tell those two apart.
    """
    from metatv.gui.sidebar.history import HistorySection

    # __new__'d like the two tests above it: _tail_text reads only
    # grow_request, so a full construction would add setup that proves nothing.
    section = HistorySection.__new__(HistorySection)

    # Room to take → the row offers to grow the section, with no arrow.
    section.__dict__["grow_request"] = lambda s, rows=None, *, probe=False: True
    label, tip = section._tail_text(6)
    assert label == "Show 6 more", label
    assert "→" not in label, (
        "the arrow says 'this leaves for somewhere else', which is the header "
        "button's job, not this one's"
    )
    assert "taller" in tip

    # No room left → the only way to see the rest IS the full view, and the
    # row says so rather than promising one thing and doing another.
    section.__dict__["grow_request"] = lambda s, rows=None, *, probe=False: False
    label, tip = section._tail_text(6)
    assert label.startswith("See all 6 more")
    assert "→" in label
    assert "full view" in tip
