"""Behavioral tests for BackgroundRefreshMixin (B8-5).

The mixin is the single shared skeleton that Favorites/History/Queue compose instead of
each hand-rolling the executor + signal + try/except/emit-None + clear/dispatch. These
pin the skeleton directly: a failing load emits None (not a swallowed blank), None renders
a visible error row, and success dispatches to _populate_rows.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QListWidget

from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


class _FakeSection(BackgroundRefreshMixin, QObject):
    """Minimal section: real signal + list, scripted load, records populate/error calls."""
    _data_ready = pyqtSignal(object)

    def __init__(self, load_result=None, raise_exc=False):
        super().__init__()
        self._list = QListWidget()
        self._load_result = load_result
        self._raise_exc = raise_exc
        self.populated = None
        self.error_msg = None

    def _refresh_list(self):
        return self._list

    def _load_error_message(self):
        return "Couldn't load thing"

    def _load_rows(self):
        if self._raise_exc:
            raise RuntimeError("db boom")
        return self._load_result

    def _populate_rows(self, rows):
        self.populated = rows
        for r in rows:
            self._list.addItem(str(r))

    def show_load_error(self, lst, msg):   # provided by CollapsibleSection in real sections
        self.error_msg = msg
        lst.addItem(msg)


def test_bg_refresh_emits_none_on_load_failure(qapp):
    """A raising _load_rows must emit None — failure is signaled, never swallowed."""
    sec = _FakeSection(raise_exc=True)
    captured = []
    sec._data_ready.connect(captured.append)
    sec._bg_refresh()
    assert captured == [None]


def test_on_data_ready_none_shows_error_row_not_blank(qapp):
    sec = _FakeSection()
    sec._on_data_ready(None)
    assert sec.error_msg == "Couldn't load thing"
    assert sec.populated is None
    assert sec._list.count() == 1   # the visible error row


def test_on_data_ready_success_dispatches_to_populate(qapp):
    sec = _FakeSection()
    sec._on_data_ready(["a", "b", "c"])
    assert sec.populated == ["a", "b", "c"]
    assert sec.error_msg is None
    assert sec._list.count() == 3


def test_on_data_ready_clears_before_render(qapp):
    """Each render starts from a clean list (no torn/stale rows)."""
    sec = _FakeSection()
    sec._list.addItem("stale")
    sec._on_data_ready(["only"])
    assert sec._list.count() == 1
    assert sec._list.item(0).text() == "only"
