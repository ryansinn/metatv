"""Behavioral tests — details-pane resize fix + debounced layout persistence.

Two bugs are pinned here:

1. The details pane resize handle did nothing because ``DetailsPaneWidget``
   called ``setFixedWidth()`` (min==max), which a ``QSplitter`` cannot drag.
   The fix keeps a min/max *range* (300–500) but no fixed pin.

2. Each ``splitterMoved`` (one per drag pixel) wrote — and backed up — the whole
   config file, flooding disk dozens of times per second.  The fix debounces all
   splitter saves into a single ``config.save()`` ~500ms after the drag settles
   (``_schedule_layout_save`` → timer → ``_persist_layout_now``).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Bug 1 — details pane must be a resizable RANGE, not a fixed width
# ---------------------------------------------------------------------------

class _StubImageCache(QObject):
    """Minimal image cache carrying the two signals DetailsPaneWidget connects."""

    image_loaded = pyqtSignal(str, QPixmap)
    image_failed = pyqtSignal(str, str)

    def get_image_async(self, *a, **k):  # noqa: ANN002, ANN003
        pass

    def load_pixmap(self, *a, **k):  # noqa: ANN002, ANN003
        return None


def test_details_pane_is_resizable_range_not_fixed(qapp):
    """DetailsPaneWidget must expose a width *range*, not a pinned fixed width.

    A fixed width (min==max) makes the enclosing QSplitter handle inert.  We
    assert the pane keeps the intended 300–500 range and that min != max so the
    splitter can actually drag it.
    """
    from metatv.core.config import Config
    from metatv.gui.details_pane import DetailsPaneWidget

    dp = DetailsPaneWidget(Config(), _StubImageCache(), None)
    assert dp.minimumWidth() == 300
    assert dp.maximumWidth() == 500
    assert dp.minimumWidth() != dp.maximumWidth(), (
        "details pane must be drag-resizable (no setFixedWidth pin)"
    )


# ---------------------------------------------------------------------------
# Bug 2 — debounced single-write layout persistence
# ---------------------------------------------------------------------------

def _shell_window():
    """Thin MainWindow shell (no Qt/DB init) with mock splitters + config."""
    from metatv.gui import main_window as mw

    with patch.object(mw.MainWindow, "__init__", lambda self: None):
        win = mw.MainWindow.__new__(mw.MainWindow)

    win.config = MagicMock()

    main_sp = MagicMock()
    main_sp.sizes.return_value = [340, 900, 420]
    win.main_splitter = main_sp

    side_sp = MagicMock()
    side_sp.sizes.return_value = [100, 200, 300]
    win.sidebar_splitter = side_sp

    inner_sp = MagicMock()
    inner_sp.sizes.return_value = [180, 600]
    win._inner_splitter = inner_sp

    return win


def test_persist_layout_now_writes_config_exactly_once(qapp):
    """_persist_layout_now must set every field but call config.save() ONCE."""
    win = _shell_window()

    win._persist_layout_now()

    assert win.config.save.call_count == 1, (
        "all splitter sizes must be persisted in a single config write"
    )
    # Fields from each splitter were updated in-memory.
    assert win.config.sidebar_width == 340
    assert win.config.details_pane_width == 420
    assert win.config.details_pane_visible is True
    assert win.config.sidebar_section_sizes == [100, 200, 300]
    assert win.config.filter_panel_width == 180


def test_schedule_layout_save_debounces_does_not_write_synchronously(qapp):
    """_schedule_layout_save must defer the write to a timer, not save inline.

    Simulates a drag burst: many splitterMoved → many _schedule_layout_save
    calls → zero synchronous config writes, with a single-shot timer armed.  The
    timer→write half is covered by test_persist_layout_now_writes_config_exactly_once.
    """
    from PyQt6.QtCore import QTimer

    win = _shell_window()
    win._layout_save_debounce = QTimer()
    win._layout_save_debounce.setSingleShot(True)
    win._layout_save_debounce.setInterval(500)

    # A burst of drag signals (splitterMoved delivers (pos, index)).
    for px in range(25):
        win._schedule_layout_save(px, 1)

    assert win.config.save.call_count == 0, (
        "drag must not write config synchronously — it is debounced"
    )
    assert win._layout_save_debounce.isActive(), (
        "the debounce timer must be armed by _schedule_layout_save"
    )
