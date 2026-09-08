"""``FlowLayout`` hands its items back before its C++ half is destroyed.

``QLayout``'s C++ destructor calls ``takeAt(0)`` until it gets null — into the
Python object, which by then may be part-finalized. A Python-implemented layout
that does not drain itself first is the classic PyQt crash (Qt's own FlowLayout
example drains in ``__del__`` for exactly this reason), and it is the shape
behind the intermittent CI teardown segfaults of 2026-09-07/08: the details
pane's tag chips live in a ``FlowLayout``, and both platforms crashed in the
same run right after a Tags-section test.
"""
from __future__ import annotations

import pytest

from metatv.gui.flow_layout import FlowLayout


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_layout_hands_its_items_back_before_it_dies(qapp):
    from PyQt6.QtWidgets import QPushButton, QWidget

    from tests.conftest import destroy_widget

    host = QWidget()
    layout = FlowLayout(host, spacing=4)
    for _ in range(3):
        layout.addWidget(QPushButton("chip", host))
    assert layout.count() == 3

    layout.__del__()
    assert layout.count() == 0, "the layout kept its items past its own teardown"

    destroy_widget(host)


def test_draining_twice_is_harmless(qapp):
    from PyQt6.QtWidgets import QPushButton, QWidget

    from tests.conftest import destroy_widget

    host = QWidget()
    layout = FlowLayout(host, spacing=4)
    layout.addWidget(QPushButton("chip", host))
    layout.__del__()
    layout.__del__()
    assert layout.count() == 0

    destroy_widget(host)
