"""Restored search text must still show the QLineEdit clear (×) button.

Regression: ``restore_search_state`` (and the VOD-rule restore) used
``blockSignals(True)`` + ``setText``, which suppresses the clear button — its show
is driven by ``textChanged`` — so on startup with a remembered search term the ×
did not appear until the user edited the box.  Fixed by guarding the handler
(``_set_search_text_silently`` + ``_suppress_search_handler``) instead of blocking
the signal.
"""
import pytest
from PyQt6.QtWidgets import QApplication, QLineEdit, QToolButton

from metatv.gui.main_window_channels import _ChannelListMixin


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _clear_visible(le: QLineEdit) -> bool:
    return any(b.isVisible() for b in le.findChildren(QToolButton))


class _Debounce:
    def __init__(self) -> None:
        self.started = 0

    def start(self) -> None:
        self.started += 1


def _harness() -> _ChannelListMixin:
    obj = _ChannelListMixin.__new__(_ChannelListMixin)
    obj.search_input = QLineEdit()
    obj.search_input.setClearButtonEnabled(True)
    obj.search_input.textChanged.connect(obj._on_search_text_changed)
    obj._bypass_tier1_filters = True
    obj._save_calls = 0
    obj._save_search_state = lambda: setattr(obj, "_save_calls", obj._save_calls + 1)
    obj._search_debounce = _Debounce()
    return obj


def test_blocksignals_path_hides_clear_button(qapp):
    """Documents the Qt root cause the fix avoids (blockSignals → × stays hidden)."""
    le = QLineEdit()
    le.setClearButtonEnabled(True)
    le.blockSignals(True)
    le.setText("hello")
    le.blockSignals(False)
    le.show()
    qapp.processEvents()
    assert not _clear_visible(le)


def test_set_search_text_silently_shows_clear_and_skips_handler(qapp):
    obj = _harness()
    obj._set_search_text_silently("hello")
    obj.search_input.show()
    qapp.processEvents()
    assert _clear_visible(obj.search_input), "clear × must show for restored text"
    assert obj._search_debounce.started == 0, "restore must not trigger the debounce"
    assert obj._save_calls == 0, "restore must not re-save state"
    assert obj.search_input.text() == "hello"


def test_live_edit_still_triggers_debounce(qapp):
    obj = _harness()
    obj.search_input.setText("user types")  # live edit — flag is off
    assert obj._search_debounce.started >= 1, "real edits must still debounce-load"
    assert obj._save_calls >= 1
