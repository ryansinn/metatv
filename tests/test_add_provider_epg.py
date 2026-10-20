"""EPG pull on source refresh.

Pinned on the real code path (the new source's Enable-EPG checkbox is covered
in test_add_source_in_editor, where sources are added now):
2. `MainWindow.on_provider_refresh_finished` calls `_maybe_refresh_provider_epg` on EVERY
   successful refresh (newly-added or ordinary) and clears the add flag — but NOT when the
   load failed. The fetch's gating (epg_enabled / usable URL) is covered in
   test_epg_on_source_refresh.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest



@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ── 1. (moved) the new source's epg_enabled: tests/test_add_source_in_editor.py ─ #


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
    # Post-refresh EPG fetch is exercised at the seam here; its gating
    # (epg_enabled / usable URL) is covered in test_epg_on_source_refresh. Mock it
    # so the handler test needs no seeded DB.
    mw._maybe_refresh_provider_epg = MagicMock()
    # SPORT-7's stamp seam — same treatment: it opens a real session_scope on
    # self.db, which a __new__'d shell doesn't have.
    mw._mark_catalog_refreshed = MagicMock()
    # Set so hasattr() resolves cleanly — on a __new__'d QMainWindow a *missing*
    # attr raises RuntimeError from PyQt rather than returning False.
    mw.stream_retry_manager = MagicMock()
    return mw


def _thread(provider_id):
    t = MagicMock()
    t.provider_id = provider_id
    t.prefix_stats = None
    return t


def test_successful_refresh_triggers_epg_and_clears_add_flag(qapp):
    """A successful refresh fetches EPG (via the gated seam) and clears the add flag."""
    mw = _main_window_stub()
    mw.refreshing_providers = {"p1"}
    mw._epg_fetch_after_add = {"p1"}

    mw.on_provider_refresh_finished("notif", True, "done", _thread("p1"))

    mw._maybe_refresh_provider_epg.assert_called_once_with("p1")
    assert "p1" not in mw._epg_fetch_after_add  # add flag cleared (now just bookkeeping)


def test_ordinary_refresh_also_triggers_epg(qapp):
    """A refresh of an existing (non-newly-added) source now ALSO pulls EPG.

    This is the behaviour change: previously only a flagged add fetched EPG; now
    every successful refresh does (gating happens inside _maybe_refresh_provider_epg).
    """
    mw = _main_window_stub()
    mw.refreshing_providers = {"p2"}
    mw._epg_fetch_after_add = set()  # not a fresh add

    mw.on_provider_refresh_finished("notif", True, "done", _thread("p2"))

    mw._maybe_refresh_provider_epg.assert_called_once_with("p2")


def test_failed_load_does_not_fetch_epg(qapp):
    """A failed channel load must not fetch EPG, and drops the stale add flag."""
    mw = _main_window_stub()
    mw._epg_fetch_after_add = {"p3"}

    mw.on_provider_refresh_finished("notif", False, "boom", _thread("p3"))

    mw._maybe_refresh_provider_epg.assert_not_called()
    assert "p3" not in mw._epg_fetch_after_add  # stale flag dropped
