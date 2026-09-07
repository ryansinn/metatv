"""LIVE-1 — Settings -> Content -> "Live catalog refresh" round-trips through config.

Same pattern as ``test_adult_content_control.py`` for the sibling combo on the
same tab: a control that renders but does not persist is the same bug in a
new place, so this proves both directions (load from config, save back to
config) using the REAL ``SettingsDialog`` constructor — not a ``__new__``
skeleton — so the whole Content tab actually builds and
``wire_settings_content_widgets`` never diverges from the real
``_build_content_tab``. The config is ``settings_config_double`` (a real
``Config``) rather than a hand-written stub, for the reason that factory's
docstring gives.

This also covers the retirement of the combo's sixth option (SETTINGS-1,
ledger row D47). "Whenever Sports or Events opens" was still offered after
#731 retired both views and dead-code sweep B deleted the hook it drove, so
choosing it did nothing whatsoever. The combo now offers Manual plus the four
intervals, and a config that had stored the retired value is rewritten once on
load by ``Config._migrate_live_refresh_mode``, mirroring
``_migrate_background_polling_defaults``.

Why the rewrite is not optional: ``SettingsDialog._load_values`` falls back to
``findData("manual")`` when the stored mode is not on the combo. Without the
migration the dialog would DISPLAY "Manual" while config.yaml still said
``on_view_open`` — a disagreement that persists until the user happens to press
Save, and that nothing logs.
"""

from metatv.core.catalog_refresh import LIVE_REFRESH_INTERVALS, RETIRED_LIVE_REFRESH_MODES
from metatv.core.config import Config
from metatv.gui.settings_dialog import SettingsDialog
from tests.conftest import settings_config_double

LIVE_MODES = ("manual", "15m", "30m", "1h", "3h")


def test_content_tab_has_a_live_refresh_combo(qapp):
    """The control must exist at all — a setting you cannot find does not exist."""
    dlg = SettingsDialog(settings_config_double(), parent=None)
    try:
        assert dlg._live_refresh_mode_combo is not None
        values = {dlg._live_refresh_mode_combo.itemData(i)
                  for i in range(dlg._live_refresh_mode_combo.count())}
        assert values == set(LIVE_MODES)
    finally:
        dlg.close()


def test_the_combo_offers_no_retired_mode(qapp):
    """The D47 defect, asserted directly rather than implied by the set above.

    Every offered value must be one the tick can actually act on: "manual", or
    an interval ``LIVE_REFRESH_INTERVALS`` names. An option that does nothing
    when chosen is the thing that shipped, and naming two views that no longer
    exist is how it was found.
    """
    dlg = SettingsDialog(settings_config_double(), parent=None)
    try:
        offered = {dlg._live_refresh_mode_combo.itemData(i)
                   for i in range(dlg._live_refresh_mode_combo.count())}
        assert not (offered & set(RETIRED_LIVE_REFRESH_MODES)), (
            "the combo still offers a retired mode: "
            f"{sorted(offered & set(RETIRED_LIVE_REFRESH_MODES))}"
        )
        assert offered - {"manual"} == set(LIVE_REFRESH_INTERVALS), (
            "every non-manual option must be an interval the tick recognizes"
        )
        labels = [dlg._live_refresh_mode_combo.itemText(i)
                  for i in range(dlg._live_refresh_mode_combo.count())]
        assert not any("Sports" in t or "Events" in t for t in labels), labels
    finally:
        dlg.close()


def test_live_refresh_mode_round_trips_through_config(qapp):
    cfg = settings_config_double(live_refresh_mode="30m")
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._live_refresh_mode_combo.currentData() == "30m", (
            "combo did not load the stored mode"
        )
        dlg._live_refresh_mode_combo.setCurrentIndex(
            dlg._live_refresh_mode_combo.findData("1h")
        )
        dlg._save_values()
        assert cfg.live_refresh_mode == "1h", "combo did not save back to config"
    finally:
        dlg.close()


def test_every_live_refresh_mode_survives_the_round_trip(qapp):
    """All five modes, not just the one that happens to be first."""
    for mode in LIVE_MODES:
        cfg = settings_config_double(live_refresh_mode=mode)
        dlg = SettingsDialog(cfg, parent=None)
        try:
            assert dlg._live_refresh_mode_combo.currentData() == mode
            dlg._save_values()
            assert cfg.live_refresh_mode == mode
        finally:
            dlg.close()


# ---------------------------------------------------------------------------
# The one-time config migration off the retired value (SETTINGS-1)
# ---------------------------------------------------------------------------

def _load_from_disk(body: str) -> Config:
    """Write a config.yaml into the isolated fake home and load it for real.

    The autouse ``_isolate_user_config`` fixture points ``Path.home()`` at a
    per-test tmp dir, and ``Config.load()`` reads ``~/.config/metatv``, so this
    exercises the actual upgrade path — YAML on disk, parsed and migrated —
    rather than a hand-constructed model.

    ``database_url`` is not decoration: ``load()`` treats a file without one as
    empty/corrupt and silently substitutes a FRESH default config, which already
    has ``live_refresh_mode: manual`` and the version stamped. A migration test
    without it passes no matter what the migration does.
    """
    from pathlib import Path

    config_dir = Path.home() / ".config" / "metatv"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        f"database_url: sqlite:///{config_dir / 'metatv.db'}\n{body}", encoding="utf-8")
    config, recovered = Config.load()
    assert not recovered, "load() fell back to a backup — the YAML was rejected"
    assert config.database_url.endswith("metatv.db"), (
        "load() substituted a fresh default config instead of reading the file"
    )
    return config


def test_a_stored_retired_mode_loads_as_manual_and_stamps_the_version():
    """The upgrade path: a real config.yaml carrying the retired value.

    ``save()`` writes every field, so this is the shape an existing install
    actually has on disk — an explicit stored value, not a default nobody
    chose, and an explicit stored value beats any default.
    """
    cfg = _load_from_disk("live_refresh_mode: on_view_open\n")
    assert cfg.live_refresh_mode == "manual"
    assert cfg.live_refresh_mode_version == 1


def test_a_config_already_at_the_version_is_left_alone():
    """Version-gated, not re-derived on every load.

    If the migration re-ran, a deliberate later choice could be rewritten out
    from under the user on the next launch — the trap the two sibling
    migrations' version markers exist to avoid. So a value that is already
    stamped survives, even a retired one put back by hand.
    """
    cfg = _load_from_disk(
        "live_refresh_mode: on_view_open\nlive_refresh_mode_version: 1\n")
    assert cfg.live_refresh_mode == "on_view_open"
    assert cfg.live_refresh_mode_version == 1


def test_a_live_mode_is_not_touched():
    """Only a RETIRED value is rewritten — a real choice is preserved."""
    cfg = _load_from_disk("live_refresh_mode: 1h\n")
    assert cfg.live_refresh_mode == "1h"
    assert cfg.live_refresh_mode_version == 1


def test_the_migration_is_logged():
    """A value the user chose is being changed for them, so it has to be
    findable afterwards — the same reason the polling-defaults migration logs."""
    from loguru import logger

    seen: list[str] = []
    sink = logger.add(seen.append, level="INFO")
    try:
        _load_from_disk("live_refresh_mode: on_view_open\n")
    finally:
        logger.remove(sink)
    assert any("live_refresh_mode" in line and "on_view_open" in line
               for line in seen), seen


def test_the_migrated_value_is_one_the_combo_can_show(qapp):
    """The two halves have to agree.

    Whatever the migration produces must be selectable, or the dialog is back
    to displaying one thing while config.yaml says another — which is the
    defect the migration exists to prevent, not a new one.
    """
    cfg = _load_from_disk("live_refresh_mode: on_view_open\n")
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._live_refresh_mode_combo.findData(cfg.live_refresh_mode) >= 0
        assert dlg._live_refresh_mode_combo.currentData() == "manual"
    finally:
        dlg.close()
