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
    assert "Sports" in labels


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


def test_the_sports_chip_switches_to_the_sports_view(window):
    """The real host, not a stub: chip → switch → view shown → chip alone lit.

    Every piece of this wiring is a hand-edit in a different file — the spec
    tuple, the registration, the switch method, the toggle slot, and the
    deactivation branch — and a miss in any one of them fails only when a user
    clicks the chip. A stub host would not have caught a signal connected to a
    handler with the wrong arity either.

    Restores the previous view, per this module's fixture contract.
    """
    from metatv.gui.app_header import NAV_CHIP_SPECS

    previous = window.view_mode
    try:
        window.sports_chip.set_enabled(True)
        window.on_sports_view_toggle()

        assert window.view_mode == "sports"
        assert not window.sports_view.isHidden()
        assert window.stats_label.text() == "Sports"

        lit = [attr for attr, *_ in NAV_CHIP_SPECS
               if getattr(window, attr).is_enabled()]
        assert lit == ["sports_chip"], (
            f"chips lit while Sports is showing: {lit} — a chip missing from "
            "the deactivation list stays lit and nothing raises")
    finally:
        window.switch_to_list_view()
        window.view_mode = previous


def test_switching_away_hides_the_sports_view(window):
    """Two views drawn at once is what a missed hide looks like.

    Only the HIDING is asserted here. Deactivation is gated on
    ``view.isVisible()``, which is False for every child of a window this
    fixture never shows — the token behaviour is covered against a live view in
    ``test_sports_view.test_deactivate_invalidates_an_in_flight_result``.
    """
    previous = window.view_mode
    try:
        window.sports_chip.set_enabled(True)
        window.on_sports_view_toggle()
        assert not window.sports_view.isHidden()

        window.switch_to_list_view()
        assert window.sports_view.isHidden(), (
            "the view stayed visible behind the channel list")
    finally:
        window.view_mode = previous


def test_the_events_chip_switches_to_the_events_view(window):
    """The real host — six hand-edits in five files, and a miss in any one of
    them fails only when a user clicks the chip."""
    from metatv.gui.app_header import NAV_CHIP_SPECS

    previous = window.view_mode
    try:
        window.events_chip.set_enabled(True)
        window.on_events_view_toggle()

        assert window.view_mode == "events"
        assert not window.events_view.isHidden()
        assert window.stats_label.text() == "Events"

        lit = [attr for attr, *_ in NAV_CHIP_SPECS
               if getattr(window, attr).is_enabled()]
        assert lit == ["events_chip"], f"chips lit alongside Events: {lit}"
    finally:
        window.switch_to_list_view()
        window.view_mode = previous


def test_switching_away_hides_the_events_view(window):
    """Only the hiding — this fixture never shows the window.

    Deactivation is gated on ``view.isVisible()``, which is False for every
    child of an unshown window, so the timer's stop cannot be observed here.
    It is asserted against a live view in
    ``test_events_view.test_the_timer_runs_only_while_the_view_is_active``, and
    the host path was checked by hand against a shown window.
    """
    previous = window.view_mode
    try:
        window.events_chip.set_enabled(True)
        window.on_events_view_toggle()
        assert not window.events_view.isHidden()

        window.switch_to_list_view()
        assert window.events_view.isHidden()
    finally:
        window.view_mode = previous
