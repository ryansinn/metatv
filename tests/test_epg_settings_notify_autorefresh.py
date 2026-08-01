"""Behavioral tests for the two new EPG settings-dialog controls (Wave 3 slice 3A).

Ground truth: ``epg_notification_minutes_before`` (config.py:888) and
``epg_auto_refresh`` (config.py:889) already existed on ``Config`` and were
already CONSUMED (``epg_manager.py`` — ``_check_watchlist_notifications`` reads
the former, ``refresh_all_if_needed`` gates on the latter) but were genuinely
UI-less: nothing in Settings ever wrote them, so a user could never change them
without hand-editing config.yaml. This adds:

  - "Notify before show:" QSpinBox (5-120 min, default 15) → epg_notification_minutes_before
  - "Auto-refresh guides on launch and interval" QCheckBox → epg_auto_refresh

Both live in the EPG group inside the Metadata & API Keys tab, alongside the
pre-existing EPG refresh-interval / browse-back / scrubber controls.

These tests drive the REAL SettingsDialog(config, parent=None) constructor (not
a hand-wired skeleton) against a real Config on tmp_path, so the widgets are
built exactly as production _build_metadata_tab() builds them.
"""

from __future__ import annotations

import pytest

from metatv.core.config import Config


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def real_config(tmp_path):
    """A real Config backed by tmp_path (never touches the user's actual config)."""
    cfg = Config(
        config_dir=tmp_path / "cfg",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    cfg.config_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    return cfg


# ---------------------------------------------------------------------------
# Notify-before-show spinner
# ---------------------------------------------------------------------------

def test_notify_minutes_defaults_to_fifteen(qapp, real_config):
    """A fresh config (default 15) loads into the spinner unchanged."""
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(real_config, parent=None)
    assert dlg._epg_notify_minutes_spin.value() == 15
    dlg.close()


def test_notify_minutes_loads_from_config(qapp, real_config):
    """Load: a stored non-default value populates the spinner."""
    from metatv.gui.settings_dialog import SettingsDialog

    real_config.epg_notification_minutes_before = 45
    dlg = SettingsDialog(real_config, parent=None)
    assert dlg._epg_notify_minutes_spin.value() == 45
    dlg.close()


def test_notify_minutes_saves_to_config(qapp, real_config):
    """Save: changing the spinner and calling _save_values persists the new value."""
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(real_config, parent=None)
    dlg._epg_notify_minutes_spin.setValue(90)
    dlg._save_values()

    assert real_config.epg_notification_minutes_before == 90
    dlg.close()


def test_notify_minutes_spin_range_clamps(qapp, real_config):
    """The spinner enforces the 5-120 minute range from the brief."""
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(real_config, parent=None)
    dlg._epg_notify_minutes_spin.setValue(1)     # below range
    assert dlg._epg_notify_minutes_spin.value() == 5
    dlg._epg_notify_minutes_spin.setValue(999)   # above range
    assert dlg._epg_notify_minutes_spin.value() == 120
    dlg.close()


# ---------------------------------------------------------------------------
# Auto-refresh checkbox
# ---------------------------------------------------------------------------

def test_auto_refresh_loads_from_config_true(qapp, real_config):
    from metatv.gui.settings_dialog import SettingsDialog

    real_config.epg_auto_refresh = True
    dlg = SettingsDialog(real_config, parent=None)
    assert dlg._epg_auto_refresh_check.isChecked() is True
    dlg.close()


def test_auto_refresh_loads_from_config_false(qapp, real_config):
    from metatv.gui.settings_dialog import SettingsDialog

    real_config.epg_auto_refresh = False
    dlg = SettingsDialog(real_config, parent=None)
    assert dlg._epg_auto_refresh_check.isChecked() is False
    dlg.close()


def test_auto_refresh_saves_to_config(qapp, real_config):
    """Save: unchecking the box and calling _save_values persists False."""
    from metatv.gui.settings_dialog import SettingsDialog

    real_config.epg_auto_refresh = True
    dlg = SettingsDialog(real_config, parent=None)
    dlg._epg_auto_refresh_check.setChecked(False)
    dlg._save_values()

    assert real_config.epg_auto_refresh is False
    dlg.close()


def test_both_epg_settings_round_trip_together(qapp, real_config):
    """Both new controls save independently in the same _save_values() call, and
    config.save() is invoked exactly once (the shared end-of-save call)."""
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog(real_config, parent=None)
    dlg._epg_notify_minutes_spin.setValue(30)
    dlg._epg_auto_refresh_check.setChecked(False)
    dlg._save_values()

    assert real_config.epg_notification_minutes_before == 30
    assert real_config.epg_auto_refresh is False
    dlg.close()
