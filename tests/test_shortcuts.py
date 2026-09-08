"""KEYS-1 — the keyboard shortcuts, proven by pressing the keys.

Two things this file will not do, because both have shipped a green suite over
broken behaviour before:

* It does not assert that a string appears in a function body. Every claim here
  is made by installing the real registry on a real window and sending a real
  key event, then reading what changed.
* It does not use a ``MainWindow.__new__()`` skeleton. ``install()`` calls
  ``window.menuBar()`` and ``window.addAction()``, and a ``__new__``'d
  QMainWindow has no C++ object behind it — PyQt raises ``RuntimeError``, which
  reads like a Qt bug rather than a stale double. So the host below is a REAL
  ``QMainWindow`` that mixes in the REAL ``_MenuActionsMixin`` and the REAL
  ``_NavMixin``: every handler under test is the shipped one, and only the
  ``switch_to_*`` view bodies (which want the whole content area) are replaced
  with recorders.

The cheat-sheet's assertion is on rendered GEOMETRY, not on the presence of
labels: a two-column sheet whose columns rendered on top of each other, or
whose key column collapsed to nothing, would satisfy any "the text is there"
check and be unreadable on screen.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QLabel, QLineEdit, QMainWindow, QWidget

from metatv.gui import shortcuts as _shortcuts
from metatv.gui.app_header import NAV_CHIP_SPECS
from metatv.gui.chips import ToggleChip
from metatv.gui.main_window_menu_actions import _MenuActionsMixin
from metatv.gui.main_window_nav import _NAV_VIEW_TARGETS, _NavMixin
from metatv.gui.scoped_filter_box import ScopedFilterBox
from metatv.gui.shortcuts import SHORTCUTS, ShortcutCheatSheetDialog
from tests.conftest import destroy_widget

_VIEW_ROWS = tuple(spec for spec in SHORTCUTS if spec.id.startswith("view_"))


class _FakePlayer:
    """Records what the playback shortcuts asked the player to do."""

    def __init__(self) -> None:
        self.commands: list[list] = []
        self.stops = 0
        self.running = True

    def send_command(self, cmd, key=None) -> bool:
        self.commands.append(cmd)
        return self.running

    def stop(self, key=None) -> bool:
        self.stops += 1
        return self.running


class _Overlay(QWidget):
    """Stands in for a lightbox: closes itself on Escape, exactly as they do."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.escapes = 0

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.key() == Qt.Key.Key_Escape:
            self.escapes += 1
            self.hide()
        else:
            super().keyPressEvent(event)


class _Window(_MenuActionsMixin, _NavMixin, QMainWindow):
    """A real window running the real handlers the registry names."""

    def __init__(self) -> None:
        super().__init__()
        self.view_mode: str | None = None
        self.statuses: list[str] = []
        self.player_manager = _FakePlayer()

        bar = self.menuBar()
        self._view_menu = bar.addMenu("&View")
        self._view_menu.addAction("&Refresh")  # so the separator has a reason
        self._playback_menu = bar.addMenu("&Playback")
        layout_menu = bar.addMenu("&Layout")
        self._tools_menu = bar.addMenu("&Tools")
        self._tools_menu.addAction("Stream diagnostics")

        self._sidebar_visible_action = QAction("&Sidebar", self, checkable=True)
        self._sidebar_visible_action.setToolTip(
            "Show or hide the left sidebar. Its width is remembered."
        )
        layout_menu.addAction(self._sidebar_visible_action)
        self._details_visible_action = QAction("&Details pane", self, checkable=True)
        self._details_visible_action.setToolTip(
            "Show or hide the details pane on the right. Its width is remembered."
        )
        layout_menu.addAction(self._details_visible_action)

        central = QWidget(self)
        self.setCentralWidget(central)
        self.search_input = ScopedFilterBox("Search titles…", debounce_ms=0, parent=central)
        self.search_input.setToolTip("Search every source by name or category")

        for attr, label, role, *_rest in NAV_CHIP_SPECS:
            chip = ToggleChip(label, vector_role=role)
            chip.setParent(central)
            chip.setToolTip(f"{label} view")
            setattr(self, attr, chip)

        _shortcuts.install(self)

    # ── the view bodies, replaced: the real ones want the whole content area
    def _record(self, mode: str) -> None:
        self.view_mode = mode

    def switch_to_list_view(self) -> None:
        self._record("list")

    def switch_to_epg_view(self) -> None:
        self._record("epg")

    def switch_to_preferences_view(self) -> None:
        self._record("preferences")

    def switch_to_discover_view(self) -> None:
        self._record("discover")

    def switch_to_recipe_view(self) -> None:
        self._record("recipe")

    def status(self, message: str, ms: int = 0) -> None:
        self.statuses.append(message)


@pytest.fixture
def win(qtbot):
    """A shown, ACTIVE window — a WindowShortcut only fires on the active one."""
    window = _Window()
    qtbot.addWidget(window)
    window.show()
    QTest.qWaitForWindowExposed(window)
    window.activateWindow()
    QApplication.processEvents()
    yield window
    destroy_widget(window)


def _press(target, key, modifier=Qt.KeyboardModifier.NoModifier):
    QTest.keyClick(target, key, modifier)
    QApplication.processEvents()


# ---------------------------------------------------------------------------
# The table itself
# ---------------------------------------------------------------------------


class TestTheRegistryAgreesWithTheSwitcher:

    def test_the_view_rows_are_the_nav_chips_in_the_chips_own_order(self):
        """``Ctrl+1..5`` must read left to right across the switcher.

        Both sides are read here — the registry AND ``NAV_CHIP_SPECS``, the
        tuple that lays the chips out — because the whole point of deriving one
        from the other is that a sixth chip, or a reordered one, cannot leave
        the keys pointing at the old positions.
        """
        assert [spec.label for spec in _VIEW_ROWS] == [
            label for _attr, label, *_rest in NAV_CHIP_SPECS
        ]
        assert [spec.keys[0] for spec in _VIEW_ROWS] == [
            f"Ctrl+{n}" for n in range(1, len(NAV_CHIP_SPECS) + 1)
        ]
        assert [spec.tooltip_host for spec in _VIEW_ROWS] == [
            attr for attr, *_rest in NAV_CHIP_SPECS
        ]

    def test_every_view_row_names_a_real_navigation_target(self):
        """A ``view:<name>`` nobody can resolve is a key that does nothing."""
        for spec in _VIEW_ROWS:
            kind, _, name = spec.arg.partition(":")
            assert kind == "view", spec.id
            assert name in _NAV_VIEW_TARGETS, spec.id

    def test_every_handler_the_table_names_exists_on_mainwindow(self):
        """The handler field is a NAME, so nothing but this proves it resolves."""
        from metatv.gui.main_window import MainWindow

        for spec in SHORTCUTS:
            assert callable(getattr(MainWindow, spec.handler, None)), spec.id

    def test_only_the_typeable_keys_are_guarded(self):
        """``F1`` and every ``Ctrl+…`` must stay live while the user types."""
        assert _shortcuts.guarded_key_codes() == frozenset({
            Qt.Key.Key_Slash, Qt.Key.Key_Question, Qt.Key.Key_Space,
        })

    def test_every_text_key_is_one_of_the_rows_own_keys(self):
        """A guard entry that no binding uses would silently eat a keystroke."""
        for spec in SHORTCUTS:
            assert set(spec.text_keys) <= set(spec.keys), spec.id

    def test_each_section_is_contiguous_in_the_table(self):
        """The cheat-sheet draws the table section by section, in order.

        A row filed under a section already drawn would jump up the page,
        away from the key above it in the table — so the table has to keep
        its sections together for the sheet to read down.
        """
        drawn: list[str] = []
        for spec in SHORTCUTS:
            if not drawn or drawn[-1] != spec.section:
                assert spec.section not in drawn, spec.id
                drawn.append(spec.section)


class TestInstall:

    def test_every_row_becomes_an_action_carrying_its_keys(self, win):
        actions = win._shortcut_actions
        assert set(actions) == {spec.id for spec in SHORTCUTS}
        for spec in SHORTCUTS:
            bound = {seq.toString() for seq in actions[spec.id].shortcuts()}
            assert bound == {seq.toString() for seq in spec.sequences()}, spec.id
            assert (
                actions[spec.id].shortcutContext()
                == Qt.ShortcutContext.WindowShortcut
            ), spec.id

    def test_the_panel_toggles_reuse_the_actions_that_already_exist(self, win):
        """No second Sidebar entry beside the one the Layout menu already has."""
        assert win._shortcut_actions["toggle_sidebar"] is win._sidebar_visible_action
        assert win._shortcut_actions["toggle_details"] is win._details_visible_action

    def test_each_row_lands_in_the_menu_it_names(self, win):
        for spec in SHORTCUTS:
            if spec.menu is None or spec.existing_action is not None:
                continue
            menu = getattr(win, spec.menu)
            assert win._shortcut_actions[spec.id] in menu.actions(), spec.id

    def test_escape_is_owned_by_the_window_even_with_no_menu_entry(self, win):
        """Without a menu, only ``addAction`` gets it into the shortcut map."""
        escape = win._shortcut_actions["escape"]
        assert escape in win.actions()
        assert all(escape not in menu.actions() for menu in (
            win._view_menu, win._playback_menu, win._tools_menu))


# ---------------------------------------------------------------------------
# Pressing the keys
# ---------------------------------------------------------------------------


class TestViewSwitching:

    def test_ctrl_1_switches_to_the_first_view_in_the_switcher(self, win):
        _press(win, Qt.Key.Key_1, Qt.KeyboardModifier.ControlModifier)
        assert win.view_mode == "list"

    def test_ctrl_2_switches_to_the_second_and_lights_its_chip(self, win):
        _press(win, Qt.Key.Key_2, Qt.KeyboardModifier.ControlModifier)
        assert win.view_mode == "epg"
        assert win.epg_chip.is_enabled()
        assert not win.discover_chip.is_enabled()

    @pytest.mark.parametrize("n,expected", [
        (Qt.Key.Key_3, "preferences"),
        (Qt.Key.Key_4, "discover"),
        (Qt.Key.Key_5, "recipe"),
    ])
    def test_the_remaining_view_keys_each_land_on_their_own_view(
        self, win, n, expected
    ):
        _press(win, n, Qt.KeyboardModifier.ControlModifier)
        assert win.view_mode == expected


class TestFocusSearch:

    def test_the_slash_focuses_the_search_box_and_selects_what_is_in_it(self, win):
        win.search_input.setText("dune")
        win.centralWidget().setFocus()
        QApplication.processEvents()

        _press(win, Qt.Key.Key_Slash)

        assert QApplication.focusWidget() is win.search_input
        assert win.search_input.selectedText() == "dune"

    def test_ctrl_f_does_it_too(self, win):
        win.centralWidget().setFocus()
        _press(win, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
        assert QApplication.focusWidget() is win.search_input

    def test_a_slash_typed_in_the_box_is_a_slash_not_a_shortcut(self, win):
        """The other direction: the key the user is TYPING must reach the box."""
        win.search_input.setFocus()
        win.search_input.setText("mad max")
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_Slash)

        assert win.search_input.text() == "mad max/"
        # …and it did not re-fire focus-search, which would have selected it all
        assert win.search_input.selectedText() == ""

    def test_ctrl_f_still_works_from_inside_the_box(self, win):
        """The focus-search binding is exempt: nothing types Ctrl+F."""
        win.search_input.setFocus()
        win.search_input.setText("solaris")
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)

        assert win.search_input.text() == "solaris"
        assert win.search_input.selectedText() == "solaris"


class TestTextFieldsSwallowTheSingleKeys:

    def test_space_typed_in_the_search_box_never_reaches_the_player(self, win):
        win.search_input.setFocus()
        win.search_input.setText("blade")
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_Space)

        assert win.search_input.text() == "blade "
        assert win.player_manager.commands == []

    def test_question_typed_in_the_search_box_opens_no_cheat_sheet(self, win):
        win.search_input.setFocus()
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_Question,
               Qt.KeyboardModifier.ShiftModifier)

        assert win.search_input.text() == "?"
        assert not any(
            isinstance(w, ShortcutCheatSheetDialog)
            for w in QApplication.topLevelWidgets()
        )

    def test_the_guard_answers_for_a_focused_text_field_and_no_one_else(self, win):
        """The filter's own predicate, both directions, without Qt's help.

        An editable ``QLineEdit`` accepts the ShortcutOverride itself, so the
        two tests above would pass with the guard deleted. This one asks the
        guard directly, so removing it turns something red.
        """
        from PyQt6.QtCore import QEvent
        from PyQt6.QtGui import QKeyEvent

        guard = win._shortcut_key_guard
        space = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Space,
                          Qt.KeyboardModifier.NoModifier)
        ctrl_b = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_B,
                           Qt.KeyboardModifier.ControlModifier)

        win.search_input.setFocus()
        QApplication.processEvents()
        assert guard.blocks(space) is True
        assert guard.blocks(ctrl_b) is False

        win.centralWidget().setFocus()
        QApplication.processEvents()
        assert guard.blocks(space) is False


class TestEscape:

    def test_escape_in_the_search_box_clears_it_and_drops_focus(self, win):
        win.search_input.setFocus()
        win.search_input.setText("arrival")
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_Escape)

        assert win.search_input.text() == ""
        assert QApplication.focusWidget() is not win.search_input

    def test_escape_forwards_to_the_box_so_its_own_signal_still_fires(self, win):
        """The box's ``escaped`` is what folds the Watch Queue's find panel.

        Re-implementing "clear it" in the handler would leave that signal
        unfired and quietly break a surface this slice never touched.
        """
        seen: list[bool] = []
        win.search_input.escaped.connect(lambda: seen.append(True))
        win.search_input.setFocus()
        win.search_input.setText("annihilation")
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_Escape)

        assert seen == [True]

    def test_escape_closes_the_overlay_in_front(self, win):
        overlay = _Overlay(win)
        win._lightbox = overlay
        overlay.show()
        win.centralWidget().setFocus()
        QApplication.processEvents()

        _press(win, Qt.Key.Key_Escape)

        assert overlay.escapes == 1
        assert not overlay.isVisible()

    def test_the_topmost_overlay_is_the_one_that_closes(self, win):
        under, over = _Overlay(win), _Overlay(win)
        win._lightbox, win._poster_lightbox = under, over
        under.show()
        over.show()
        win.centralWidget().setFocus()
        QApplication.processEvents()

        _press(win, Qt.Key.Key_Escape)

        assert (over.escapes, under.escapes) == (1, 0)

    def test_escape_with_nothing_open_does_nothing_at_all(self, win):
        win.centralWidget().setFocus()
        QApplication.processEvents()
        _press(win, Qt.Key.Key_Escape)  # must not raise
        assert win.statuses == []


class TestPlayback:

    def test_space_toggles_pause_on_the_current_stream(self, win):
        win.centralWidget().setFocus()
        _press(win, Qt.Key.Key_Space)
        assert win.player_manager.commands == [["cycle", "pause"]]

    def test_space_says_so_when_there_is_nothing_playing(self, win):
        win.player_manager.running = False
        win.centralWidget().setFocus()
        _press(win, Qt.Key.Key_Space)
        assert win.statuses == ["Nothing is playing"]

    def test_ctrl_period_stops_the_stream(self, win):
        win.centralWidget().setFocus()
        _press(win, Qt.Key.Key_Period, Qt.KeyboardModifier.ControlModifier)
        assert win.player_manager.stops == 1
        assert win.statuses == ["Playback stopped"]


class TestChannelStepping:
    """``Ctrl+Down``/``Ctrl+Up`` move the selection, and skip what cannot hold it."""

    @staticmethod
    def _list(win, selectable):
        from PyQt6.QtCore import QAbstractListModel, QModelIndex
        from PyQt6.QtWidgets import QListView

        class _Model(QAbstractListModel):
            def rowCount(self, parent=QModelIndex()):
                return len(selectable)

            def data(self, index, role=Qt.ItemDataRole.DisplayRole):
                if role == Qt.ItemDataRole.DisplayRole:
                    return f"row {index.row()}"
                return None

            def flags(self, index):
                if selectable[index.row()]:
                    return (Qt.ItemFlag.ItemIsEnabled
                            | Qt.ItemFlag.ItemIsSelectable)
                return Qt.ItemFlag.ItemIsEnabled

        view = QListView(win.centralWidget())
        view.setModel(_Model(view))
        win.channels_list = view
        return view

    def test_ctrl_down_moves_to_the_next_row(self, win):
        view = self._list(win, [True, True, True])
        view.setCurrentIndex(view.model().index(0, 0))
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)

        assert view.currentIndex().row() == 1

    def test_it_steps_over_a_row_that_cannot_be_selected(self, win):
        """Grouped mode puts unselectable headings in the same model."""
        view = self._list(win, [True, False, True])
        view.setCurrentIndex(view.model().index(0, 0))
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)

        assert view.currentIndex().row() == 2

    def test_ctrl_up_walks_back_and_stops_at_the_top(self, win):
        view = self._list(win, [True, True])
        view.setCurrentIndex(view.model().index(1, 0))
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        assert view.currentIndex().row() == 0
        _press(win, Qt.Key.Key_Up, Qt.KeyboardModifier.ControlModifier)
        assert view.currentIndex().row() == 0

    def test_stepping_selects_but_never_plays(self, win):
        view = self._list(win, [True, True])
        view.setCurrentIndex(view.model().index(0, 0))
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_Down, Qt.KeyboardModifier.ControlModifier)

        assert win.player_manager.commands == []


# ---------------------------------------------------------------------------
# Saying where the keys are
# ---------------------------------------------------------------------------


class TestTooltips:

    def test_each_control_keeps_its_tooltip_and_gains_its_key(self, win):
        _shortcuts.annotate_tooltips(win)
        for spec in SHORTCUTS:
            if spec.tooltip_host is None:
                continue
            host = getattr(win, spec.tooltip_host)
            assert spec.key_text() in host.toolTip(), spec.id

    def test_the_existing_wording_survives(self, win):
        _shortcuts.annotate_tooltips(win)
        tip = win._sidebar_visible_action.toolTip()
        assert tip.startswith("Show or hide the left sidebar.")
        assert tip.endswith("(Ctrl+B)")

    def test_annotating_twice_does_not_stack_the_keys_up(self, win):
        _shortcuts.annotate_tooltips(win)
        once = win.search_input.toolTip()
        _shortcuts.annotate_tooltips(win)
        assert win.search_input.toolTip() == once

    def test_an_action_built_here_says_its_own_key(self, win):
        assert "(Ctrl+.)" in win._shortcut_actions["stop"].toolTip()


class TestCheatSheet:

    @pytest.fixture
    def sheet(self, qtbot):
        dialog = ShortcutCheatSheetDialog()
        qtbot.addWidget(dialog)
        dialog.show()
        QTest.qWaitForWindowExposed(dialog)
        QApplication.processEvents()
        yield dialog
        destroy_widget(dialog)

    def test_it_lists_every_row_in_the_registry(self, sheet):
        assert set(sheet.rows) == {spec.id for spec in SHORTCUTS}
        for spec in SHORTCUTS:
            keys, what = sheet.rows[spec.id]
            assert keys.text() == spec.key_text()
            assert what.text() == spec.label

    def test_every_section_gets_a_heading(self, sheet):
        headings = {
            label.text() for label in sheet.findChildren(QLabel)
            if label.objectName() == ""
        }
        for spec in SHORTCUTS:
            assert spec.section in headings, spec.section

    def test_it_renders_as_two_columns_with_the_keys_on_the_left(self, sheet):
        """Rendered geometry, not row order.

        Order is not position: a grid that put both labels in the same cell, or
        collapsed the keys column to zero width, would pass every "is the text
        there" assertion above and be unreadable on screen.
        """
        for spec_id, (keys, what) in sheet.rows.items():
            key_box = keys.geometry()
            what_box = what.geometry()
            assert key_box.width() > 0, spec_id
            assert what_box.width() > 0, spec_id
            assert key_box.right() < what_box.left(), spec_id
            # Same row: the two halves of one line, not stacked.
            assert abs(key_box.center().y() - what_box.center().y()) <= 4, spec_id

    def test_the_rows_run_down_the_page_in_the_table_order(self, sheet):
        """Position, not sequence: a grid can place a row anywhere it likes."""
        tops = [sheet.rows[spec.id][0].geometry().top() for spec in SHORTCUTS]
        assert tops == sorted(tops)
        assert len(set(tops)) == len(tops), "two rows landed on the same line"

    def test_the_key_column_is_the_narrow_one(self, sheet):
        """The description takes the slack — the point of the stretch on col 1."""
        keys, what = sheet.rows["focus_search"]
        assert keys.width() < what.width()

    def test_it_closes_on_its_one_button(self, sheet):
        from PyQt6.QtWidgets import QDialogButtonBox

        box = sheet.findChild(QDialogButtonBox)
        primary = box.button(QDialogButtonBox.StandardButton.Ok)
        assert primary.text() == "Close"
        assert box.button(QDialogButtonBox.StandardButton.Cancel) is None


class TestOpeningTheCheatSheet:

    def test_f1_opens_it(self, win, monkeypatch):
        opened: list[object] = []
        monkeypatch.setattr(
            ShortcutCheatSheetDialog, "exec",
            lambda self: opened.append(self) or 0,
        )
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_F1)

        assert len(opened) == 1
        destroy_widget(*opened)

    def test_question_mark_opens_it_too(self, win, monkeypatch):
        opened: list[object] = []
        monkeypatch.setattr(
            ShortcutCheatSheetDialog, "exec",
            lambda self: opened.append(self) or 0,
        )
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_Question, Qt.KeyboardModifier.ShiftModifier)

        assert len(opened) == 1
        destroy_widget(*opened)

    def test_f1_still_opens_it_from_inside_the_search_box(self, win, monkeypatch):
        """A function key is not typeable, so it is not guarded."""
        opened: list[object] = []
        monkeypatch.setattr(
            ShortcutCheatSheetDialog, "exec",
            lambda self: opened.append(self) or 0,
        )
        win.search_input.setFocus()
        QApplication.processEvents()

        _press(win.search_input, Qt.Key.Key_F1)

        assert len(opened) == 1
        assert win.search_input.text() == ""
        destroy_widget(*opened)


class TestPanelToggles:

    def test_ctrl_b_and_ctrl_d_drive_the_existing_layout_handlers(self, win):
        toggled: list[str] = []
        win._sidebar_visible_action.triggered.connect(
            lambda: toggled.append("sidebar"))
        win._details_visible_action.triggered.connect(
            lambda: toggled.append("details"))
        win.centralWidget().setFocus()

        _press(win, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
        _press(win, Qt.Key.Key_D, Qt.KeyboardModifier.ControlModifier)

        assert toggled == ["sidebar", "details"]


def test_no_widget_builds_a_qshortcut_of_its_own():
    """A shortcut off the table is one nobody can find.

    An AST walk, not a text scan: this file and ``gui/shortcuts.py`` both
    discuss ``QShortcut`` in prose, and a guard a comment can trip is a guard
    somebody eventually deletes.
    """
    import ast
    import pathlib

    gui = pathlib.Path(_shortcuts.__file__).parent
    offenders: list[str] = []
    for path in sorted(gui.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "QShortcut"):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], (
        "these build a QShortcut instead of adding a row to "
        "gui/shortcuts.py — a QShortcut cannot appear in a menu or in the "
        f"cheat-sheet, so nobody finds it: {offenders}"
    )


def test_the_search_box_is_a_line_edit_so_the_guard_can_see_it(qtbot):
    """The guard's type list is only as true as the widget it has to catch."""
    box = ScopedFilterBox("x")
    plain = QWidget()
    qtbot.addWidget(box)
    qtbot.addWidget(plain)
    assert issubclass(ScopedFilterBox, QLineEdit)
    assert _shortcuts.is_text_entry(box)
    assert not _shortcuts.is_text_entry(plain)
    destroy_widget(box, plain)
