"""LIVE-1 — Settings -> Content -> "Live catalog refresh" round-trips through config.

Same pattern as ``test_adult_content_control.py`` for the sibling combo on the
same tab: a control that renders but does not persist is the same bug in a
new place, so this proves both directions (load from config, save back to
config) using the REAL ``SettingsDialog`` constructor — not a ``__new__``
skeleton — so the whole Content tab actually builds and
``wire_settings_content_widgets`` never diverges from the real
``_build_content_tab``.
"""

from metatv.gui.settings_dialog import SettingsDialog
from tests.test_settings_tab_layout import _FakeConfig


def test_content_tab_has_a_live_refresh_combo(qapp):
    """The control must exist at all — a setting you cannot find does not exist."""
    dlg = SettingsDialog(_FakeConfig(), parent=None)
    try:
        assert dlg._live_refresh_mode_combo is not None
        values = {dlg._live_refresh_mode_combo.itemData(i)
                  for i in range(dlg._live_refresh_mode_combo.count())}
        assert values == {"manual", "on_view_open", "15m", "30m", "1h", "3h"}
    finally:
        dlg.close()


def test_live_refresh_mode_round_trips_through_config(qapp):
    cfg = _FakeConfig()
    cfg.live_refresh_mode = "30m"
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._live_refresh_mode_combo.currentData() == "30m", (
            "combo did not load the stored mode"
        )
        dlg._live_refresh_mode_combo.setCurrentIndex(
            dlg._live_refresh_mode_combo.findData("on_view_open")
        )
        dlg._save_values()
        assert cfg.live_refresh_mode == "on_view_open", (
            "combo did not save back to config"
        )
    finally:
        dlg.close()


def test_every_live_refresh_mode_survives_the_round_trip(qapp):
    """All six modes, not just the one that happens to be first."""
    for mode in ("manual", "on_view_open", "15m", "30m", "1h", "3h"):
        cfg = _FakeConfig()
        cfg.live_refresh_mode = mode
        dlg = SettingsDialog(cfg, parent=None)
        try:
            assert dlg._live_refresh_mode_combo.currentData() == mode
            dlg._save_values()
            assert cfg.live_refresh_mode == mode
        finally:
            dlg.close()


def test_missing_config_value_falls_back_to_manual(qapp):
    """A config double that predates this setting (no ``live_refresh_mode``
    attribute at all — every existing skeleton config in this test suite)
    must not crash ``_load_values``; it falls back to "manual", same shape
    as ``filter_adult_mode``'s getattr fallback."""
    cfg = _FakeConfig()  # never sets live_refresh_mode
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._live_refresh_mode_combo.currentData() == "manual"
    finally:
        dlg.close()
