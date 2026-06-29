"""Behavioral tests: nested flow containers actually wrap (height-for-width opt-in).

Regression context
------------------
The details-pane genre row, version chip rows ("Also available as" / filtered
variants) and the media-type row are flow-layout containers nested inside
``QVBoxLayout``s.  A ``QBoxLayout`` only consults a child's ``heightForWidth`` —
the value a flow layout uses to grow taller and wrap onto more rows — when the
child's *size policy* opts in (``setHeightForWidth(True)``); returning
``hasHeightForWidth() == True`` from the layout is NOT sufficient.

None of the containers opted in, so each laid its chips out in a single row that
clipped at the pane's right edge — the "Cowboy Bebop genres overflow off the
right edge" bug, flagged twice (entries 93 & 103) and never resolved by earlier
attempts that only touched the layout, not the container's policy.

The fix calls ``enable_height_for_width`` from every flow-layout constructor, so
nested chip rows wrap for free.  These tests pin both halves: the container opts
in, and the layout reports more height (more rows) when narrow than when wide.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.gui.details_versions import _FlowLayout
from metatv.gui.flow_layout import FlowLayout


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _chip(w: int = 100, h: int = 20) -> QWidget:
    c = QWidget()
    c.setFixedSize(w, h)
    return c


_FACTORIES = [
    pytest.param(lambda parent: FlowLayout(parent, spacing=4), id="FlowLayout"),
    pytest.param(
        lambda parent: _FlowLayout(parent, h_spacing=4, v_spacing=4),
        id="details_versions._FlowLayout",
    ),
]


@pytest.mark.parametrize("make_layout", _FACTORIES)
def test_flow_container_opts_into_height_for_width(qapp, make_layout):
    """Constructing a flow layout on a container enables height-for-width on the
    container's size policy — the missing opt-in that caused single-row clipping."""
    container = QWidget()
    make_layout(container)
    assert container.sizePolicy().hasHeightForWidth() is True


@pytest.mark.parametrize("make_layout", _FACTORIES)
def test_flow_wraps_to_more_rows_when_narrow(qapp, make_layout):
    """Six 100px chips: a wide width fits one row; a narrow width must wrap to more
    rows (greater heightForWidth) — proving the row wraps instead of overflowing."""
    container = QWidget()
    layout = make_layout(container)
    for _ in range(6):
        layout.addWidget(_chip(100, 20))

    wide = layout.heightForWidth(1000)   # 6*100 + gaps < 1000 → single row
    narrow = layout.heightForWidth(150)  # ~1 chip per row → many rows
    assert narrow > wide, f"narrow ({narrow}) must wrap taller than wide ({wide})"
