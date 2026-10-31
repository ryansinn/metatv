"""Finished events ("End |", "ENDED |") are hidden unless "Show finished events" is on.

A provider keeps listing a game after it is over and marks it with a name
prefix (650 such channels on the owner's TREX source). The setting rides the
Global-Exclusion prefix axis, so every surface that applies the exclusions —
the channel list, EPG On now, Other Versions, every faceted count — drops them
without a per-surface change. Real ``Database`` on a ``tmp_path`` file.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from metatv.core.config import Config
from metatv.core.database import ChannelDB, Database
from metatv.core.filter_utils import (
    channel_exclusion_criterion, global_exclusion_set, is_channel_excluded,
)


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    with d.session_scope() as s:
        for name, prefix in [("End | Pacers vs. Bucks", "END"),
                             ("ENDED | AZTEC VS. GALLUP", "ENDED"),
                             ("LIVE | Suns vs. Thunder", "LIVE"),
                             ("US| ESPN", "US")]:
            s.add(ChannelDB(id=str(uuid.uuid4()), source_id=str(uuid.uuid4()), provider_id="p",
                            name=name, media_type="live", detected_prefix=prefix,
                            detected_region="US"))
    yield d
    d.close()


def _visible(db, config) -> set[str]:
    excluded = global_exclusion_set(config)
    with db.session_scope(commit=False) as s:
        rows = s.execute(select(ChannelDB.name, ChannelDB.detected_prefix, ChannelDB.detected_region)
                         .where(channel_exclusion_criterion(excluded, ChannelDB))).all()
    # The Python twin must agree with the SQL one row for row.
    assert all(not is_channel_excluded(p, r, excluded) for _n, p, r in rows)
    return {n for n, _p, _r in rows}


def test_finished_events_are_hidden_by_default(db):
    assert _visible(db, Config()) == {"LIVE | Suns vs. Thunder", "US| ESPN"}


def test_show_finished_events_brings_them_back(db):
    cfg = Config()
    cfg.show_ended_events = True
    assert len(_visible(db, cfg)) == 4


def test_pausing_global_exclusions_shows_them_too(db):
    cfg = Config()
    cfg.global_filter_paused = True
    assert len(_visible(db, cfg)) == 4


def test_the_default_does_not_light_the_exclusions_chip():
    """Hiding finished events is a default, not a user exclusion: the chip stays inactive."""
    from metatv.gui.main_window_nav import _NavMixin

    class _Chip:
        def set_filter_state(self, active, paused):
            self.active = active

    stub = type("Stub", (), {})()
    stub.config, stub._filter_chip = Config(), _Chip()
    _NavMixin._update_filter_btn_state(stub)
    assert stub._filter_chip.active is False


def test_global_exclusions_dialog_checkbox_saves_the_setting(qtbot, db):
    from metatv.gui.global_filter_dialog import GlobalFilterDialog
    cfg = Config()
    dlg = GlobalFilterDialog(db, cfg)
    qtbot.addWidget(dlg)
    assert dlg._ended_cb.isChecked(), "hidden by default: the box reads 'Hide finished events'"
    dlg._ended_cb.setChecked(False)
    dlg._save_and_accept()
    assert cfg.show_ended_events is True
