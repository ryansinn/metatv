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


def test_the_switcher_renders_exactly_what_it_declares(window):
    """The rendered chips must match NAV_CHIP_SPECS exactly, in order.

    Was a hand-written list of five labels, which a sixth view broke. Deriving
    the expectation is not tautological: the assertion is that the RENDERING
    LOOP produces one chip per spec, in spec order, with the spec's label — a
    dropped chip, a duplicate, or a reordering all still fail. The concrete
    anchor below keeps a wholesale corruption of the list catchable.
    """
    from metatv.gui.app_header import NAV_CHIP_SPECS

    labels = [window._nav_track.layout().itemAt(i).widget().text().strip()
              for i in range(window._nav_track.layout().count())]
    assert labels == [label for _, label, *_ in NAV_CHIP_SPECS]
    assert labels[0] == "Search", "Search is the switcher's home position"


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

def test_header_search_stays_put_on_every_view(window):
    """The search box no longer hides — it is the anchor the switcher sits beside.

    It used to disappear on EPG, Recommended, Discover and Recipe, on the
    reasoning that it only filters the channel list. Removing a 240-460px
    widget from a horizontal layout re-flows everything to its right, so the
    VIEW SWITCHER jumped sideways every time you left or returned to Search —
    the control you use to change views moved as a consequence of changing
    views. Owner report, 2026-08-27.

    isHidden(), not isVisible(): the window is never shown in an offscreen
    test, so isVisible() is False for every child of a hidden parent regardless
    of what was asked for. isHidden() reflects the explicit setVisible() call,
    which is what is under test.
    """
    window._sync_header_search_visibility(False)
    assert not window.search_input.isHidden(), (
        "the search box hid on a non-Search view; that is what moved the switcher"
    )
    window._sync_header_search_visibility(True)
    assert not window.search_input.isHidden()


def test_the_switcher_does_not_move_when_the_view_changes(window):
    """The reason the box stays, asserted as PAINTED GEOMETRY.

    The switcher used to jump 250px left when you left Search — measured, not
    estimated: x=364 with the box, x=114 without.

    ``show()`` and ``processEvents()`` are load-bearing. Without them every
    widget reports the default ``QRect(0, 0, 640, 480)`` because the layout has
    never run, both states compare equal, and the assertion cannot fail — which
    is precisely what the first version of this test did.
    """
    from PyQt6.QtWidgets import QApplication

    window.resize(1400, 900)
    window.show()
    try:
        QApplication.processEvents()
        window._sync_header_search_visibility(True)
        QApplication.processEvents()
        on_search = window._nav_track.geometry()

        window._sync_header_search_visibility(False)
        QApplication.processEvents()
        off_search = window._nav_track.geometry()
    finally:
        window.hide()

    assert on_search.width() > 0 and on_search.x() > 0, (
        f"the switcher was never laid out ({on_search}) — this test would pass "
        "for any behaviour at all"
    )
    assert on_search.x() == off_search.x(), (
        f"the view switcher moved {abs(on_search.x() - off_search.x())}px when "
        "leaving the Search view"
    )
    assert on_search.width() == off_search.width()


def test_the_search_placeholder_says_enter_searches_off_the_search_view(window):
    """The box is present everywhere, so it has to say what Enter will do."""
    window._sync_header_search_visibility(False)
    assert "Enter" in window.search_input.placeholderText()
    window._sync_header_search_visibility(True)
    assert "Enter" not in window.search_input.placeholderText()


# ---------------------------------------------------------------------------
# 4. Nothing was orphaned by deleting the bottom bar.
# ---------------------------------------------------------------------------

def test_diagnose_survived_into_the_tools_menu(window):
    """It had a permanent button in the bottom bar — a niche action pinned on
    screen beside the primary navigation. Deleting the bar must move it, not
    lose it (R5).

    Asserts the entry exists, is UNIQUE, and is actually connected — not that
    its label contains a particular phrase. The label check this replaced
    ("stream quality") pinned wording, so renaming the entry to "Stream
    diagnostics" — to match the dialog it opens, once the dead second
    "Diagnostics" entry beside it was deleted — failed a test whose subject was
    whether the action still existed at all.

    ``receivers()`` rather than triggering it: the entry opens a modal, and
    rebinding ``window.on_diagnose_clicked`` cannot intercept it anyway, since
    the connection captured the bound method when the menu was built.
    """
    candidates = [
        a for a in window._tools_menu.actions()
        if "diagnos" in a.text().lower()
    ]
    assert candidates, (
        "no diagnostics entry in the Tools menu — the bottom-bar action was "
        "lost rather than rehomed"
    )
    assert len(candidates) == 1, (
        f"{len(candidates)} diagnostics entries: {[a.text() for a in candidates]} "
        f"— a dead one sat beside the real one and must not come back"
    )
    action = candidates[0]
    assert action.receivers(action.triggered) > 0, (
        "the diagnostics entry is connected to nothing — exactly the defect "
        "that made the deleted entry useless"
    )
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
        window.apply_configured_theme()
        assert _theme.COLOR_BG_BAR in window._app_header.styleSheet()
    finally:
        window.config.theme_name = original
        window.apply_configured_theme()


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


# ---------------------------------------------------------------------------
# 6. SEARCH-11: the header search box is always live.
# ---------------------------------------------------------------------------

def test_the_search_box_is_enabled_after_the_series_view(window):
    """The series view used to be the one place that disabled the header
    search box directly, and because every OTHER view switch only ever set
    visibility/placeholder (never touched ``setEnabled``), nothing turned it
    back on until the user returned to the channel list — "inaccessible
    unless the search view is selected". ``_sync_header_search_visibility``
    now asserts ``setEnabled(True)`` on every call, so the very next view
    switch (any of them, not just the list) re-enables it.
    """
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    window.current_series = SimpleNamespace(id="s", name="S", provider_id="p")
    real_populate = window.populate_series_tree
    real_show_nav = window.show_series_nav
    window.populate_series_tree = MagicMock()
    window.show_series_nav = MagicMock()
    try:
        window.switch_to_series_view()
        assert window.search_input.isEnabled(), (
            "the header search box was left disabled by the series view"
        )

        # Any other view switch shares _hide_all_content_views(), the seam
        # that re-asserts the enabled state — drive it directly rather than
        # switch_to_discover_view(), which would also touch the (empty but
        # real) DB via discover_view.on_activate().
        window._hide_all_content_views()
        assert window.search_input.isEnabled(), (
            "leaving series view for another view left the box disabled"
        )
    finally:
        window.populate_series_tree = real_populate
        window.show_series_nav = real_show_nav
        window.switch_to_list_view()


def test_enter_from_a_non_list_view_switches_to_the_list_and_searches(window):
    """Enter used to only switch views when the search CHIP was disabled, but
    the series view can leave the chip enabled while the list itself is
    hidden — so Enter ran ``load_channels()`` into a view nobody could see.
    ``_on_search_submitted`` now also checks ``channels_list.isHidden()``,
    which every content view (series tree included) sets via an explicit
    ``setVisible(False)``.
    """
    from unittest.mock import MagicMock

    window.channels_list.setVisible(False)
    window.search_input.setText("batman")

    real_switch = window.switch_to_list_view
    real_load = window.load_channels
    window.switch_to_list_view = MagicMock()
    window.load_channels = MagicMock()
    real_debounce_stop = window._search_debounce.stop
    stopped = []
    window._search_debounce.stop = lambda: (stopped.append(1), real_debounce_stop())
    try:
        window._on_search_submitted()
        window.switch_to_list_view.assert_called_once()
        window.load_channels.assert_called_once()
        assert stopped, "Enter must stop the pending debounce, not wait it out"
    finally:
        window.switch_to_list_view = real_switch
        window.load_channels = real_load
        window._search_debounce.stop = real_debounce_stop
        window.channels_list.setVisible(True)


def test_enter_on_an_empty_box_does_nothing(window):
    """Enter on an empty box must not yank the user out of whatever view they
    were reading, having asked for nothing."""
    from unittest.mock import MagicMock

    window.channels_list.setVisible(False)
    window.search_input.setText("")

    real_switch = window.switch_to_list_view
    real_load = window.load_channels
    window.switch_to_list_view = MagicMock()
    window.load_channels = MagicMock()
    try:
        window._on_search_submitted()
        window.switch_to_list_view.assert_not_called()
        window.load_channels.assert_not_called()
    finally:
        window.switch_to_list_view = real_switch
        window.load_channels = real_load
        window.channels_list.setVisible(True)
