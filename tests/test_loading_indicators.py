"""Behavioral tests for the loading-indicators feature.

Each async-loaded surface must show a transient "Loading…" placeholder from the
moment a load starts until the first result/error arrives, so the user never sees
the stale empty/zero state during the (multi-second) load window.

These drive the REAL main-thread methods (refresh()/load_channels()/result slots)
against real widgets and assert the rendered placeholder appears, then that the
result slot replaces it. No shape/substring-of-source assertions.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _stub_collapsible_state(obj) -> None:
    """Give a CollapsibleSection-derived object the minimal attrs set_empty() reads."""
    obj.is_empty = True
    obj.is_collapsed = False
    obj._user_collapsed = False


# ---------------------------------------------------------------------------
# 1. KEYSTONE — BackgroundRefreshMixin (Favorites/History/Queue/Alerts share this)
# ---------------------------------------------------------------------------

def _make_mixin_section(qapp):
    """A minimal real BackgroundRefreshMixin + CollapsibleSection, no DB/config."""
    from PyQt6.QtWidgets import QListWidget
    from PyQt6.QtCore import pyqtSignal
    from metatv.gui.sidebar.background_refresh import BackgroundRefreshMixin
    from metatv.gui.sidebar.base import CollapsibleSection

    class _Section(BackgroundRefreshMixin, CollapsibleSection):
        _data_ready = pyqtSignal(object)

        def _refresh_list(self):
            return self._list

        def _load_error_message(self):
            return "Couldn't load things"

        def _populate_rows(self, rows):
            from PyQt6.QtWidgets import QListWidgetItem
            for r in rows:
                self._list.addItem(QListWidgetItem(str(r)))
            self.set_empty(not rows)

    sec = _Section.__new__(_Section)
    _stub_collapsible_state(sec)
    sec._list = QListWidget()
    sec.set_empty = lambda *a, **k: None  # avoid splitter geometry in headless test
    return sec


def test_background_refresh_mixin_refresh_adds_loading_row(qapp):
    sec = _make_mixin_section(qapp)
    sec._executor = MagicMock()  # don't actually run the worker

    sec.refresh()

    # Exactly one row: the non-selectable loading placeholder.
    assert sec._list.count() == 1
    item = sec._list.item(0)
    assert _icons.loading_icon in item.text()
    from PyQt6.QtCore import Qt
    assert item.flags() == Qt.ItemFlag.NoItemFlags
    sec._executor.submit.assert_called_once()


def test_background_refresh_mixin_on_data_ready_replaces_loading_row(qapp):
    sec = _make_mixin_section(qapp)
    sec._executor = MagicMock()
    sec.refresh()  # places the loading row
    assert _icons.loading_icon in sec._list.item(0).text()

    sec._on_data_ready(["alpha", "beta"])

    # Loading row gone; real rows rendered.
    texts = [sec._list.item(i).text() for i in range(sec._list.count())]
    assert texts == ["alpha", "beta"]
    assert all(_icons.loading_icon not in t for t in texts)


def test_background_refresh_mixin_loading_message_default(qapp):
    sec = _make_mixin_section(qapp)
    sec._executor = MagicMock()
    sec.refresh()
    assert "Loading" in sec._list.item(0).text()


def test_background_refresh_mixin_section_can_override_loading_message(qapp):
    sec = _make_mixin_section(qapp)
    sec._executor = MagicMock()
    sec._loading_message = lambda: "Loading widgets…"
    sec.refresh()
    assert "Loading widgets" in sec._list.item(0).text()


# ---------------------------------------------------------------------------
# 2. show_loading on the QTreeWidget variant (WatchAlertsSection)
# ---------------------------------------------------------------------------

def test_alerts_tree_show_loading_adds_top_level_loading_row(qapp):
    from PyQt6.QtWidgets import QTreeWidget
    from PyQt6.QtCore import Qt
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    sec = WatchAlertsSection.__new__(WatchAlertsSection)
    _stub_collapsible_state(sec)
    sec.set_empty = lambda *a, **k: None
    tree = QTreeWidget()

    sec.show_loading(tree, sec._loading_message())

    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert _icons.loading_icon in item.text(0)
    assert "alerts" in item.text(0).lower()        # section overrides the default message
    assert item.flags() == Qt.ItemFlag.NoItemFlags


# ---------------------------------------------------------------------------
# 3. RecommendedSection (documented BackgroundRefreshMixin exception)
# ---------------------------------------------------------------------------

def _make_recommended(qapp):
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.recommended import RecommendedSection

    sec = RecommendedSection.__new__(RecommendedSection)
    _stub_collapsible_state(sec)
    sec.set_empty = lambda *a, **k: None
    sec._list = QListWidget()
    sec._executor = MagicMock()
    return sec


def test_recommended_refresh_adds_loading_row(qapp):
    from PyQt6.QtCore import Qt
    sec = _make_recommended(qapp)

    sec.refresh()

    assert sec._list.count() == 1
    item = sec._list.item(0)
    assert _icons.loading_icon in item.text()
    assert "recommendations" in item.text().lower()
    assert item.flags() == Qt.ItemFlag.NoItemFlags
    sec._executor.submit.assert_called_once()


def test_recommended_on_rec_data_ready_none_replaces_loading_with_empty_state(qapp):
    sec = _make_recommended(qapp)
    sec.refresh()
    assert _icons.loading_icon in sec._list.item(0).text()

    sec._on_rec_data_ready(None)  # None = valid "no weights" empty state

    assert sec._list.count() == 1
    text = sec._list.item(0).text()
    assert _icons.loading_icon not in text
    assert "Rate movies/series" in text


# ---------------------------------------------------------------------------
# 4. Recommendations PAGE — preferences_view header
# ---------------------------------------------------------------------------

def _make_preferences_view(qapp):
    from metatv.gui.preferences_view import PreferencesView

    view = PreferencesView.__new__(PreferencesView)
    view._active = True
    view._executor = MagicMock()
    view._header_label = MagicMock()
    return view


def test_preferences_refresh_sets_loading_header(qapp):
    view = _make_preferences_view(qapp)

    view.refresh()

    view._header_label.setText.assert_called_once()
    (msg,), _ = view._header_label.setText.call_args
    assert "Loading" in msg
    view._executor.submit.assert_called_once()


def test_preferences_render_overwrites_loading_header_no_ratings(qapp):
    """_render (called by _on_pref_data_ready) overwrites the loading header even
    when there genuinely are no ratings — so 'No ratings yet' shows post-load."""
    from metatv.core.preference_engine import AttributeWeights

    view = _make_preferences_view(qapp)
    view.config = MagicMock()
    view.config.like_icon = "+"
    view.config.dislike_icon = "-"
    view.config.muted_attributes = {}
    # The header is set first in _render (before any layout work). We stub _attr_layout
    # so the path up to/just past the header runs; anything after may raise and is
    # swallowed below — we assert only on the header calls.
    view._attr_layout = MagicMock(count=MagicMock(return_value=0))

    empty_weights = AttributeWeights()
    assert empty_weights.is_empty()

    view.refresh()  # sets "Loading recommendations…"
    try:
        view._render(empty_weights, [])
    except Exception:
        # _render does more than the header; we only assert the header call below.
        pass

    # The LAST setText was the real "No ratings yet …" header, not the loading text.
    texts = [c.args[0] for c in view._header_label.setText.call_args_list]
    assert any("Loading" in t for t in texts)          # loading shown first
    assert any("No ratings yet" in t for t in texts)   # then overwritten with real state
    assert "Loading" not in texts[-1]


# ---------------------------------------------------------------------------
# 5. Channel list / initial Search — load_channels placeholder
# ---------------------------------------------------------------------------

def _make_load_channels_host(qapp):
    from PyQt6.QtWidgets import QListView, QLabel, QPushButton
    from PyQt6.QtCore import Qt
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    # Virtualized model + view replace the old QListWidget
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)
    # Banner widgets (created in setup_ui; stub them for the test)
    win._channel_banner = QLabel()
    win._channel_filter_btn = QPushButton()
    win.all_channels = ["stale"]
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win.config = MagicMock()
    # global_filter_paused=True takes the short branch that skips category-filter
    # resolution, keeping this test focused on the placeholder.
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
    win._run_query = MagicMock()  # no-op: we only test the placeholder being set
    return win


def test_load_channels_shows_loading_placeholder(qapp, monkeypatch):
    host = _make_load_channels_host(qapp)

    # Resolve the provider list without a real DB: a minimal fake DB returning no
    # providers lets load_channels run to the _run_query call (which we mocked).
    fake_session = MagicMock()
    host.db = MagicMock()
    host.db.get_session.return_value = fake_session

    # B10-8: load_channels moved to _ChannelListMixin in main_window_channels.py,
    # so RepositoryFactory is resolved from that module's namespace.
    import metatv.gui.main_window_channels as mw_channels_module

    class _FakeRepos:
        def __init__(self, _session):
            self.providers = MagicMock()
            self.providers.get_all.return_value = []

    monkeypatch.setattr(mw_channels_module, "RepositoryFactory", _FakeRepos)

    host.load_channels()

    # all_channels was reset; model has 0 rows (channel_model received empty set_channels).
    assert host.all_channels == []
    assert host.channel_model.rowCount() == 0
    # Loading banner is visible and contains the loading text.
    assert host._channel_banner.isVisible()
    assert _icons.loading_icon in host._channel_banner.text()
    assert "Loading" in host._channel_banner.text()
    # Stats label was set to the loading text.
    stats_texts = [c.args[0] for c in host.stats_label.setText.call_args_list]
    assert any("Loading" in t for t in stats_texts)
    # The heavy query was scheduled (not run inline).
    host._run_query.assert_called_once()


def test_channels_load_error_clears_loading_placeholder(qapp):
    from PyQt6.QtWidgets import QListView, QLabel, QPushButton
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)
    win._channel_banner = QLabel()
    win._channel_filter_btn = QPushButton()
    win.stats_label = MagicMock()
    win.status_bar = MagicMock()
    win._clear_provider_busy = MagicMock()

    # Seed the loading banner like load_channels would.
    win._channel_banner.setText(f"{_icons.loading_icon} Loading channels…")
    win._channel_banner.setVisible(True)

    win._on_channels_load_error(RuntimeError("boom"))

    # Loading banner hidden; error stats set.
    assert not win._channel_banner.isVisible()
    win.stats_label.setText.assert_called()
    assert any("Couldn't load" in c.args[0] for c in win.stats_label.setText.call_args_list)


# ---------------------------------------------------------------------------
# 6. EPG → Watchlist loading placeholder
# ---------------------------------------------------------------------------

def test_epg_watchlist_show_loading_swaps_placeholder_widget(qapp):
    from PyQt6.QtWidgets import QScrollArea, QWidget
    from metatv.gui.epg_view import EpgView

    view = EpgView.__new__(EpgView)
    view.watchlist_scroll = QScrollArea()
    view.watchlist_scroll.setWidget(QWidget())  # prior/stale content

    view._show_watchlist_loading()

    inner = view.watchlist_scroll.widget()
    assert inner is not None
    # The placeholder contains a label carrying the loading icon + "watchlist".
    from PyQt6.QtWidgets import QLabel
    labels = inner.findChildren(QLabel)
    assert labels, "expected a loading label in the watchlist placeholder"
    joined = " ".join(l.text() for l in labels)
    assert _icons.loading_icon in joined
    assert "watchlist" in joined.lower()


def test_epg_reload_watchlist_shows_loading_then_submits(qapp):
    from PyQt6.QtWidgets import QScrollArea, QWidget, QLabel
    from metatv.gui.epg_view import EpgView

    view = EpgView.__new__(EpgView)
    view.watchlist_scroll = QScrollArea()
    view.watchlist_scroll.setWidget(QWidget())
    view.config = MagicMock()
    view.config.epg_watchlist_patterns = ["NHL"]
    view._filtered_provider_ids = MagicMock(return_value=["p1"])
    view._executor = MagicMock()

    view._reload_watchlist()

    # Loading placeholder installed before the worker is submitted.
    inner = view.watchlist_scroll.widget()
    joined = " ".join(l.text() for l in inner.findChildren(QLabel))
    assert _icons.loading_icon in joined
    view._executor.submit.assert_called_once()
