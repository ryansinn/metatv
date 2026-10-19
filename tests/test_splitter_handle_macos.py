"""Splitter handles are easy to grab on macOS: wider, with the resize cursor.

Owner, 2026-10-19: the column handles were "hard to grab on Mac, fine on
Linux". Linux keeps the 7px clickable handle; macOS gets a wider strip and the
resize arrows instead of the pointing hand.
"""
import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from metatv.core import runtime_env
from metatv.gui.collapsible_splitter import CollapsibleSplitter, CollapsibleSplitterHandle
from tests.conftest import destroy_widget


def _splitter():
    s = CollapsibleSplitter(Qt.Orientation.Horizontal)
    for _ in range(3):
        s.addWidget(QWidget())
    s.resize(900, 400)
    s.show()
    return s


@pytest.mark.parametrize("mac", [True, False])
def test_handle_grab_area_and_cursor(qapp, monkeypatch, mac):
    monkeypatch.setattr(runtime_env, "is_macos", lambda: mac)
    s = _splitter()
    qapp.processEvents()
    handle = s.handle(1)
    try:
        if mac:
            assert s.handleWidth() >= CollapsibleSplitterHandle.MAC_GRIP_THICKNESS
            assert handle.geometry().width() >= CollapsibleSplitterHandle.MAC_GRIP_THICKNESS
            assert handle.cursor().shape() == Qt.CursorShape.SplitHCursor
            assert handle.property("clickable") is False
        else:
            assert s.handleWidth() == CollapsibleSplitterHandle.GRIP_THICKNESS
            assert handle.cursor().shape() == Qt.CursorShape.PointingHandCursor
            assert handle.property("clickable") is True
    finally:
        destroy_widget(s)
