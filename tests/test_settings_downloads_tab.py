"""Settings ▸ Downloads — the folder, layout and free-space floor controls.

*Catch, Keep, Record* (2026-08-30) shipped the library folder, the tree/flat
layout choice, and the free-space floor as hardcoded defaults (#656), with the
note that "the layout and the floor are not yet in Settings, so they use those
defaults for now." This is that page — driven through the REAL
``SettingsDialog(config, parent=None)`` constructor with a real ``Config``
(``settings_config_double``, CLAUDE.md: never a hand-written stub that drifts
from the model) so the round-trip is proven against production wiring, not a
copy of it.
"""

from __future__ import annotations

import pytest

from metatv.core.download_naming import LAYOUT_FLAT, LAYOUT_TREE
from metatv.gui.settings_dialog import SettingsDialog, _SECTION_HELP, _SECTIONS
from tests.conftest import settings_config_double


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_downloads_section_exists_and_is_documented():
    """A Downloads section must exist AND carry non-empty help text."""
    ids = [sid for sid, _label, _builder in _SECTIONS]
    assert "downloads" in ids, "Settings has no Downloads section"
    assert "downloads" in _SECTION_HELP
    assert _SECTION_HELP["downloads"].strip()


def test_layout_combo_offers_tree_and_flat(qapp, tmp_path):
    """Both layout choices from DL-1 must be selectable, not just the default."""
    cfg = settings_config_double(config_dir=tmp_path)
    dlg = SettingsDialog(cfg, parent=None)
    try:
        data = [dlg._download_layout_combo.itemData(i)
                for i in range(dlg._download_layout_combo.count())]
        assert set(data) == {LAYOUT_TREE, LAYOUT_FLAT}
    finally:
        dlg.close()


def test_downloads_settings_round_trip_through_config(qapp, tmp_path):
    """Load reflects a saved config; changing widgets and saving writes it back."""
    cfg = settings_config_double(
        config_dir=tmp_path,
        download_dir="/library/one",
        download_layout=LAYOUT_FLAT,
        download_free_space_floor_gb=25.0,
        download_space_policy="stop_now",
    )
    dlg = SettingsDialog(cfg, parent=None)
    try:
        # Loaded from the config passed at construction.
        assert dlg._download_dir_input.text() == "/library/one"
        assert dlg._download_layout_combo.currentData() == LAYOUT_FLAT
        assert dlg._download_floor_spin.value() == pytest.approx(25.0)
        assert dlg._download_policy_combo.currentData() == "stop_now"

        # Change every widget, then save.
        dlg._download_dir_input.setText("/library/two")
        idx = dlg._download_layout_combo.findData(LAYOUT_TREE)
        dlg._download_layout_combo.setCurrentIndex(idx)
        dlg._download_floor_spin.setValue(5.0)
        policy_idx = dlg._download_policy_combo.findData("finish_current")
        dlg._download_policy_combo.setCurrentIndex(policy_idx)
        dlg._save_values()

        assert cfg.download_dir == "/library/two"
        assert cfg.download_layout == LAYOUT_TREE
        assert cfg.download_free_space_floor_gb == pytest.approx(5.0)
        assert cfg.download_space_policy == "finish_current"
    finally:
        dlg.close()


def test_floor_zero_means_off(qapp, tmp_path):
    """0 GB is a real, selectable value — the floor's "off" position."""
    cfg = settings_config_double(config_dir=tmp_path, download_free_space_floor_gb=0.0)
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._download_floor_spin.value() == 0
        dlg._save_values()
        assert cfg.download_free_space_floor_gb == 0
    finally:
        dlg.close()


def test_browse_button_fills_in_the_chosen_folder(qapp, tmp_path, monkeypatch):
    """"Browse…" writes whatever the file dialog returns into the path field."""
    from PyQt6.QtWidgets import QFileDialog

    chosen = str(tmp_path / "chosen-library")
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", lambda *a, **kw: chosen)

    cfg = settings_config_double(config_dir=tmp_path, download_dir="/old/path")
    dlg = SettingsDialog(cfg, parent=None)
    try:
        dlg._browse_download_dir()
        assert dlg._download_dir_input.text() == chosen
    finally:
        dlg.close()


def test_browse_cancelled_leaves_the_path_untouched(qapp, tmp_path, monkeypatch):
    """An empty string (Cancel) must not blank out what was already typed."""
    from PyQt6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **kw: "")

    cfg = settings_config_double(config_dir=tmp_path, download_dir="/keep/me")
    dlg = SettingsDialog(cfg, parent=None)
    try:
        dlg._browse_download_dir()
        assert dlg._download_dir_input.text() == "/keep/me"
    finally:
        dlg.close()
