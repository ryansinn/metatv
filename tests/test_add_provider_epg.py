"""PR-2-C: Enable-EPG checkbox on the Add-Provider dialog + first EPG pull on add.

Two behaviors are pinned, both executing the real code paths:
1. `AddProviderDialog` persists `epg_enabled` from its checkbox onto the new ProviderDB row.
2. `MainWindow.on_provider_refresh_finished` triggers a one-time `force_refresh_provider`
   for a freshly-added provider (flagged in `_epg_fetch_after_add`) when its channel load
   succeeds — and does NOT for an ordinary re-refresh or when the load failed.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ProviderDB


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


# ── 1. Dialog persists epg_enabled ───────────────────────────────────────────── #

@pytest.mark.parametrize("checked", [True, False])
def test_add_provider_dialog_persists_epg_enabled(qapp, db, checked):
    from metatv.gui.dialogs import AddProviderDialog

    dlg = AddProviderDialog(None, MagicMock(), db, MagicMock())
    dlg.name_input.setText("New Src")
    dlg.url_input.setText("http://host:8080")
    dlg.epg_enabled_check.setChecked(checked)

    dlg.add_provider()  # parent is None → just creates the row + accept()

    with db.session_scope(commit=False) as session:
        prov = session.query(ProviderDB).filter_by(name="New Src").first()
        assert prov is not None
        assert bool(prov.epg_enabled) is checked


# ── 2. Post-add first-EPG-pull trigger ───────────────────────────────────────── #

def _main_window_stub():
    """A MainWindow shell with only the attributes on_provider_refresh_finished touches."""
    from metatv.gui.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)
    mw.active_threads = []
    mw.refreshing_providers = set()
    mw._epg_fetch_after_add = set()
    mw.notification_manager = MagicMock()
    mw.epg_manager = MagicMock()
    mw._refresh_provider_dependent_views = MagicMock()
    # Set so hasattr() resolves cleanly — on a __new__'d QMainWindow a *missing*
    # attr raises RuntimeError from PyQt rather than returning False.
    mw.stream_retry_manager = MagicMock()
    return mw


def _thread(provider_id):
    t = MagicMock()
    t.provider_id = provider_id
    t.prefix_stats = None
    return t


def test_flagged_add_triggers_first_epg_fetch_once(qapp):
    mw = _main_window_stub()
    mw.refreshing_providers = {"p1"}
    mw._epg_fetch_after_add = {"p1"}

    mw.on_provider_refresh_finished("notif", True, "done", _thread("p1"))

    mw.epg_manager.force_refresh_provider.assert_called_once_with("p1")
    assert "p1" not in mw._epg_fetch_after_add  # flag cleared (no repeat)


def test_ordinary_refresh_does_not_trigger_epg_fetch(qapp):
    mw = _main_window_stub()
    mw.refreshing_providers = {"p2"}
    mw._epg_fetch_after_add = set()  # not a fresh add

    mw.on_provider_refresh_finished("notif", True, "done", _thread("p2"))

    mw.epg_manager.force_refresh_provider.assert_not_called()


def test_failed_load_clears_flag_without_fetch(qapp):
    mw = _main_window_stub()
    mw._epg_fetch_after_add = {"p3"}

    mw.on_provider_refresh_finished("notif", False, "boom", _thread("p3"))

    mw.epg_manager.force_refresh_provider.assert_not_called()
    assert "p3" not in mw._epg_fetch_after_add  # stale flag dropped
