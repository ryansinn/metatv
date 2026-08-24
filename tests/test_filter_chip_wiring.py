"""Is the chip bar actually WIRED — reachable, visible, and driving the panel?

This file exists because of a specific failure, twice over. A sidebar
allocation fix shipped inert: every unit test passed, and the only caller of
the new code was its own test suite. A theme sweep shipped the same way. Both
times the tests proved the mechanism worked and nothing proved it was CONNECTED.

So these run against a real ``MainWindow``: is the bar in the layout, does the
column actually go away, does a chip's × change the query, and does returning
from another view leave things as the mode says rather than as the old
``setVisible(True)`` said.
"""

from __future__ import annotations

import pathlib

import pytest

from metatv.gui.filter_chip_bar import FilterChipBar


@pytest.fixture(scope="module")
def window(tmp_path_factory):
    """ONE real MainWindow for the module — see test_app_header.py's note."""
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

    real_run_pending = MigrationManager.run_pending
    MigrationManager.run_pending = lambda self, *a, **k: None

    config, _ = Config.load()
    win = MainWindow(config)
    win.resize(1680, 1000)
    # show(), not just resize(): isVisible() is False for every descendant of an
    # unshown window, so without this the visibility assertions below would pass
    # for a bar that was never built and fail for one that works.
    win.show()
    app.processEvents()
    try:
        yield win
    finally:
        win.close()
        app.processEvents()
        MigrationManager.run_pending = real_run_pending
        pathlib.Path.home = real_home


def test_the_chip_bar_is_in_the_window(window):
    """Not "the method exists" — the widget is in the tree."""
    assert isinstance(window.filter_chip_bar, FilterChipBar)
    assert window.filter_chip_bar in window.findChildren(FilterChipBar)


def test_the_chip_bar_sits_above_the_results(window):
    """It describes the list, so it goes over the list."""
    layout = window._list_layout
    index = layout.indexOf(window.filter_chip_bar)
    assert index == 0, (
        f"the chip bar is at position {index} in the list area, not the top"
    )


def test_chip_mode_takes_the_includes_column_off_the_screen(window):
    """The whole point: ~250px of width back to the results."""
    assert window.filter_ui_mode() == "chips"
    assert not window.filter_panel.isVisible(), (
        "the Includes column is still on screen in chip mode — the chip line "
        "and the column are both showing, which is the layout chips replace"
    )
    assert window.filter_chip_bar.isVisible()


def test_the_column_starts_shut_every_launch_not_just_the_first(window):
    """A rule, not a one-time migration flag.

    An existing config carries ``filter_section_visible: true``; so does a
    fresh one. Anything that depends on having recorded a handover is wrong
    for one of those cases.
    """
    window.config.filter_section_visible = True
    window._filter_column_launched = False       # pretend this is a new launch
    window._apply_filter_ui_mode()
    assert not window.filter_panel.isVisible()
    assert window.config.filter_section_visible is False


def test_add_filter_opens_the_column_and_again_shuts_it(window):
    bar = window.filter_chip_bar
    bar._add.click()
    assert window.filter_panel.isVisible(), "+ Add filter did not open the column"
    bar._add.click()
    assert not window.filter_panel.isVisible(), "+ Add filter did not shut it again"


def test_returning_from_another_view_does_not_re_open_the_column(window):
    """The old restore path forced ``setVisible(True)`` unconditionally.

    Left alone, that would drag the column back every time you left a view and
    came back — the chip mode would last exactly one navigation.
    """
    window.switch_to_epg_view()
    assert not window.filter_chip_bar.isVisible(), "chips linger over the EPG view"
    window.switch_to_list_view()
    assert window.filter_chip_bar.isVisible(), "the chip line did not come back"
    assert not window.filter_panel.isVisible(), (
        "the Includes column came back on a view switch"
    )


def test_a_column_the_user_opened_survives_a_view_switch(window):
    """The rule is about LAUNCH, not about overriding the user mid-session."""
    window.filter_chip_bar._add.click()
    assert window.filter_panel.isVisible()
    window.switch_to_epg_view()
    window.switch_to_list_view()
    assert window.filter_panel.isVisible(), (
        "the column the user opened was shut by a view switch"
    )
    window.filter_chip_bar._add.click()      # restore for later tests


def test_a_real_filter_becomes_a_real_chip(window):
    """End to end: constrain the panel, read the line."""
    panel = window.filter_panel
    panel._media_sec.check_only("movie")
    window._sync_filter_chips()
    assert "Movies" in window.filter_chip_bar.chip_labels()

    panel._media_sec.select_all()
    window.current_filter_state = panel.get_filter_state()
    window._sync_filter_chips()
    assert "Movies" not in window.filter_chip_bar.chip_labels()


def test_ticking_the_panel_updates_the_line_with_no_help(window):
    """The real path: panel row → filter_changed → on_filter_changed → chips.

    Every other test here calls ``_sync_filter_chips`` itself, which proves the
    describer works but not that anything CALLS it. Drop the call from
    ``on_filter_changed`` and those tests all stay green while the line silently
    stops matching the results — the exact shape of "shipped inert".

    ``load_channels`` is stubbed because this is about the chip line, not the
    query; the query has its own tests.
    """
    panel = window.filter_panel
    panel._media_sec.select_all()
    window.current_filter_state = panel.get_filter_state()
    window._sync_filter_chips()
    assert window.filter_chip_bar.chip_labels() == []

    real_load = window.load_channels
    window.load_channels = lambda *a, **k: None
    try:
        panel._media_sec.check_only("movie")   # emits filter_changed for real
    finally:
        window.load_channels = real_load

    assert window.filter_chip_bar.chip_labels() == ["Movies"], (
        "a filter changed and the chip line did not follow it"
    )


def test_a_chips_x_actually_lifts_the_constraint(window):
    """Not "the signal fires" — the PANEL comes back unconstrained."""
    panel = window.filter_panel
    panel._media_sec.check_only("series")
    window._sync_filter_chips()
    chips = window.filter_chip_bar._chips
    assert [c.label() for c in chips] == ["Series"]

    chips[0]._close.click()

    assert panel._media_sec.is_all_selected(), (
        "the × removed the chip but left the filter in place"
    )
    assert set(panel.get_filter_state()["media_types"]) == {"live", "movie", "series"}


def test_dropping_the_last_media_kind_restores_all_three(window):
    """A × that empties the screen is a trap, not a remove button."""
    panel = window.filter_panel
    panel._media_sec.check_only("movie")
    panel.clear_facet("media:movie")
    assert set(panel.get_filter_state()["media_types"]) == {"live", "movie", "series"}


def test_clear_all_empties_the_line(window):
    panel = window.filter_panel
    panel._media_sec.check_only("live")
    window._sync_filter_chips()
    assert window.filter_chip_bar.chip_labels()

    window.filter_chip_bar._clear.click()
    window.current_filter_state = panel.get_filter_state()
    window._sync_filter_chips()
    assert window.filter_chip_bar.chip_labels() == []


def test_panel_mode_puts_the_column_back_and_takes_the_line_away(window):
    """The spec's escape hatch: the column is a genuine overview, keep it available."""
    try:
        assert window.toggle_filter_ui_mode() == "panel"
        assert window.filter_panel.isVisible()
        assert not window.filter_chip_bar.isVisible(), (
            "both filter UIs are showing at once"
        )
        assert window.toggle_filter_ui_mode() == "chips"
        assert not window.filter_panel.isVisible()
        assert window.filter_chip_bar.isVisible()
    finally:
        window.config.filter_ui_mode = "chips"
        window._apply_filter_ui_mode()


def test_the_layout_menu_tick_follows_the_mode(window):
    """A menu that lies about the screen is worse than no menu."""
    window._sync_layout_menu()
    assert window._filter_chips_action.isChecked() is True
    window.config.filter_ui_mode = "panel"
    window._sync_layout_menu()
    assert window._filter_chips_action.isChecked() is False
    window.config.filter_ui_mode = "chips"


def test_only_one_thing_decides_the_columns_visibility(window):
    """No path may set the panel visible behind the chokepoint's back.

    ``_apply_filter_ui_mode`` and ``toggle_filters`` are the two sanctioned
    writers. A third would be a second source of truth, which is how the
    restore path came to fight the mode in the first place.
    """
    import ast

    # Hiding the column is always fine — any view switch may do it. FORCING it
    # visible is the bug: that is the line the restore path used to carry, and
    # it would drag the column back on every return to the list.
    allowed = {"filter_chip_host.py", "main_window_channels.py"}
    offenders = []
    for path in pathlib.Path("metatv/gui").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr == "setVisible"):
                continue
            target = fn.value
            forces_visible = any(
                isinstance(a, ast.Constant) and a.value is True for a in node.args
            )
            if (isinstance(target, ast.Attribute)
                    and target.attr == "filter_panel"
                    and forces_visible
                    and path.name not in allowed):
                offenders.append(f"{path}:{node.lineno}")
    assert not offenders, (
        "filter_panel.setVisible(True) called outside the chokepoint: "
        + ", ".join(offenders)
    )
