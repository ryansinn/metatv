"""Adding a source URL behaves the same in both places it can be done.

Owner: *"pressing ENTER on the Url field of adding a new source should submit
/ add the url, the user shouldn't have to hit the button. then the cursor
should return to the url field, now empty... also the url entry field is above
the list of urls in the settings for existing sources and below it in the
initial setup, that's bad ux."*

All three were true, and the split is the interesting part: the **source
editor** already accepted Enter; the **initial-setup dialog** did not. The same
keystroke on the same kind of field gave two different outcomes depending on
which door the user came in through.

Entering several fallback URLs is the normal case for a source — that is the
whole point of having more than one — so the sequence has to be type, Enter,
type, Enter, without reaching for the mouse in between.

These tests drive the real widgets. They assert the ORDER of the widgets in the
layout, not merely that both exist, because "both are present" was already true
while they were in opposite orders.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QLineEdit, QListWidget

from metatv.core.database import Database


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def add_dialog(qapp, tmp_path):
    """The real dialog, wired like main_window_providers wires it."""
    from metatv.gui.dialogs import AddProviderDialog

    db = Database(f"sqlite:///{tmp_path / 'urls.db'}")
    db.create_tables()
    dlg = AddProviderDialog(None, MagicMock(), db, MagicMock())
    yield dlg
    dlg.deleteLater()
    db.close()


# ── Enter submits ───────────────────────────────────────────────────────────

def test_enter_adds_the_url_in_the_setup_dialog(add_dialog):
    """THE assertion. This did nothing before — only the button worked."""
    add_dialog.url_input.setText("http://example.com:8000")
    add_dialog.url_input.returnPressed.emit()

    assert add_dialog.url_list.count() == 1
    assert add_dialog.url_list.item(0).text() == "http://example.com:8000"


def test_the_field_is_empty_and_focused_for_the_next_url(add_dialog):
    """Type, Enter, type, Enter — no mouse in between."""
    add_dialog.url_input.setText("http://one.example:8000")
    add_dialog.url_input.returnPressed.emit()

    assert add_dialog.url_input.text() == "", "the field kept the URL just added"
    # focusWidget(), not hasFocus(): an unshown dialog has no active window, so
    # hasFocus() is False even when setFocus() was called correctly. This asks
    # the window which of ITS widgets holds focus, which is the real claim.
    assert add_dialog.focusWidget() is add_dialog.url_input, (
        "the caret did not return to the URL field"
    )


def test_several_urls_can_be_entered_in_a_row(add_dialog):
    """The normal case for a source with fallbacks."""
    for host in ("http://a.example", "http://b.example", "http://c.example"):
        add_dialog.url_input.setText(host)
        add_dialog.url_input.returnPressed.emit()

    assert [add_dialog.url_list.item(i).text() for i in range(3)] == [
        "http://a.example", "http://b.example", "http://c.example"
    ]


@pytest.mark.parametrize("text", ["", "   "])
def test_enter_on_an_empty_field_adds_nothing(add_dialog, text):
    add_dialog.url_input.setText(text)
    add_dialog.url_input.returnPressed.emit()

    assert add_dialog.url_list.count() == 0


def test_whitespace_around_a_url_is_trimmed(add_dialog):
    """Pasted URLs carry spaces and newlines."""
    add_dialog.url_input.setText("  http://spaced.example:8000  ")
    add_dialog.url_input.returnPressed.emit()

    assert add_dialog.url_list.item(0).text() == "http://spaced.example:8000"


# ── the two surfaces agree on layout ────────────────────────────────────────

def _index_of(container, cls) -> int:
    """Position of the first descendant of *cls* in the container's layout."""
    layout = container.layout()
    for i in range(layout.count()):
        item = layout.itemAt(i)
        w = item.widget()
        if w is not None:
            if isinstance(w, cls):
                return i
            if w.findChild(cls) is not None:
                return i
        sub = item.layout()
        if sub is not None:
            for j in range(sub.count()):
                sw = sub.itemAt(j).widget()
                if isinstance(sw, cls):
                    return i
    return -1


def test_the_entry_field_comes_before_the_list(add_dialog):
    """THE layout assertion — order, not mere presence.

    The setup dialog had the list first and the field underneath, while the
    source editor had the field on top. Both surfaces contained both widgets,
    so any "are they both there" check passed while the UX was inconsistent.
    """
    container = add_dialog.url_input.parentWidget()
    while container is not None and container.layout() is None:
        container = container.parentWidget()
    assert container is not None

    field_at = _index_of(container, QLineEdit)
    list_at = _index_of(container, QListWidget)

    assert field_at != -1 and list_at != -1, "expected both widgets in one container"
    assert field_at < list_at, (
        f"the URL field is at {field_at} and the list at {list_at} — the field "
        "must come first, as it does in the source editor"
    )


def test_the_source_editor_also_accepts_enter_and_refocuses():
    """Derived from the source, since building that tab needs a live provider.

    Checking the wiring rather than the widget keeps this honest about what it
    covers: that both surfaces connect Enter and return the caret.
    """
    import pathlib

    src = pathlib.Path("metatv/gui/provider_editor_tabs.py").read_text()
    assert "returnPressed.connect(self._add_url)" in src
    assert "_new_url_input.setFocus()" in src, (
        "the source editor clears the field but leaves the caret elsewhere"
    )
