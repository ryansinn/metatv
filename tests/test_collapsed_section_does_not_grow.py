"""A collapsed section is its header, whatever the splitter tries to give it.

Owner, 2026-09-02, with a screenshot of Watch Alerts and Favorites collapsed and
each eating most of the rail: *"minimize (header click) a section and then reduce
the size of a section around them and the header of the collapsed section grows
to consume the space that should have been reclaimed by other sections."*

Measured cause, not theorised. ``max_useful_height()`` is the ONLY thing that
stops the splitter handing a section more room, and it returned **1072** for a
collapsed Favorites — because ``content_widget.sizeHint()`` was still 1046.
**Hiding a widget does not change its size hint.** So for as long as a section
was collapsed its cap sat at the height it would need OPEN, and any pixels a
shrinking neighbour released went straight into it: 396px of empty panel under a
header, reproduced headless.

The owner's recollection that this arrived with Recordings and Downloads is
consistent with the mechanism rather than the cause — the defect predates them;
two more sections simply give the splitter more to redistribute, so it reaches
the collapsed one more often.

Both directions are asserted. "Collapsed stays small" is satisfiable by a change
that makes every section small, so the round trip back to expanded is here too.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize, Qt
from PyQt6.QtWidgets import QListWidgetItem, QSplitter, QWidget

from metatv.core.config import Config
from tests.conftest import destroy_widget

TALL = 900
ROW_PX = 37


@pytest.fixture
def rig(qapp, tmp_path):
    """Favorites over History over a plain sink, both populated.

    The sink is a bare QWidget for the reason recorded in
    ``test_section_content_cap``: a rig made only of capped sections has nowhere
    to put slack, so the splitter forces sizes and the test measures the rig.
    """
    from metatv.gui.sidebar.favorites import FavoritesSection
    from metatv.gui.sidebar.history import HistorySection

    config = Config(config_dir=tmp_path)
    splitter = QSplitter(Qt.Orientation.Vertical)
    fav = FavoritesSection(config, db=None)
    hist = HistorySection(config, db=None)
    splitter.addWidget(fav)
    splitter.addWidget(hist)
    splitter.addWidget(QWidget())
    splitter.resize(320, TALL)
    splitter.show()
    for _ in range(6):
        qapp.processEvents()

    for section, view, n in ((fav, fav.favorites_list, 28),
                             (hist, hist.history_list, 40)):
        for i in range(n):
            item = QListWidgetItem(f"row {i}")
            item.setSizeHint(QSize(200, ROW_PX))
            view.addItem(item)
        section.reapply_row_budget()
    for _ in range(6):
        qapp.processEvents()

    yield splitter, fav, hist
    destroy_widget(splitter)


def _settle(qapp, n=12):
    for _ in range(n):
        qapp.processEvents()


def test_a_collapsed_section_refuses_room_the_splitter_offers(qapp, rig):
    """The owner's gesture, and the assertion that fails against the old code."""
    splitter, fav, _hist = rig
    fav.toggle_collapse()
    _settle(qapp)
    assert fav.is_collapsed

    # The splitter hands it a large share — exactly what a shrinking neighbour
    # produces. Pre-fix this rendered 396px.
    splitter.setSizes([400, 200, 300])
    _settle(qapp)

    floor = fav.min_expanded_height()
    assert fav.height() <= floor, (
        f"a collapsed section RENDERS {fav.height()}px when offered room; "
        f"its header floor is {floor}px"
    )
    assert fav.max_useful_height() <= floor, (
        "the cap still reports the section's expanded height while collapsed, "
        "so nothing stops the splitter growing it"
    )


def test_the_space_goes_to_a_neighbour_instead(qapp, rig):
    """"...space that should have been reclaimed by other sections."

    The point is not that the collapsed one is small — it is that the pixels
    land somewhere useful.
    """
    splitter, fav, hist = rig
    before = hist.height()
    fav.toggle_collapse()
    _settle(qapp)
    splitter.setSizes([400, 200, 300])
    _settle(qapp)

    assert hist.height() > before, (
        f"History was {before}px and is {hist.height()}px — collapsing a "
        "sibling released nothing"
    )


def test_a_remembered_drag_height_does_not_leak_into_the_collapsed_answer(qapp, rig):
    """``_user_height`` is a height for the section OPEN.

    It is one of the two ways this grew, so the collapsed branch has to return
    BEFORE the max() that consults it — a fix placed after it would still be
    wrong for anyone who had ever dragged the section.
    """
    splitter, fav, _hist = rig
    fav.note_user_height(420)
    fav.toggle_collapse()
    _settle(qapp)

    assert fav.max_useful_height() <= fav.min_expanded_height()
    splitter.setSizes([400, 200, 300])
    _settle(qapp)
    assert fav.height() <= fav.min_expanded_height()


def test_expanding_gives_the_room_back(qapp, rig):
    """The property that breaks if "collapsed is small" is over-applied."""
    splitter, fav, _hist = rig
    fav.toggle_collapse()
    _settle(qapp)
    fav.toggle_collapse()
    _settle(qapp)

    assert not fav.is_collapsed
    splitter.setSizes([500, 200, 200])
    _settle(qapp)

    assert fav.height() > fav.min_expanded_height() * 3, (
        f"an expanded section is stuck at {fav.height()}px — the collapsed "
        "answer is being returned when it is open"
    )
    assert fav.max_useful_height() >= fav.HEADER_H + ROW_PX
