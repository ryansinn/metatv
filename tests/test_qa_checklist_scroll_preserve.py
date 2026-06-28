"""Regression test — QA checklist scroll position survives a rebuild.

The Re-test button rebuilds the checklist body and (via an async log snapshot)
rebuilds it a *second* time.  A deferred-only scroll restore snapped back to the
top.  _refresh_preserving_scroll now restores synchronously after forcing a
layout pass; this pins that the scroll position is preserved *immediately* after
the rebuild (no event-loop tick needed), which is what defeats the async re-save
race that caused the jump-to-top.
"""

from __future__ import annotations

import pytest
from PyQt6.QtWidgets import (
    QApplication,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Fake:
    """Plain holder so we exercise the real method without QMainWindow init."""


def test_refresh_preserving_scroll_restores_synchronously(qapp):
    from metatv.gui.qa_checklist_window import QAChecklistWindow

    shell = _Fake()

    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    body = QWidget()
    layout = QVBoxLayout(body)

    def _rebuild():
        # Mirror _refresh: clear then repopulate the SAME body (resets scroll).
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
        for i in range(60):
            lbl = QLabel(f"row {i}")
            lbl.setMinimumHeight(30)
            layout.addWidget(lbl)

    _rebuild()
    scroll.setWidget(body)
    scroll.resize(200, 200)
    scroll.show()

    shell._scroll = scroll
    shell._body = body
    shell._refresh = _rebuild  # stub the real rebuild

    qapp.processEvents()
    sb = scroll.verticalScrollBar()
    assert sb.maximum() > 0, "test setup must produce a scrollable range"

    sb.setValue(sb.maximum())
    target = sb.value()
    assert target > 0

    QAChecklistWindow._refresh_preserving_scroll(shell)

    # Capture the value BEFORE any event-loop tick — proves the restore is
    # synchronous (what defeats the async-retest re-save race).
    synchronous_value = sb.value()
    # Flush the deferred backstop timer while the widgets are still alive.
    qapp.processEvents()

    assert synchronous_value == target, (
        f"scroll must be preserved immediately after rebuild "
        f"(got {synchronous_value}, expected {target})"
    )
