"""The adult-content gate must be reachable, sticky, and self-explaining.

Two separate failures shipped together here, and each test below targets one:

1. **Silent.** Every PORNBOX channel carries ``is_adult``, so opening that
   category returned 0 rows under "try a different search" — the four-axis
   transparency bar had no adult axis, so the honest branch could not be reached.
2. **Not sticky.** ``config`` owns ``filter_adult_mode``; the only writer is
   Settings → Content, via ``SettingsDialog._save_values()``.

A third failure — a ``FilterBar``-only combo left permanently invisible via
``setVisible(False)``, unreachable by any live control — was retired with the
rest of the dead ``FilterBar`` class (audit slice 4, 2026-09-07);
``_apply_adult_mode_setting`` now only reloads the channel list, covered by
``tests/test_settings_apply.py::test_the_reloading_handlers_ask_rather_than_force``.
"""

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


def test_adult_mode_setting_reloads_the_channel_list(qapp):
    """``_apply_adult_mode_setting`` must reload so a Settings change shows on screen."""
    from metatv.gui.main_window import MainWindow

    win = MainWindow.__new__(MainWindow)
    win.config = _FakeConfig()
    win.config.filter_adult_mode = "all"
    reloads = []
    win.load_channels = lambda *a, **k: reloads.append(1)

    MainWindow._apply_adult_mode_setting(win)

    assert reloads, "the channel list was not reloaded, so nothing changes on screen"


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
