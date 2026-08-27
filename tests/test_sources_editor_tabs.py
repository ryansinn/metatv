"""Behavioral tests for the Wave 7 Sources-editor relayout.

Covers:
  A. Left-column rows: no action buttons, full (untruncated) provider name.
  B. Summary-tab action bar: four labelled actions, each reaching its
     re-pointed signal/handler (Refresh / Analyze / Refresh Guide / Toggle).
  C. Busy state renders on the action bar (toggle + EPG-refresh), not the row.
  D. The three tabs exist in order, each with its specified widgets; no
     destructive zone in Settings.
  E. The persistent footer (Delete / Test Connection / Discard / Save Changes)
     is reachable from every tab and Delete is visually separated from the
     Save group; each footer button still reaches its original handler.
  F. The selected tab persists to config and restores.
  G. The "← Done Editing Sources" button is gone; the provider-name row
     carries a status dot.
  H. The sidebar Sources strip toggles the manager closed (running
     on_deactivate + hiding it) when it is already the active view.

All tests execute the real widget/handler code, not shape/string checks.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QMessageBox, QPushButton

from metatv.gui import icons as _icons
from tests.conftest import wire_nav_host


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# ── helpers ──────────────────────────────────────────────────────────────── #

@pytest.fixture()
def file_db(tmp_path):
    """File-backed Database (not :memory:) so pooled connections share tables."""
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_provider(db, name: str = "TestProv", username: str = "u1", is_active: bool = True) -> str:
    """Insert a ProviderDB row and return its id."""
    from metatv.core.database import ProviderDB
    pid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid,
            name=name,
            type="xtream",
            url="http://example.com:8080",
            username=username,
            password="pass",
            is_active=is_active,
            urls=[{"url": "http://example.com:8080", "priority": 0,
                   "is_active": True, "success_count": 0, "failure_count": 0}],
        ))
    return pid


def _sources_manager_view(qapp, db, config=None):
    """A real SourcesManagerView with a real embedded ProviderEditorView (the
    view requires the editor's real signals to wire its pass-through — a bare
    QWidget stub would lack them)."""
    from metatv.gui.provider_editor import ProviderEditorView
    from metatv.gui.sources_manager_view import SourcesManagerView
    editor = ProviderEditorView(db, config)
    return SourcesManagerView(config, db, editor)


# ─────────────────────────────────────────────────────────────────────────── #
# A. Left-column rows — no action buttons, full name
# ─────────────────────────────────────────────────────────────────────────── #

def test_left_row_has_no_action_buttons_and_full_name(qapp, file_db):
    long_name = "A Very Long Provider Name That Would Have Truncated Before"
    pid = _seed_provider(file_db, name=long_name)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()

    widget = view._item_widgets[pid]
    assert widget._action_btns == []
    assert widget._toggle_btn is None
    assert widget._epg_btn is None
    assert widget._name_lbl.text() == long_name


# ─────────────────────────────────────────────────────────────────────────── #
# B. Action bar — four labelled actions, each reaches its re-pointed signal
# ─────────────────────────────────────────────────────────────────────────── #

def test_action_bar_has_four_labelled_actions(qapp, file_db):
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)
    ed = view._provider_editor

    assert "Refresh" in ed._action_refresh_btn.text()
    assert "Analyze" in ed._action_analyze_btn.text()
    assert "Refresh Guide" in ed._epg_refresh_btn.text()
    assert ed._action_toggle_btn.text() in ("Disable", "Enable")


def test_refresh_action_reaches_refresh_requested_signal(qapp, file_db):
    """Reuses the pre-existing (previously unemitted) refresh_requested signal
    — already wired in main_window.py directly to refresh_provider."""
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)
    ed = view._provider_editor

    got = []
    ed.refresh_requested.connect(got.append)
    ed._action_refresh_btn.click()
    assert got == [pid]


def test_analyze_action_reaches_manager_view_signal(qapp, file_db):
    """New analyze_requested signal, passed through to the SAME public
    providerAnalyzeClicked signal main_window.py already connects."""
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)

    got = []
    view.providerAnalyzeClicked.connect(got.append)
    view._provider_editor._action_analyze_btn.click()
    assert got == [pid]


def test_toggle_action_reaches_manager_view_signal(qapp, file_db):
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)

    got = []
    view.providerToggleClicked.connect(got.append)
    view._provider_editor._action_toggle_btn.click()
    assert got == [pid]


def test_epg_refresh_action_reaches_manager_view_signal(qapp, file_db):
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)
    ed = view._provider_editor

    # The button is disabled without an effective EPG URL — give it one so the
    # click is genuinely reachable (proves the real gating, not a bypass).
    ed._epg_url_override_input.setText("http://example.com/xmltv.php")
    assert ed._epg_refresh_btn.isEnabled()

    got = []
    view.providerEpgRefreshClicked.connect(got.append)
    ed._epg_refresh_btn.click()
    assert got == [pid]


# ─────────────────────────────────────────────────────────────────────────── #
# C. Busy state renders on the action bar
# ─────────────────────────────────────────────────────────────────────────── #

def test_toggle_busy_renders_on_action_button(qapp, file_db):
    pid = _seed_provider(file_db, is_active=True)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)
    ed = view._provider_editor

    assert ed._action_toggle_btn.text() == "Disable"

    view.set_provider_busy(pid, True)
    assert _icons.loading_icon in ed._action_toggle_btn.text()
    assert not ed._action_toggle_btn.isEnabled()
    assert view.is_provider_busy(pid)

    view.set_provider_busy(pid, False)
    assert ed._action_toggle_btn.text() == "Disable"  # still active in the DB
    assert ed._action_toggle_btn.isEnabled()
    assert not view.is_provider_busy(pid)


def test_epg_busy_renders_on_action_button(qapp, file_db):
    pid = _seed_provider(file_db)
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid)
    ed = view._provider_editor

    view.set_provider_epg_refreshing(pid, True)
    assert _icons.loading_icon in ed._epg_refresh_btn.text()
    assert not ed._epg_refresh_btn.isEnabled()

    view.set_provider_epg_refreshing(pid, False)
    assert "Refresh Guide" in ed._epg_refresh_btn.text()


def test_busy_does_not_render_when_a_different_provider_is_selected(qapp, file_db):
    """Busy state for a provider NOT currently loaded in the editor must not
    touch the action bar (it reflects whichever provider is selected)."""
    pid_a = _seed_provider(file_db, name="A")
    pid_b = _seed_provider(file_db, name="B")
    view = _sources_manager_view(qapp, file_db)
    view.refresh()
    view.select_provider(pid_b)
    ed = view._provider_editor

    view.set_provider_busy(pid_a, True)
    assert ed._action_toggle_btn.isEnabled()  # B's button untouched by A's busy state
    assert view.is_provider_busy(pid_a)

    # Switching to A resyncs the busy visual from _busy_ids.
    view.select_provider(pid_a)
    assert not ed._action_toggle_btn.isEnabled()


# ─────────────────────────────────────────────────────────────────────────── #
# D. Three tabs, in order, each with its specified widgets
# ─────────────────────────────────────────────────────────────────────────── #

def _tab_content(ed, index: int):
    """Return the actual content widget inside tab *index* (unwraps the
    per-tab QScrollArea)."""
    return ed._tabs.widget(index).widget()


def test_three_tabs_exist_in_order(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    assert ed._tabs.count() == 3
    assert ed._tabs.tabText(0) == "Summary"
    assert ed._tabs.tabText(1) == "Connection"
    assert ed._tabs.tabText(2) == "Settings"


def test_summary_tab_contains_expected_widgets(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    summary = _tab_content(ed, 0)
    for w in (ed._icon_picker, ed._name_input, ed._status_dot_lbl, ed._enabled_check,
              ed._action_refresh_btn, ed._action_analyze_btn, ed._epg_refresh_btn,
              ed._action_toggle_btn, ed._acct_status_lbl, ed._acct_remaining_lbl,
              ed._refresh_acct_btn):
        assert summary.isAncestorOf(w), f"{w} not in Summary tab"


def test_connection_tab_contains_expected_widgets(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    connection = _tab_content(ed, 1)
    for w in (ed._username_input, ed._password_input, ed._url_list, ed._new_url_input):
        assert connection.isAncestorOf(w), f"{w} not in Connection tab"


def test_settings_tab_contains_expected_widgets_and_no_destructive_zone(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    settings = _tab_content(ed, 2)
    for w in (ed._refresh_combo, ed._force_adult_check, ed._epg_enabled_check,
              ed._epg_url_override_input, ed._epg_interval_combo, ed._epg_freshness_lbl):
        assert settings.isAncestorOf(w), f"{w} not in Settings tab"
    # No destructive zone here — Delete lives in the persistent footer only.
    assert not settings.isAncestorOf(ed._delete_btn)
    button_texts = [b.text() for b in settings.findChildren(QPushButton)]
    assert not any("Delete" in t for t in button_texts)


# ─────────────────────────────────────────────────────────────────────────── #
# E. Persistent footer — reachable from every tab, Delete separated
# ─────────────────────────────────────────────────────────────────────────── #

def test_footer_buttons_live_outside_every_tab(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    footer_buttons = (ed._delete_btn, ed._test_btn, ed._discard_btn, ed._save_btn)
    for i in range(ed._tabs.count()):
        ed._tabs.setCurrentIndex(i)
        tab_content = _tab_content(ed, i)
        for btn in footer_buttons:
            assert not tab_content.isAncestorOf(btn), (
                f"{btn.text()!r} must not live inside tab {i} ({ed._tabs.tabText(i)})"
            )
        # And they stay reachable (same parent) regardless of the selected tab.
        assert ed.isAncestorOf(ed._save_btn)


def test_delete_is_visually_separated_from_save_group(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    footer_layout = ed._delete_btn.parentWidget().layout()
    delete_idx = footer_layout.indexOf(ed._delete_btn)
    divider_idx = footer_layout.indexOf(ed._footer_divider)
    test_idx = footer_layout.indexOf(ed._test_btn)
    discard_idx = footer_layout.indexOf(ed._discard_btn)
    save_idx = footer_layout.indexOf(ed._save_btn)

    assert delete_idx < divider_idx < test_idx < discard_idx < save_idx


def test_delete_reaches_original_handler(qapp, file_db):
    pid = _seed_provider(file_db)
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    got = []
    ed.provider_delete_requested.connect(got.append)
    with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
        ed._delete_btn.click()
    assert got == [pid]


def test_discard_reaches_original_handler_from_footer(qapp, file_db):
    pid = _seed_provider(file_db, name="Stable Name")
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)
    ed._name_input.setText("Unsaved Edit")

    ed._discard_btn.click()
    assert ed._name_input.text() == "Stable Name"


def test_save_reaches_original_handler_while_on_a_non_summary_tab(qapp, file_db):
    """Save must work regardless of which tab is selected — it is a
    whole-source action, not scoped to Summary."""
    pid = _seed_provider(file_db, name="Orig")
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)
    ed._tabs.setCurrentIndex(2)  # Settings tab active
    ed._name_input.setText("Renamed While On Settings Tab")

    got = []
    ed.provider_saved.connect(got.append)
    ed._save_btn.click()
    assert got == [pid]


# ─────────────────────────────────────────────────────────────────────────── #
# F. Selected tab persists to config and restores
# ─────────────────────────────────────────────────────────────────────────── #

def test_selected_tab_persists_and_restores(qapp, file_db, tmp_path):
    from metatv.core.config import Config
    from metatv.gui.provider_editor import ProviderEditorView

    cfg = Config(config_dir=tmp_path)
    ed = ProviderEditorView(file_db, cfg)
    assert ed._tabs.currentIndex() == 0

    ed._tabs.setCurrentIndex(1)
    assert cfg.provider_editor_selected_tab == 1

    # A fresh editor reading the same config restores the saved tab, signals
    # blocked during restore (no spurious _on_tab_changed re-save).
    ed2 = ProviderEditorView(file_db, cfg)
    assert ed2._tabs.currentIndex() == 1


# ─────────────────────────────────────────────────────────────────────────── #
# G. "Done Editing Sources" removed; status dot on the name row
# ─────────────────────────────────────────────────────────────────────────── #

def test_done_editing_button_no_longer_exists(qapp, file_db):
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    texts = [b.text() for b in ed.findChildren(QPushButton)]
    assert not any("Done Editing" in t for t in texts)


def test_provider_name_row_carries_status_dot(qapp, file_db):
    pid = _seed_provider(file_db, is_active=True)
    from metatv.gui.provider_editor import ProviderEditorView
    ed = ProviderEditorView(file_db)
    ed.load_provider(pid)

    assert isinstance(ed._status_dot_lbl, QLabel)
    assert _tab_content(ed, 0).isAncestorOf(ed._status_dot_lbl)
    assert ed._status_dot_lbl.text() == _icons.status_dot_icon
    assert "Active" in ed._status_dot_lbl.toolTip()


# ─────────────────────────────────────────────────────────────────────────── #
# H. Sources strip toggles the manager closed when already active
# ─────────────────────────────────────────────────────────────────────────── #

def test_sources_strip_toggle_opens_when_not_active():
    from metatv.gui.main_window import MainWindow
    calls = []
    me = SimpleNamespace(
        view_mode="list",
        switch_to_list_view=lambda: calls.append("list"),
        switch_to_sources_manager=lambda: calls.append("sources_manager"),
    )
    MainWindow.on_sources_manager_toggle(me)
    assert calls == ["sources_manager"]


def test_sources_strip_toggle_closes_and_deactivates_when_already_active():
    """Clicking the strip while the Sources manager is already the active view
    must close it (return to the channel list) AND run its on_deactivate() —
    exercised through the REAL on_sources_manager_toggle/switch_to_list_view/
    _hide_all_content_views chain on a minimal host that actually inherits
    _NavMixin (so self.<method>() resolves to the real bound methods, not a
    re-implemented check)."""
    from metatv.gui.main_window_nav import _NavMixin

    class _FakeHost(_NavMixin):
        pass

    me = _FakeHost()
    wire_nav_host(me)
    # _hide_all_content_views() resets the channel-render banners, which
    # live outside every view; this skeleton host is not a full MainWindow
    # so it needs that method wired in (shared factory — see conftest).
    from tests.conftest import wire_header_search_sync, wire_hide_channel_banners
    wire_hide_channel_banners(me)
    wire_header_search_sync(me)
    me.view_mode = "sources_manager"
    me._in_provider_edit_mode = True
    me.epg_view = MagicMock()
    me.discover_view = MagicMock()
    me.preferences_view = MagicMock()
    me.channels_list = MagicMock()
    me.series_tree = MagicMock()
    me.provider_editor = MagicMock()
    me.search_controls = MagicMock()
    me._hidden_banner = MagicMock()
    me.back_button = MagicMock()
    me.breadcrumb_label = MagicMock()
    me.sources_manager_view = MagicMock()
    me.search_chip = MagicMock()
    me.epg_chip = MagicMock()
    me.prefs_chip = MagicMock()
    me.discover_chip = MagicMock()
    me.search_input = MagicMock()
    me.status_bar = MagicMock()
    me.current_series = None
    me.series_data = None
    me.sources_manager_view.isVisible.return_value = True
    me.epg_view.isVisible.return_value = False
    me.discover_view.isVisible.return_value = False
    me.preferences_view.isVisible.return_value = False

    me.on_sources_manager_toggle()

    assert me.view_mode == "list"
    me.sources_manager_view.on_deactivate.assert_called_once()
    me.sources_manager_view.setVisible.assert_any_call(False)
