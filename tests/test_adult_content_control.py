"""The adult-content gate must be reachable, sticky, and self-explaining.

Three separate failures shipped together here, and each test below targets one:

1. **Unreachable.** ``FilterBar`` built ``adult_mode_combo`` with
   ``setVisible(False)`` and a comment pointing at ``set_adult_filter_visible()``
   — a method defined and called by nobody. The only control over the setting was
   permanently invisible.
2. **Silent.** Every PORNBOX channel carries ``is_adult``, so opening that
   category returned 0 rows under "try a different search" — the four-axis
   transparency bar had no adult axis, so the honest branch could not be reached.
3. **Not sticky.** ``config`` owns ``filter_adult_mode`` but ``FilterBar`` caches
   it in the combo, and ``save_filter_state()`` writes the CACHE back to config.
   A Settings change that did not also update the combo would be reverted by the
   user's next filter click.
"""

from PyQt6.QtWidgets import QWidget

from metatv.gui.settings_dialog import SettingsDialog, _SECTIONS, _SECTION_HELP
from tests.test_settings_tab_layout import _FakeConfig


def test_content_section_exists_and_is_documented(qapp):
    """A Content section must exist AND carry help text — id is the help key."""
    ids = [sid for sid, _label, _builder in _SECTIONS]
    assert "content" in ids, "Settings has no Content section"
    assert "content" in _SECTION_HELP, "Content section has no help-panel text"
    assert _SECTION_HELP["content"].strip(), "Content help text is empty"


def test_adult_control_round_trips_through_config(qapp):
    """The control must LOAD from config and SAVE back — both directions.

    A control that renders but does not persist is the same bug in a new place.
    """
    cfg = _FakeConfig()
    cfg.filter_adult_mode = "only"
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._adult_mode_combo.currentData() == "only", (
            "combo did not load the stored mode"
        )
        dlg._adult_mode_combo.setCurrentIndex(dlg._adult_mode_combo.findData("all"))
        dlg._save_values()
        assert cfg.filter_adult_mode == "all", "combo did not save back to config"
    finally:
        dlg.close()


def test_every_adult_mode_survives_the_round_trip(qapp):
    """All three modes, not just the one that happens to be first."""
    for mode in ("all", "hide", "only"):
        cfg = _FakeConfig()
        cfg.filter_adult_mode = mode
        dlg = SettingsDialog(cfg, parent=None)
        try:
            assert dlg._adult_mode_combo.currentData() == mode
            dlg._save_values()
            assert cfg.filter_adult_mode == mode
        finally:
            dlg.close()


def test_settings_change_is_pushed_into_the_filter_bar_cache(qapp):
    """``_apply_adult_mode_setting`` must write config INTO the combo.

    Without this the setting silently reverts: ``FilterBar.get_filter_state()``
    reads the combo (never config) and ``save_filter_state()`` writes that stale
    value back over the freshly-saved one on the user's next filter click.
    """
    from metatv.gui.main_window import MainWindow

    class _Combo(QWidget):
        def __init__(self):
            super().__init__()
            self._idx = 1
            self.blocked = None

        def blockSignals(self, on):          # noqa: N802 - Qt casing
            self.blocked = on
            return False

        def setCurrentIndex(self, i):        # noqa: N802 - Qt casing
            assert self.blocked, (
                "setCurrentIndex fired with signals live — it re-enters "
                "on_filter_changed and triggers a duplicate reload"
            )
            self._idx = i

        def currentIndex(self):              # noqa: N802 - Qt casing
            return self._idx

    class _Bar:
        def __init__(self):
            self.adult_mode_combo = _Combo()

    win = MainWindow.__new__(MainWindow)
    win.filter_bar = _Bar()
    win.config = _FakeConfig()
    win.config.filter_adult_mode = "all"
    reloads = []
    win.load_channels = lambda *a, **k: reloads.append(1)

    MainWindow._apply_adult_mode_setting(win)

    assert win.filter_bar.adult_mode_combo.currentIndex() == 0, (
        "combo was not synced to the 'all' the user just chose in Settings"
    )
    assert reloads, "the channel list was not reloaded, so nothing changes on screen"


def test_sync_maps_every_mode_to_the_right_index(qapp):
    """A wrong mapping would silently apply the wrong setting."""
    from metatv.gui.main_window import MainWindow

    class _Combo(QWidget):
        def __init__(self):
            super().__init__()
            self._idx = -1

        def blockSignals(self, on):          # noqa: N802 - Qt casing
            return False

        def setCurrentIndex(self, i):        # noqa: N802 - Qt casing
            self._idx = i

        def currentIndex(self):              # noqa: N802 - Qt casing
            return self._idx

    class _Bar:
        def __init__(self):
            self.adult_mode_combo = _Combo()

    for mode, expected in (("all", 0), ("hide", 1), ("only", 2)):
        win = MainWindow.__new__(MainWindow)
        win.filter_bar = _Bar()
        win.config = _FakeConfig()
        win.config.filter_adult_mode = mode
        win.load_channels = lambda *a, **k: None
        MainWindow._apply_adult_mode_setting(win)
        assert win.filter_bar.adult_mode_combo.currentIndex() == expected, (
            f"mode {mode!r} mapped to the wrong combo index"
        )


def test_empty_list_names_the_adult_gate_instead_of_blaming_search(qapp):
    """The reported bug: 0 results with no indication a gate did it.

    Asserts the RENDERED text of the segment, not merely that a flag flipped —
    the user's complaint was about what the screen said.
    """
    from metatv.gui.main_window import MainWindow
    from tests.conftest import wire_channel_banner_widgets

    win = MainWindow.__new__(MainWindow)
    wire_channel_banner_widgets(win)
    win._count_label = lambda n, floor: f"{n:,}{'+' if floor else ''}"

    MainWindow._show_channel_filter_breakdown(win, 0, 0, 0, 0, 28)

    assert win._channel_adult_btn.isVisible(), "the adult notice never appeared"
    text = win._channel_adult_btn.text()
    assert "28" in text, f"the count is missing from {text!r}"
    assert "adult" in text.lower(), f"the reason is not named in {text!r}"
    assert "Settings" in text, f"no route to the control in {text!r}"
    assert win._channel_filter_bar.isVisible(), "the bar holding it stayed hidden"


def test_no_adult_notice_when_the_gate_hid_nothing(qapp):
    """The segment must not appear on an ordinary empty list."""
    from metatv.gui.main_window import MainWindow
    from tests.conftest import wire_channel_banner_widgets

    win = MainWindow.__new__(MainWindow)
    wire_channel_banner_widgets(win)
    win._count_label = lambda n, floor: str(n)

    MainWindow._show_channel_filter_breakdown(win, 0, 0, 0, 0, 0)

    assert not win._channel_adult_btn.isVisible()
    assert not win._channel_filter_bar.isVisible()


def test_adult_notice_opens_settings_rather_than_bypassing_the_gate(qapp):
    """Deliberate asymmetry: the other four segments reveal, this one routes.

    The gate is a choice the user made; the app hands over the switch rather
    than flipping it for them.
    """
    from metatv.gui.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    opened = []
    win.open_settings = lambda tab=None: opened.append(tab)

    MainWindow._open_adult_settings(win)

    assert opened == ["Content"], (
        f"expected Settings to open on Content, got {opened!r}"
    )
    labels = [label for _sid, label, _builder in _SECTIONS]
    assert "Content" in labels, (
        "the label passed to open_settings does not match any real section, so "
        "select_section_by_label would silently select nothing"
    )
