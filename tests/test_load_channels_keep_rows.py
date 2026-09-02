"""Tests for load_channels keep_rows parameter — avoid blank-flash on background refreshes.

The keep_rows parameter lets background refreshes (provider changes, exclusions apply,
metadata enrichment) keep the old channel list visible while the async query runs,
avoiding a multi-second blank flash. User-initiated loads (search, filter) still clear
immediately to show the loading state, since old rows misrepresent the new query.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.gui import icons as _icons


def _make_load_channels_host(qapp):
    """Build a minimal MainWindow for load_channels tests."""
    from PyQt6.QtWidgets import QListView
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)
    from tests.conftest import wire_channel_banner_widgets
    wire_channel_banner_widgets(win)
    win._bypass_global_exclusions = False
    win.all_channels = ["stale_channel_1", "stale_channel_2", "stale_channel_3"]
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win.config = MagicMock()
    win.config.global_filter_paused = True
    win.current_filter_state = {"_language_prefixes": [], "_region_prefixes": [],
                                "_platform_prefixes": [], "_quality_prefixes": []}
    win.search_input = MagicMock()
    win.search_input.text.return_value = ""
    win._search_debounce = MagicMock()
    win._bypass_tier1_filters = False
    win._details_genre_filter = None
    win._details_person_filter = None
    win._details_tag_filter = None
    win._details_category_filter = None
    win._details_id_filter = None
    win._id_filter_show_all = False
    win._search_page_size = 1000
    win._hidden_mode = False
    win._load_channels_token = [0]
    win._run_query = MagicMock()
    return win


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def test_keep_rows_leaves_the_model_populated_until_data_lands(qapp, monkeypatch):
    """load_channels(keep_rows=True) leaves old rows visible; no loading banner."""
    host = _make_load_channels_host(qapp)

    fake_session = MagicMock()
    host.db = MagicMock()
    host.db.get_session.return_value = fake_session

    import metatv.gui.main_window_channels as mw_channels_module
    class _FakeRepos:
        def __init__(self, _session):
            self.providers = MagicMock()
            self.providers.get_all.return_value = []

    monkeypatch.setattr(mw_channels_module, "RepositoryFactory", _FakeRepos)

    # Pre-load with 3 rows so we can verify they stay.
    host.channel_model.set_channels(
        [MagicMock(id=str(i), name=f"Channel {i}") for i in range(3)],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    assert host.channel_model.rowCount() == 3

    # Call load_channels(keep_rows=True)
    host.load_channels(keep_rows=True)

    # Model still has rows (not cleared).
    assert host.channel_model.rowCount() == 3
    # all_channels not reset.
    assert len(host.all_channels) == 3
    # No loading banner.
    assert not host._channel_banner.isVisible()
    # Status bar shows "Refreshing…".
    host.status_bar.showMessage.assert_called_with("Refreshing…")
    # Stats label was not set to "Loading…".
    for call in host.stats_label.setText.call_args_list:
        assert "Loading" not in call.args[0]


def test_default_load_still_clears_first(qapp, monkeypatch):
    """load_channels() with default keep_rows=False clears and shows loading banner."""
    host = _make_load_channels_host(qapp)

    fake_session = MagicMock()
    host.db = MagicMock()
    host.db.get_session.return_value = fake_session

    import metatv.gui.main_window_channels as mw_channels_module
    class _FakeRepos:
        def __init__(self, _session):
            self.providers = MagicMock()
            self.providers.get_all.return_value = []

    monkeypatch.setattr(mw_channels_module, "RepositoryFactory", _FakeRepos)

    # Pre-load with rows.
    host.channel_model.set_channels(
        [MagicMock(id=str(i), name=f"Channel {i}") for i in range(3)],
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
    )
    assert host.channel_model.rowCount() == 3

    # Call load_channels() without keep_rows (default False).
    host.load_channels()

    # Model cleared to 0 rows.
    assert host.channel_model.rowCount() == 0
    # all_channels reset.
    assert host.all_channels == []
    # Loading banner is visible with loading icon/text.
    assert host._channel_banner.isVisible()
    assert _icons.loading_icon in host._channel_banner.text()
    assert "Loading" in host._channel_banner.text()
    # Stats label set to "Loading channels…".
    stats_texts = [c.args[0] for c in host.stats_label.setText.call_args_list]
    assert any("Loading" in t for t in stats_texts)
    # Status bar shows "Loading channels…".
    host.status_bar.showMessage.assert_called_with("Loading channels…")


def test_provider_dependent_refresh_passes_keep_rows(monkeypatch):
    """_refresh_provider_dependent_views calls load_channels(keep_rows=True)."""
    # Test that the canonical refresh method passes keep_rows=True.
    # Use a mock/spy on load_channels at the import site.
    import metatv.gui.main_window_providers as mw_providers

    # Create a minimal mock of a host object.
    host = MagicMock()
    host.load_channels = MagicMock()

    # Directly call _refresh_provider_dependent_views on the mixin.
    # This binds self=host, so our mocked load_channels will be called.
    mw_providers._ProviderMixin._refresh_provider_dependent_views(host)

    # load_channels was called exactly once with keep_rows=True.
    host.load_channels.assert_called_once_with(keep_rows=True)
