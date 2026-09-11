"""Behavioral tests for ``ScopedFilterBox`` (SEARCH-10) — real widget, real signals.

This is the ONE widget every hand-rolled search/filter ``QLineEdit`` was
consolidated into (see ``metatv/gui/scoped_filter_box.py`` and its census).
Every assertion here drives the ACTUAL widget rather than a shape/attribute
check: debounce timing via ``qtbot.wait``, the real clear (×) button via
``qtbot.mouseClick``, and real key events via ``qtbot.keyClick`` for Escape.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QToolButton

from metatv.gui import theme as _theme
from metatv.gui.scoped_filter_box import ScopedFilterBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _clear_button(box: ScopedFilterBox) -> QToolButton:
    buttons = box.findChildren(QToolButton)
    assert buttons, "no clear button found — setClearButtonEnabled(True) missing"
    return buttons[0]


def test_debounce_coalesces_a_burst_into_one_filter_changed(qapp, qtbot):
    """Three keystrokes inside the debounce window must fire filterChanged ONCE,
    with the LAST value — not once per keystroke."""
    box = ScopedFilterBox("Search…", debounce_ms=150)
    qtbot.addWidget(box)
    seen: list[str] = []
    box.filterChanged.connect(seen.append)

    box.setText("a")
    box.setText("ab")
    box.setText("abc")
    assert seen == [], "filterChanged fired before the debounce window closed"

    qtbot.wait(300)  # past the 150ms window, plus margin for slow CI runners

    assert seen == ["abc"], f"expected one coalesced emission, got {seen}"


def test_zero_debounce_emits_on_every_keystroke(qapp, qtbot):
    """debounce_ms=0 is the 'no debounce' case every non-recipe site uses —
    each keystroke must emit immediately, synchronously."""
    box = ScopedFilterBox("Filter…", debounce_ms=0)
    qtbot.addWidget(box)
    seen: list[str] = []
    box.filterChanged.connect(seen.append)

    box.setText("a")
    box.setText("ab")
    box.setText("abc")

    assert seen == ["a", "ab", "abc"], (
        f"debounce_ms=0 must emit per keystroke with no delay, got {seen}"
    )


def test_clear_button_fires_filter_cleared_once(qapp, qtbot):
    box = ScopedFilterBox("Search…", debounce_ms=0)
    qtbot.addWidget(box)
    box.show()
    box.setText("something")
    QApplication.processEvents()

    cleared = []
    box.filterCleared.connect(lambda: cleared.append(True))

    btn = _clear_button(box)
    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert box.text() == ""
    assert cleared == [True], f"expected filterCleared exactly once, got {cleared}"


def test_escape_on_non_empty_text_clears_and_emits_escaped(qapp, qtbot):
    box = ScopedFilterBox("Search…", debounce_ms=0)
    qtbot.addWidget(box)
    box.show()
    box.setText("something")

    escaped = []
    box.escaped.connect(lambda: escaped.append(True))

    box.setFocus()
    qtbot.keyClick(box, Qt.Key.Key_Escape)

    assert box.text() == "", "Escape on non-empty text must clear the box"
    assert escaped == [True], f"expected escaped() exactly once, got {escaped}"


def test_escape_on_empty_text_emits_escaped_and_propagates(qapp, qtbot):
    """Nothing to clear -> ``escaped`` still fires (the Watch Queue hides its
    find box on Escape whether or not there was text, as its pre-SEARCH-10
    QShortcut did), but the key is NOT consumed: it reaches the parent, so a
    dialog hosting the box still closes on Escape."""
    from PyQt6.QtWidgets import QWidget

    class _Host(QWidget):
        def __init__(self):
            super().__init__()
            self.escapes = 0

        def keyPressEvent(self, event):  # noqa: N802 (Qt override)
            if event.key() == Qt.Key.Key_Escape:
                self.escapes += 1
            super().keyPressEvent(event)

    host = _Host()
    qtbot.addWidget(host)
    box = ScopedFilterBox("Search…", debounce_ms=0, parent=host)
    host.show()
    assert box.text() == ""

    escaped = []
    box.escaped.connect(lambda: escaped.append(True))

    box.setFocus()
    qtbot.keyClick(box, Qt.Key.Key_Escape)

    assert escaped == [True], "Escape on an empty box must still emit escaped()"
    assert host.escapes == 1, (
        "Escape on an already-empty box must propagate to the parent"
    )

    box.setText("abc")
    qtbot.keyClick(box, Qt.Key.Key_Escape)
    assert box.text() == "" and escaped == [True, True]
    assert host.escapes == 1, "a consumed clear must not also reach the parent"


def test_the_role_sheet_is_applied_through_the_registry(qapp):
    """Styled via theme.style(), not a raw setStyleSheet — so it survives a
    live theme switch (docs/CRITICAL_RULES.md#styles-and-theme-tokens)."""
    before = _theme.registered_style_count()
    box = ScopedFilterBox("Search…")

    assert _theme.registered_style_count() == before + 1, (
        "constructing a ScopedFilterBox must register exactly one live style"
    )
    assert box.styleSheet() == _theme.SCOPED_FILTER_BOX


# ---------------------------------------------------------------------------
# select_all_on_click (SEARCH-11) — a click that RETURNS focus to the box
# selects its text, mirroring the keyboard shortcut's own selectAll().
# ---------------------------------------------------------------------------

def _build_focus_pair(qtbot):
    """A shown container with an ``other`` QLineEdit above a ScopedFilterBox
    placeholder — the shared fixture shape for the two tests below."""
    from PyQt6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

    w = QWidget()
    layout = QVBoxLayout(w)
    other = QLineEdit()
    layout.addWidget(other)
    qtbot.addWidget(w)
    return w, layout, other


def _focus_other_first(w, other, qtbot) -> None:
    """Get real focus onto *other* so a later click on the box is a genuine
    focus RETURN, falling back to ``activateWindow()`` when the offscreen
    platform doesn't hand out focus on ``show()`` alone."""
    w.show()
    qtbot.waitExposed(w)
    other.setFocus()
    try:
        qtbot.waitUntil(other.hasFocus, timeout=500)
    except Exception:
        QApplication.setActiveWindow(w)
        w.activateWindow()
        other.setFocus()
        qtbot.waitUntil(other.hasFocus, timeout=500)


def _click_box_letting_focus_land(box, qtbot) -> None:
    """Click *box* and make sure it ends up focused, even on an offscreen
    platform that doesn't always hand out a real WM focus transition on a
    plain ``mouseClick``. Falls back to driving the Qt events directly, which
    still exercises the mechanism under test (``focusInEvent`` arms the
    pending flag, ``mousePressEvent`` consumes it)."""
    from PyQt6.QtCore import QEvent
    from PyQt6.QtGui import QFocusEvent

    qtbot.mouseClick(box, Qt.MouseButton.LeftButton)
    if not box.hasFocus():
        box.focusInEvent(
            QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.MouseFocusReason)
        )
        qtbot.mouseClick(box, Qt.MouseButton.LeftButton)


def test_click_into_an_unfocused_box_selects_its_text(qapp, qtbot):
    """A click that RETURNS focus to the box selects its previous text
    (SEARCH-11) — the mouse twin of the keyboard shortcut's own
    ``selectAll()`` (``_shortcut_focus_search``): reached to start a NEW
    search far more often than to extend the last one. A second click while
    already focused only places the caret."""
    from PyQt6.QtCore import QPoint

    w, layout, other = _build_focus_pair(qtbot)
    box = ScopedFilterBox("p", select_all_on_click=True)
    layout.addWidget(box)
    _focus_other_first(w, other, qtbot)

    box.setText("batman")
    _click_box_letting_focus_land(box, qtbot)

    assert box.hasFocus()
    assert box.selectedText() == "batman"

    # Already focused: a second click only places the caret, it does not
    # re-select.
    qtbot.mouseClick(
        box, Qt.MouseButton.LeftButton, pos=QPoint(4, box.height() // 2)
    )
    assert box.selectedText() == ""


def test_a_default_box_click_does_not_select_all(qapp, qtbot):
    """Every other adopter keeps the default (``select_all_on_click=False``):
    a click just places the caret, same as any plain QLineEdit."""
    w, layout, other = _build_focus_pair(qtbot)
    box = ScopedFilterBox("p")
    layout.addWidget(box)
    _focus_other_first(w, other, qtbot)

    box.setText("batman")
    _click_box_letting_focus_land(box, qtbot)

    assert box.selectedText() == ""
