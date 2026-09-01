"""Walking the Settings section list must not rewrite the whole config each time.

Owner's log, 2026-09-01 — six full config writes inside sixteen seconds, from
nothing but clicking down the left-hand list, then a seventh for the OK::

    04:32:15.591  Backed up config to .../config.yaml.bak
    04:32:15.661  Saved config to .../config.yaml
    04:32:16.497  Backed up config ...
    04:32:16.556  Saved config ...
    ... four more ...
    04:32:31.282  Settings saved

``Config.save()`` is not cheap. It serialises **299 keys** to YAML and copies
the whole file to ``.bak`` first — on this config that is **129 KB written
twice**, on the main thread, measured at 14 ms on an idle machine and **55-93
ms** in the running app.

And #638 made it worse before this fix: splitting Interface into three pages
means more sections, so more clicks, so more whole-file rewrites.

Nothing is lost by waiting: ``done()`` calls ``_persist_dialog_state`` on every
close path — OK, Cancel, and the window button — so the row is still
remembered, written once instead of once per click.
"""
from __future__ import annotations


import pytest

from metatv.core.config import Config
from metatv.gui.settings_dialog import SettingsDialog


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def counting_config(tmp_path, monkeypatch):
    """A real Config on a tmp dir, plus a count of how often it is written.

    Patched on the CLASS: ``Config`` is a pydantic model and rejects setting an
    attribute it has no field for, so an instance-level patch raises
    ``ValueError: "Config" object has no field "save"``.
    """
    calls: list[int] = []
    real_save = Config.save

    def _counted(self, *a, **kw):
        calls.append(1)
        return real_save(self, *a, **kw)

    monkeypatch.setattr(Config, "save", _counted)
    return Config(config_dir=tmp_path / "config"), calls


def test_changing_section_writes_nothing(counting_config, qapp):
    """Selecting a section records the row. The write happens on close."""
    cfg, saves = counting_config
    dlg = SettingsDialog(cfg, parent=None)
    saves.clear()      # ignore construction

    # Driven through the nav, not by calling the handler: that is the path the
    # user takes, and it is what makes done()'s current_row() read agree.
    for row in range(dlg._nav.count()):
        dlg._nav.set_current_row(row)

    assert saves == [], (
        f"{len(saves)} full config rewrites from walking "
        "the section list — each one serialises 299 keys and copies 129 KB to "
        ".bak, on the main thread")
    dlg.close()


def test_the_row_is_still_remembered_in_memory(counting_config, qapp):
    """Non-degeneracy: not writing must not mean not recording."""
    cfg, _saves = counting_config
    dlg = SettingsDialog(cfg, parent=None)
    dlg._nav.set_current_row(3)
    assert cfg.settings_dialog_section == 3
    dlg.close()


def test_closing_the_dialog_persists_it_exactly_once(counting_config, qapp):
    """done() is the one write, and it covers OK, Cancel and the window button."""
    cfg, saves = counting_config
    dlg = SettingsDialog(cfg, parent=None)
    dlg._nav.set_current_row(2)
    saves.clear()

    dlg.done(0)                               # the Cancel/close path

    assert len(saves) == 1, (
        "the selected section is no longer persisted on close — it would be "
        "forgotten between launches")
    assert cfg.settings_dialog_section == 2


def test_a_walk_then_close_is_one_write_not_nine(counting_config, qapp):
    """The whole point, stated as the user's actual interaction.

    Eight sections after #638. Pre-fix this was one write per click plus one
    for the close; it is now one in total.
    """
    cfg, saves = counting_config
    dlg = SettingsDialog(cfg, parent=None)
    saves.clear()

    for row in range(dlg._nav.count()):
        dlg._nav.set_current_row(row)
    dlg.done(0)

    assert len(saves) == 1, (
        f"walking {dlg._nav.count()} sections and closing cost "
        f"{len(saves)} whole-config rewrites")


def test_the_config_really_is_big_enough_for_this_to_matter(counting_config):
    """Guards the premise, so the fix cannot look pointless later.

    If the config were ten keys this would be noise. It is not: the shipped
    default already has hundreds of fields before a user adds anything, and the
    owner's real file is 299 keys / 129 KB.
    """
    cfg, _saves = counting_config
    assert len(cfg.model_dump()) > 150
