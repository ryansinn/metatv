"""Layout menu — which panels are on screen, separate from Style (#284).

Style answers "what does this look like"; Layout answers "what is present".
Keeping them apart is what makes either menu predictable, and it is why the
filter-panel toggle moved out of Style: it is the third of three panels, and a
panel toggle living in a different menu from the other two is a small trap.

The load-bearing test here is ``test_ticks_are_read_from_the_splitter``. A panel
can also be collapsed by dragging its handle or by an Explore view auto-collapsing
it, neither of which passes through this menu — so a cached flag would make the
menu quietly lie about the screen.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import wire_filter_chip_host

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget

from metatv.gui.collapsible_splitter import CollapsibleSplitter
from metatv.gui.main_window import MainWindow


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def window(qapp):
    """A host with a REAL CollapsibleSplitter and the real menu handlers.

    Real splitter, not a mock: the behaviour under test is entirely about what
    the splitter actually does with a collapse request (minimum widths clamp,
    remembered sizes restore), which a mock would simply agree with.
    """
    host = QMainWindow()
    host.config = MagicMock()
    host.config.filter_section_visible = True

    splitter = CollapsibleSplitter(Qt.Orientation.Horizontal)
    for _ in range(3):
        splitter.addWidget(QWidget())
    splitter.setSizes([340, 800, 400])
    host.setCentralWidget(splitter)
    host.main_splitter = splitter
    host.resize(1540, 700)
    host.show()
    QApplication.processEvents()

    for name in (
        "_build_layout_menu", "_sync_layout_menu", "_toggle_sidebar_from_menu",
        "_toggle_details_from_menu", "_toggle_main_panel",
    ):
        setattr(host, name, getattr(MainWindow, name).__get__(host))
    host._SIDEBAR_PANEL = MainWindow._SIDEBAR_PANEL
    host._DETAILS_PANEL = MainWindow._DETAILS_PANEL
    host._toggle_filters_from_menu = MagicMock()
    # The Layout menu now carries "Filters as chips", and building it connects
    # that entry — so the host needs the chip-host methods MainWindow mixes in.
    wire_filter_chip_host(host)
    host.config.filter_ui_mode = "chips"
    host.save_splitter_sizes = MagicMock()
    host._build_layout_menu(host.menuBar())
    return host


def _menu(window, title):
    for action in window.menuBar().actions():
        if action.text().replace("&", "") == title:
            return action.menu()
    raise AssertionError(f"no {title!r} menu")


class TestMenuShape:

    def test_the_layout_menu_lists_all_three_panels(self, window):
        entries = {
            a.text().replace("&", "")
            for a in _menu(window, "Layout").actions()
            if not a.isSeparator()
        }
        assert entries == {
            "Sidebar", "Details pane", "Filter panel",
            # Below the separator: not a panel but a choice of which filter UI
            # those panels present — see docs/V3_INTERFACE_SPEC.md Q3.
            "Filters as chips",
        }

    def test_every_entry_is_checkable_and_has_a_tooltip(self, window):
        for action in _menu(window, "Layout").actions():
            if action.isSeparator():
                continue
            assert action.isCheckable(), f"{action.text()!r} is not a toggle"
            assert action.toolTip(), f"{action.text()!r} has no tooltip"

    def test_the_filter_toggle_left_the_style_menu(self, window):
        """One panel toggle in a different menu from the other two is a trap."""
        import inspect

        src = inspect.getsource(MainWindow._build_style_menu)
        assert "_filters_visible_action" not in src, (
            "Filter panel is still in Style — it belongs with the other panels"
        )


class TestToggling:

    def test_hiding_the_sidebar_actually_collapses_it(self, window):
        window._toggle_sidebar_from_menu()
        QApplication.processEvents()

        assert window.main_splitter.sizes()[0] == 0, (
            f"sidebar is {window.main_splitter.sizes()[0]}px, not collapsed — a "
            f"minimum width means a naive setSizes() only makes it narrower"
        )
        assert not window._sidebar_visible_action.isChecked()

    def test_showing_it_again_restores_the_users_width(self, window):
        window.main_splitter.setSizes([420, 720, 400])
        QApplication.processEvents()
        # Read back what Qt actually settled on rather than what was requested:
        # a splitter renormalises sizes to its own width, so asserting against
        # the requested number would fail for a reason unrelated to this
        # behaviour (CLAUDE.md — never pin an exact px).
        before = window.main_splitter.sizes()[0]
        assert before > 0

        window._toggle_sidebar_from_menu()      # collapse, remembering `before`
        window._toggle_sidebar_from_menu()      # restore
        QApplication.processEvents()

        restored = window.main_splitter.sizes()[0]
        assert restored > 0, "sidebar did not come back at all"
        assert abs(restored - before) <= 5, (
            f"restored to {restored}px, not the {before}px it was collapsed "
            f"from — a remembered width, not a default, is the point"
        )
        assert window._sidebar_visible_action.isChecked()

    def test_the_details_pane_toggles_independently(self, window):
        window._toggle_details_from_menu()
        QApplication.processEvents()

        sizes = window.main_splitter.sizes()
        assert sizes[2] == 0, "details pane did not collapse"
        assert sizes[0] > 0, "collapsing details also collapsed the sidebar"

    def test_repeated_toggling_does_not_get_stuck(self, window):
        """The one-way-toggle bug the filter panel shipped with (#280)."""
        for expected in (False, True, False, True):
            window._toggle_details_from_menu()
            QApplication.processEvents()
            assert window._details_visible_action.isChecked() is expected
            assert (window.main_splitter.sizes()[2] > 0) is expected

    def test_a_toggle_persists_the_new_widths(self, window):
        window._toggle_sidebar_from_menu()
        window.save_splitter_sizes.assert_called()


class TestTicksMatchReality:

    def test_ticks_are_read_from_the_splitter(self, window):
        """A panel dragged shut behind the menu's back must show as unticked.

        This is the whole reason _sync_layout_menu re-reads on open instead of
        trusting a stored flag.
        """
        window.main_splitter.collapse_panel(0)
        QApplication.processEvents()

        window._sync_layout_menu()

        assert not window._sidebar_visible_action.isChecked(), (
            "the menu still claims the sidebar is visible after it was "
            "collapsed by another path"
        )

    def test_a_restored_panel_ticks_back_on(self, window):
        window.main_splitter.collapse_panel(2)
        window._sync_layout_menu()
        assert not window._details_visible_action.isChecked()

        window.main_splitter.expand_panel(2)
        window._sync_layout_menu()
        assert window._details_visible_action.isChecked()

    def test_sync_survives_a_missing_splitter(self, qapp):
        """Called on a half-built window (the persistence test shells) it must
        not explode — PyQt raises RuntimeError, not AttributeError, so a
        hasattr guard would not save it."""
        host = QMainWindow()
        host.config = MagicMock()
        host.config.filter_section_visible = True
        host._sidebar_visible_action = MagicMock()
        host._details_visible_action = MagicMock()
        host._filters_visible_action = MagicMock()
        MainWindow._sync_layout_menu(host)      # must not raise


class TestExpandRestoresFullWidth:
    """The shrink bug this slice uncovered, pinned at the splitter (#284).

    ``expand_panel`` wrote the remembered width in without taking the space back
    from the panels that had absorbed it, so the request exceeded the splitter's
    width and Qt scaled everything down — the panel returned narrower each time.
    This is not menu-specific: the same path runs when the user clicks a
    splitter handle, so it was already happening before this menu existed.
    """

    @pytest.fixture()
    def splitter(self, qapp):
        s = CollapsibleSplitter(Qt.Orientation.Horizontal)
        for _ in range(3):
            s.addWidget(QWidget())
        s.resize(1200, 600)
        s.setSizes([300, 600, 300])
        s.show()
        QApplication.processEvents()
        return s

    def test_one_cycle_returns_the_same_width(self, splitter):
        before = splitter.sizes()[0]

        splitter.collapse_panel(0)
        QApplication.processEvents()
        splitter.expand_panel(0)
        QApplication.processEvents()

        assert abs(splitter.sizes()[0] - before) <= 2, (
            f"came back as {splitter.sizes()[0]}px instead of {before}px"
        )

    def test_repeated_cycles_do_not_erode_it(self, splitter):
        """The tell: without the fix each round shaved off another slice."""
        before = splitter.sizes()[0]

        for _ in range(5):
            splitter.collapse_panel(0)
            QApplication.processEvents()
            splitter.expand_panel(0)
            QApplication.processEvents()

        assert abs(splitter.sizes()[0] - before) <= 2, (
            f"eroded from {before}px to {splitter.sizes()[0]}px over 5 cycles"
        )

    def test_the_donor_panels_are_not_driven_to_zero(self, splitter):
        splitter.collapse_panel(0)
        QApplication.processEvents()
        splitter.expand_panel(0)
        QApplication.processEvents()

        assert all(s > 0 for s in splitter.sizes()), (
            f"restoring one panel collapsed another: {splitter.sizes()}"
        )
