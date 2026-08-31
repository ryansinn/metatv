"""A hand-rolled clickable row can be operated without a mouse.

The componentization audit found collapsible sections hand-rolled in fourteen
places while ``CollapsibleHeader`` — which packages the pattern and documents
the lesson in its own docstring — had adopters only inside the details pane.

Two halves of that finding, verified separately:

* **The cursor half did not survive.** The audit said the QLabel-chevron rows
  had "no pointer cursor". They do: ``global_filter_dialog`` calls
  ``set_clickable(header)``, ``trail_map_view`` calls ``set_clickable(self)``,
  and ``epg_watchlist_mixin`` calls it on the count label. The chevron is a
  decorative hint on a row that is itself the target — the same shape
  ``CollapsibleHeader`` uses ("the whole row is the click target").
* **The keyboard half was real.** A row that reacts only to
  ``mousePressEvent`` cannot be reached by Tab or triggered by Space, while
  ``CollapsibleHeader`` — whose title is a real ``QPushButton`` — can.

The fix goes in the chokepoint that already owns "this is clickable" rather
than in fourteen hosts, so a host opts in with one keyword and writes no key
handling. It is opt-IN because focusability is not free: every clickable chip
and poster becoming a tab stop makes the tab chain unusable.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication, QWidget

from metatv.gui import cursor_affordance


class _Row(QWidget):
    """A hand-rolled clickable row: mouse handler only, exactly like the real ones."""

    def __init__(self) -> None:
        super().__init__()
        self.clicks = 0
        self.resize(120, 24)

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt override)
        self.clicks += 1


@pytest.fixture
def filt(qapp):
    """The app-level filter, installed as it is at startup."""
    return cursor_affordance.install(QApplication.instance())


def _press(widget: QWidget, key) -> None:
    QApplication.sendEvent(
        widget, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


@pytest.mark.parametrize("key", [Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_space_and_enter_activate_an_opted_in_row(filt, key):
    """The keys a QPushButton answers to, so a row standing in for one matches it."""
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    _press(row, key)
    assert row.clicks == 1


def test_an_opted_in_row_is_reachable_by_tab(filt):
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    assert row.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_activation_runs_the_widgets_own_mouse_handler(filt):
    """Synthesised as a real press+release, not by calling a named method.

    Hosts implement their toggle in ``mousePressEvent``, ``mouseReleaseEvent``,
    or a signal emitted from either. Delivering real events means every one of
    those keeps working without the host being changed.
    """
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    _press(row, Qt.Key.Key_Space)
    _press(row, Qt.Key.Key_Space)
    assert row.clicks == 2, "each activation must run the existing handler once"


def test_other_keys_are_left_alone(filt):
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    for key in (Qt.Key.Key_A, Qt.Key.Key_Down, Qt.Key.Key_Escape):
        _press(row, key)
    assert row.clicks == 0


def test_clickable_alone_does_not_make_a_tab_stop(filt):
    """The reason this is opt-in.

    Every clickable poster, chip and row becoming focusable would make the tab
    chain unusable, so plain ``set_clickable`` must not change focus policy.
    """
    row = _Row()
    cursor_affordance.set_clickable(row)
    assert row.focusPolicy() == Qt.FocusPolicy.NoFocus
    _press(row, Qt.Key.Key_Space)
    assert row.clicks == 0, "a mouse-only clickable must stay mouse-only"


def test_a_disabled_row_does_not_activate(filt):
    """Matches the cursor half: a disabled control offers nothing."""
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    row.setEnabled(False)
    _press(row, Qt.Key.Key_Space)
    assert row.clicks == 0


def test_clearing_clickability_clears_the_keyboard_flag(filt):
    """A widget that stops being clickable must stop being operable, both ways."""
    row = _Row()
    cursor_affordance.set_clickable(row, keyboard=True)
    cursor_affordance.set_clickable(row, False)
    _press(row, Qt.Key.Key_Space)
    assert row.clicks == 0
    assert not row.property(cursor_affordance.KEYBOARD_PROPERTY)


def test_the_collapsible_rows_the_audit_named_are_opted_in():
    """The three hosts, pinned by source so the opt-in cannot be quietly dropped."""
    import pathlib
    gui = pathlib.Path(__file__).resolve().parent.parent / "metatv" / "gui"
    for name, needle in [
        ("global_filter_dialog.py", "set_clickable(header, keyboard=True)"),
        ("trail_map_view.py", "set_clickable(self, keyboard=True)"),
        ("epg_watchlist_mixin.py", "set_clickable(count_lbl, keyboard=True)"),
    ]:
        source = (gui / name).read_text()
        assert needle in source, f"{name} no longer opts its collapsible row into keyboard use"
