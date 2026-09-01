"""The Sports sport/league/search selection must survive a restart.

Owner, 2026-09-01: *"Sports filters are not remembered on app restart"*.

The feature was written at both ends and connected at neither:

* ``SportsFilterBar.restore_filter_state()`` restores sports, leagues AND the
  fixture search — and had **zero callers**.
* ``Config.sports_filter_state`` was declared and **never written**; the
  owner's live config held ``sports_filter_state: {}``.

The LANE survived a restart because it saves separately (``config.sports_lane``,
written by ``_on_lane_clicked``), which is what made the gap look like a partial
bug rather than an unwired one.
"""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _view(tmp_path):
    from metatv.core.config import Config
    from metatv.gui.sports_view import SportsView
    cfg = Config(config_dir=tmp_path)
    return SportsView(None, cfg, lambda *a, **k: None), cfg


class TestTheSelectionIsSaved:

    def test_a_changed_selection_is_written_to_config(self, tmp_path, qapp):
        v, cfg = _view(tmp_path)
        v._filters_restored = True                     # past the initial restore
        v.filter_bar.get_filter_state = lambda: {
            "sport_types": ["baseball"], "league_names": [], "search": ""}
        v._reload_channels()

        assert cfg.sports_filter_state.get("sport_types") == ["baseball"], (
            "the selection was never persisted — this is the field that stayed "
            "{} in the owner's config")

    def test_an_unchanged_selection_does_not_rewrite_the_file(self, tmp_path, qapp):
        """This runs on every keystroke in the fixture search.

        A config write is a full file rewrite plus a backup copy, so writing
        unconditionally would put one on every character typed.
        """
        v, cfg = _view(tmp_path)
        v._filters_restored = True
        state = {"sport_types": ["baseball"], "league_names": [], "search": ""}
        v.filter_bar.get_filter_state = lambda: state
        v._reload_channels()

        saves = []
        real = type(cfg).save
        type(cfg).save = lambda self: saves.append(1)
        try:
            v._reload_channels()
            v._reload_channels()
        finally:
            type(cfg).save = real
        assert saves == [], "an unchanged selection still rewrote the config"

    def test_nothing_is_saved_before_the_restore_has_run(self, tmp_path, qapp):
        """Otherwise the empty startup state overwrites the saved one."""
        v, cfg = _view(tmp_path)
        cfg.sports_filter_state = {"sport_types": ["hockey"]}
        assert v._filters_restored is False
        v.filter_bar.get_filter_state = lambda: {
            "sport_types": [], "league_names": [], "search": ""}
        v._reload_channels()
        assert cfg.sports_filter_state == {"sport_types": ["hockey"]}, (
            "the startup reload wiped the saved selection before restoring it")


class TestTheSelectionIsRestored:

    def test_the_saved_state_reaches_the_filter_bar(self, tmp_path, qapp):
        v, cfg = _view(tmp_path)
        cfg.sports_filter_state = {
            "sport_types": ["baseball"], "league_names": ["MLB"], "search": "yankees"}
        seen = []
        v.filter_bar.restore_filter_state = seen.append
        v.filter_bar.load_taxonomy = lambda *a, **k: None

        v._on_taxonomy_loaded({"taxonomy": {}, "counts": {}})

        assert seen == [cfg.sports_filter_state], (
            "restore_filter_state was never called — it had zero callers")
        assert v._filters_restored is True

    def test_restore_happens_once_per_session(self, tmp_path, qapp):
        """A later taxonomy reload must not stamp the saved state back over
        whatever the user has since selected."""
        v, cfg = _view(tmp_path)
        cfg.sports_filter_state = {"sport_types": ["baseball"]}
        seen = []
        v.filter_bar.restore_filter_state = seen.append
        v.filter_bar.load_taxonomy = lambda *a, **k: None

        v._on_taxonomy_loaded({"taxonomy": {}, "counts": {}})
        v._on_taxonomy_loaded({"taxonomy": {}, "counts": {}})
        assert len(seen) == 1, "restored twice — a reload would undo the user's change"

    def test_an_empty_saved_state_restores_nothing(self, tmp_path, qapp):
        """A fresh install must not be handed an empty filter to apply."""
        v, cfg = _view(tmp_path)
        cfg.sports_filter_state = {}
        seen = []
        v.filter_bar.restore_filter_state = seen.append
        v.filter_bar.load_taxonomy = lambda *a, **k: None
        v._on_taxonomy_loaded({"taxonomy": {}, "counts": {}})
        assert seen == []
