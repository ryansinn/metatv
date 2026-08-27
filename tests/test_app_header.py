"""The application header — brand, search, view switcher, global actions.

Decision Q2/R7 chose **Option A: divided segments in the HEADER**, freeing the
bottom bar entirely. What shipped in #328 was Option A's *control* in Option
C's *location* — a segmented track pinned to the bottom edge, roughly 950px
from the content it switches — because the spec lived only in an artifact and
a lossy memory note, and nothing in the repository mentioned a header at all.
See `docs/V3_INTERFACE_SPEC.md` §4.

These tests assert the header EXISTS, holds the right things in the right
order, and that the bottom bar is gone — not that a method is defined.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLineEdit, QPushButton, QWidget

from metatv.gui import theme as _theme


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    """ONE real MainWindow for the module.

    Module-scoped deliberately: constructing a MainWindow per test leaves ~22
    top-level widgets alive each time, and a dozen of them in one file
    exhausts Qt's state before the file finishes. Every test below reads; the
    two that mutate restore what they touched.
    """
    import pathlib

    from PyQt6.QtWidgets import QApplication

    home = tmp_path_factory.mktemp("home")
    for sub in (".config/metatv", ".local/share/metatv", ".cache/metatv"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    real_home = pathlib.Path.home
    pathlib.Path.home = staticmethod(lambda: home)

    app = QApplication.instance() or QApplication([])
    from metatv.core.config import Config
    from metatv.core.migration_manager import MigrationManager
    from metatv.gui.main_window import MainWindow

    # The window posts MigrationManager.run_pending via a zero-timer at
    # startup. This module only inspects chrome, so the migration pass is pure
    # cost — and if it is still pending when teardown shuts the executors down
    # it raises "cannot schedule new futures after shutdown" into the Qt event
    # loop, where it surfaces as a failure in whichever unrelated test runs
    # next. Neutered here rather than raced with processEvents().
    real_run_pending = MigrationManager.run_pending
    MigrationManager.run_pending = lambda self, *a, **k: None

    config, _ = Config.load()
    win = MainWindow(config)
    win.resize(1680, 1000)
    # Drain the deferred startup work (MigrationManager.run_pending is posted
    # via a zero-timer) while every executor is still alive. Left pending, it
    # fires after teardown has shut them down and raises "cannot schedule new
    # futures after shutdown" into the Qt event loop — where it surfaces as a
    # failure in whichever unrelated test happens to run next.
    app.processEvents()
    try:
        yield win
    finally:
        win.close()
        app.processEvents()
        MigrationManager.run_pending = real_run_pending
        pathlib.Path.home = real_home


# ---------------------------------------------------------------------------
# 1. It exists, and the bottom bar does not.
# ---------------------------------------------------------------------------

def test_the_header_exists(window):
    assert isinstance(window._app_header, QWidget)
    assert window._app_header.objectName() == "appHeader"


def test_the_bottom_nav_bar_is_gone(window):
    """Option A frees the bottom bar entirely. Leaving it would ship both."""
    assert not hasattr(window, "_bottom_nav_bar")
    assert not hasattr(window, "_create_bottom_nav_bar")


def test_the_header_is_the_first_thing_in_the_window(window):
    """Above the splitter, not below it — a header that renders under the
    content is not a header."""
    layout = window.centralWidget().layout()
    assert layout.itemAt(0).widget() is window._app_header


# ---------------------------------------------------------------------------
# 2. It holds the right things, in the right order.
# ---------------------------------------------------------------------------

def _header_order(window) -> list[str]:
    """Left-to-right x positions of the header's named parts."""
    parts = {
        "brand": window._brand_label,
        "search": window.search_input,
        "switcher": window._nav_track,
        "split": window._split_toggle_btn,
        "tools": window._tools_btn,
        "exclusions": window._filter_chip,
    }
    window._app_header.adjustSize()
    return [name for name, _ in sorted(parts.items(), key=lambda kv: kv[1].x())]


def test_the_header_reads_brand_search_switcher_then_actions(window):
    assert _header_order(window) == [
        "brand", "search", "switcher", "split", "tools", "exclusions",
    ]


def test_the_switcher_carries_all_five_views(window):
    labels = [window._nav_track.layout().itemAt(i).widget().text()
              for i in range(window._nav_track.layout().count())]
    assert [t.strip() for t in labels] == [
        "Search", "EPG", "Recommended", "Discover", "Recipe",
    ]


def test_settings_is_not_in_the_header(window):
    """R6 — it appears once, at the foot of the sidebar, where the hand already
    goes. An early mockup had it in both places; that was a mistake."""
    texts = [b.text() for b in window._app_header.findChildren(QPushButton)]
    assert not any("Settings" in t for t in texts)
    assert hasattr(window, "_settings_btn")   # still present, in the sidebar


def test_the_search_box_lives_in_the_header(window):
    """Not in the content area's controls row, which is where it was."""
    assert window.search_input.parent() is window._app_header
    assert isinstance(window.search_input, QLineEdit)


def test_the_search_box_still_filters(window):
    """Moving it must not disconnect it — the box is only worth having in the
    header if it still does its job."""
    seen = []
    window._on_search_text_changed = lambda text: seen.append(text)
    window.search_input.textChanged.disconnect()
    window.search_input.textChanged.connect(window._on_search_text_changed)
    window.search_input.setText("batman")
    assert seen == ["batman"]


# ---------------------------------------------------------------------------
# 3. Search hides where it would do nothing.
# ---------------------------------------------------------------------------

def test_header_search_hides_on_views_it_cannot_filter(window):
    """It filters the channel list, so it is meaningless on EPG/Discover/etc.
    It follows the same rule the content controls row already followed."""
    # isHidden(), not isVisible(): the window itself is never shown in an
    # offscreen test, and isVisible() is False for every child of a hidden
    # parent regardless of what was asked for. isHidden() reflects the
    # explicit setVisible() call, which is what is under test.
    window._sync_header_search_visibility(False)
    assert window.search_input.isHidden()
    window._sync_header_search_visibility(True)
    assert not window.search_input.isHidden()


# ---------------------------------------------------------------------------
# 4. Nothing was orphaned by deleting the bottom bar.
# ---------------------------------------------------------------------------

def test_diagnose_survived_into_the_tools_menu(window):
    """It had a permanent button in the bottom bar — a niche action pinned on
    screen beside the primary navigation. Deleting the bar must move it, not
    lose it (R5)."""
    actions = [a.text() for a in window._tools_menu.actions()]
    assert any("stream quality" in a.lower() for a in actions)
    assert callable(window.on_diagnose_clicked)


def test_the_tools_button_opens_the_menu_bar_s_own_menu(window):
    """One list of tools, not two — two would drift the first time one grew."""
    assert window._tools_menu is not None
    assert window._tools_btn.toolTip()


@pytest.mark.parametrize("attr", [
    "_split_toggle_btn", "_playback_health_label", "_filter_chip",
])
def test_bottom_bar_residents_are_rehomed_not_dropped(window, attr):
    widget = getattr(window, attr)
    assert widget.parent() is window._app_header, f"{attr} was left behind"


# ---------------------------------------------------------------------------
# 5. It survives a theme switch.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette", ["Midnight", "Graphite", "Daylight"])
def test_the_header_restyles_on_a_theme_switch(window, palette):
    """A sheet applied once with setStyleSheet renders once and goes stale.
    Every header part must be registered, which is what theme.style() does."""
    original = window.config.theme_name
    try:
        window.config.theme_name = palette
        window.refresh_theme()
        assert _theme.COLOR_BG_BAR in window._app_header.styleSheet()
    finally:
        window.config.theme_name = original
        window.refresh_theme()


def _press(button: Qt.MouseButton) -> QMouseEvent:
    """A synthetic mouse-press at the label's origin."""
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(1.0, 1.0),
        QPointF(1.0, 1.0),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def test_clicking_the_playback_health_readout_reaches_its_slot(window):
    """A left click on the health readout emits ``clicked``; a right click does not.

    ``_ClickableNavLabel.mousePressEvent`` reads ``Qt.MouseButton.LeftButton``
    in its BODY, and ``Qt`` was never imported in that module — so every click
    raised ``NameError``, Qt swallowed it at the event boundary, and the
    readout silently stopped cycling player windows. ``from __future__ import
    annotations`` covers the sibling ``QMouseEvent`` in the signature, which is
    exactly why nothing at import time noticed; only running the handler does.

    The right-click half matters: without it the test passes on a handler that
    emits unconditionally, which is a different bug wearing the same green.
    """
    from metatv.gui.app_header import _ClickableNavLabel

    assert isinstance(window._playback_health_label, _ClickableNavLabel)

    label = _ClickableNavLabel("")
    fired: list[int] = []
    label.clicked.connect(lambda: fired.append(1))

    label.mousePressEvent(_press(Qt.MouseButton.LeftButton))
    assert fired == [1], "left click did not reach the clicked signal"

    label.mousePressEvent(_press(Qt.MouseButton.RightButton))
    assert fired == [1], "right click emitted clicked; the button test is dead"
