"""One row height for the whole sidebar, at any app font.

Two rules were in play and only one section had the right one. Watch Alerts
sized its rows from the FONT'S LINE BOX (ascent + descent + leading) because
that is what stops a descender clipping — "Stargate SG-1" lost the tail of its
g before it did. Every other section sized its rows from whatever their
children summed to, which is a constant: 20px, whatever the font.

Below a 13px app font the two agree and nothing looks wrong. Above it they
part, and the sidebar renders Watch Alerts at 21-24px against everyone else's
pinned 20px — the difference the owner saw and named: "the watch alerts spacing
for the content item (not header) rows is the correct spacing ... and that row
spacing should be applied to the content in the other sections".

The floor now lives in ``chip_row``, where every sidebar row is already built,
and Watch Alerts reads it back instead of keeping a second copy.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QSize
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QApplication, QListWidget, QListWidgetItem

from metatv.gui.chip_row import (
    CHIP_LANG, CHIP_YEAR, build_chip_row, row_min_height,
)
from metatv.gui.sidebar.alerts_rows import _AlertRow

#: Sizes to sweep. 13 is where the two rules used to part company, so a test
#: that sampled one size could sit on either side of the split and prove
#: nothing; the range is what makes the assertion mean something.
FONT_SIZES = (12, 13, 14, 15, 16, 18)


@pytest.fixture
def app_font(qtbot):
    """Set the application font per size and put it back afterwards.

    The floor is measured off the LIVE app font, so a test that leaves the font
    changed silently re-sizes every widget in every test that runs after it.
    """
    app = QApplication.instance()
    original = QFont(app.font())

    def _set(px: int) -> None:
        font = QFont(original)
        font.setPixelSize(px)
        app.setFont(font)

    yield _set
    app.setFont(original)


def _rows():
    """One row per sidebar section, built the way that section builds it."""
    return {
        "recommended": build_chip_row(
            title="Dumb And Dumber 2",
            chips=((CHIP_YEAR, "2014"), (CHIP_LANG, "EN"))),
        "favorites": build_chip_row(title="Forever Knight",
                                    chips=((CHIP_LANG, "EN"),)),
        "history": build_chip_row(title="Conan"),
        "watch_alerts": _AlertRow("Programme", "8:46 PM", None,
                                  live=False, region="US"),
    }


def _painted_heights(qtbot, rows: dict) -> dict[str, int]:
    """What each row is PAINTED at once it is an item in a list.

    Through a real ``QListWidget`` with ``setSizeHint(row.sizeHint())``, which
    is the line every section actually writes. A widget's ``sizeHint`` alone
    would not have caught this: the floor was set with ``setMinimumHeight`` and
    a plain ``QWidget``'s hint comes from its layout and never consults the
    minimum, so it was read straight past.
    """
    view = QListWidget()
    qtbot.addWidget(view)
    view.resize(320, 400)
    order = list(rows)
    for key in order:
        row = rows[key]
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, row.sizeHint().height()))
        view.addItem(item)
        view.setItemWidget(item, row)
    view.show()
    qtbot.waitExposed(view)
    return {key: view.visualItemRect(view.item(i)).height()
            for i, key in enumerate(order)}


@pytest.mark.parametrize("px", FONT_SIZES)
def test_every_section_paints_its_rows_at_the_same_height(qtbot, app_font, px):
    """The assertion the owner asked for, and it is RED before the fix.

    A 1px residual is allowed and is not policy: a row whose CONTENT is taller
    than the floor is free to be taller, and Watch Alerts carries a fixed-width
    slot the others do not. What is forbidden is two different FLOORS, which is
    what produced the 4px gap.
    """
    app_font(px)
    heights = _painted_heights(qtbot, _rows())
    spread = max(heights.values()) - min(heights.values())
    assert spread <= 1, (
        f"at a {px}px app font the sidebar paints rows {spread}px apart: "
        f"{heights}"
    )


@pytest.mark.parametrize("px", FONT_SIZES)
def test_no_row_is_painted_below_the_shared_floor(qtbot, app_font, px):
    """The floor is the point — a row shorter than the line box clips."""
    app_font(px)
    floor = row_min_height()
    heights = _painted_heights(qtbot, _rows())
    for key, height in heights.items():
        assert height >= floor, (
            f"{key} paints {height}px at a {px}px font; the line box needs "
            f"{floor}px and a descender clips below it"
        )


def test_the_floor_follows_the_font(qtbot, app_font):
    """Not a constant. A cached floor sizes rows for whatever font happened to
    be loaded at import, which is exactly how one got pinned at 20px."""
    app_font(12)
    small = row_min_height()
    app_font(18)
    assert row_min_height() > small, (
        f"the floor did not move with the font: {small} at 12px, "
        f"{row_min_height()} at 18px"
    )


def test_alerts_no_longer_keeps_its_own_floor(qtbot):
    """The duplication that caused this, asserted structurally.

    A second copy of the rule is what let the two drift for as long as they
    did, so the absence of the copy is worth holding.
    """
    import inspect

    from metatv.gui.sidebar import alerts_rows

    source = inspect.getsource(alerts_rows._RowShell)
    assert "row_min_height()" in source, "the shared floor is not being used"
    assert "fontMetrics().height()" not in source, (
        "_RowShell is computing a line box of its own again"
    )
