"""Behavioral tests for the zero-sources channel-list empty state (#263).

Bug: a fresh install with zero configured sources showed the SAME message as a
normal filtered-to-zero result — "No channels match — try a different search
or check filter settings" — which blames search/filters for a cause that is
actually "there is no source yet". This drives the REAL production code
(``MainWindow._build_no_sources_banner`` / ``_show_no_sources_state`` /
``load_channels`` / ``_on_channels_loaded``) against a real file-backed
``Database`` (never ``:memory:`` — see CLAUDE.md Tests rule) and asserts
rendered widget STATE (``isVisible()``/``isEnabled()``) plus the real
click→handler wiring, not just that a string constant exists somewhere.

Two scenarios, matching the PR's acceptance criteria:

1. Zero sources configured at all → the honest "no sources" banner shows, its
   "Add Source" button is visible + enabled, and clicking it invokes the SAME
   ``add_provider`` handler the sidebar '+' / Sources-manager '+' buttons use
   (asserted via the real connection, not a re-implementation).
2. >=1 source configured but zero matching channels → the ORIGINAL filter/
   search message and stats text are unchanged, and the no-sources banner
   stays hidden — this is the guard that stops the new state leaking into
   ordinary "no results" use.
"""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QListView, QVBoxLayout, QWidget

from metatv.core.database import Database, ProviderDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def file_db(tmp_path):
    """File-backed Database (not :memory:) so the test proves real DB state."""
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_provider(db: Database, name: str = "TestProv") -> str:
    """Insert a real ProviderDB row and return its id."""
    pid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ProviderDB(
            id=pid,
            name=name,
            type="xtream",
            url="http://example.com:8080",
            username="u1",
            password="pass",
            is_active=True,
            urls=[{"url": "http://example.com:8080", "priority": 0,
                   "is_active": True, "success_count": 0, "failure_count": 0}],
        ))
    return pid


def _make_channel_load_host(qapp, db: Database):
    """A bare MainWindow host wired for a REAL load_channels()/_on_channels_loaded()
    pass: _run_query runs query_fn synchronously against the real file DB (mirrors
    the established _inline_run_query pattern in test_explore_entry_points.py)
    instead of a background executor, so the whole pipeline — including the real
    _query_channels worker and the real _build_no_sources_banner()-constructed
    widgets — executes deterministically in-process.
    """
    from metatv.gui import main_window as mw_module
    from metatv.gui.channel_list_model import ChannelListModel

    win = mw_module.MainWindow.__new__(mw_module.MainWindow)
    win.db = db

    # Real virtualized model/view (load_channels populates these directly).
    win.channel_model = ChannelListModel()
    win.channels_list = QListView()
    win.channels_list.setModel(win.channel_model)

    # Real banner widgets — mirrors what setup_ui() builds, minus the rest of
    # the window chrome. _build_no_sources_banner() is the REAL production
    # method (main_window_providers.py), not a re-implementation. The container
    # is stashed on win so it (and its children) stay alive for the test's
    # lifetime — an unreferenced top-level QWidget is eligible for GC as soon
    # as this function returns, which would invalidate the banner underneath it.
    container = QWidget()
    win._test_list_container = container
    win._list_layout = QVBoxLayout(container)
    from PyQt6.QtWidgets import QLabel, QPushButton
    win._channel_banner = QLabel()
    win._channel_filter_bar = QWidget()
    win._channel_filter_btn = QPushButton()
    win.add_provider = MagicMock()  # the handler under test — real button must call THIS
    win._build_no_sources_banner()
    container.show()

    # Rendered-state surfaces (real widgets, not MagicMock, so .text()/
    # .currentMessage() reflect what the user would actually see).
    win.stats_label = QLabel()
    from PyQt6.QtWidgets import QStatusBar
    win.status_bar = QStatusBar()

    # Minimal main-thread UI state load_channels() reads before dispatch.
    win.all_channels = ["stale"]
    win.config = MagicMock()
    win.config.global_filter_paused = True          # short-circuits exclusion resolution
    win.config.collapse_variants_in_list = False
    # Must be a NON-EMPTY (truthy) dict: `current_filter_state or (... hasattr(self,
    # 'filter_panel') ...)` short-circuits on a truthy dict — an empty {} instead
    # falls through to hasattr() on this bare __new__'d host, which PyQt turns into
    # RuntimeError (no filter_panel attr AND __init__ never ran; see the #351/#375
    # trap documented on _sources_status_target in main_window_providers.py).
    win.current_filter_state = {
        "_language_prefixes": [], "_region_prefixes": [],
        "_platform_prefixes": [], "_quality_prefixes": [],
    }
    win.search_input = MagicMock()
    win.search_input.text.return_value = ""
    win._search_debounce = MagicMock()
    win._bypass_tier1_filters = False
    win._bypass_global_exclusions = False
    win._details_genre_filter = None
    win._details_person_filter = None
    win._details_tag_filter = None
    win._details_category_filter = None
    win._details_id_filter = None
    win._id_filter_show_all = False
    win._search_page_size = 1000
    win._hidden_mode = False
    win._load_channels_token = [0]

    # _on_channels_loaded() stubs unrelated to the empty-state branch under test.
    win._enqueue_tmdb_enrichment = MagicMock()
    win._clear_provider_busy = MagicMock()

    def _inline_run_query(query_fn, on_result, *, token_ref=None, on_error=None):
        """Mirror MainWindow._run_query inline against the REAL file db."""
        if token_ref is not None:
            token_ref[0] += 1
        with db.session_scope(commit=False) as session:
            data = query_fn(RepositoryFactory(session))
        on_result(data)

    win._run_query = _inline_run_query
    return win


# ---------------------------------------------------------------------------
# 1. Zero sources configured — honest message + wired, enabled, visible button
# ---------------------------------------------------------------------------

def test_zero_sources_shows_honest_banner_with_enabled_visible_add_button(qapp, file_db):
    host = _make_channel_load_host(qapp, file_db)  # file_db has ZERO providers

    host.load_channels()

    # Rendered STATE, not just that the widget/string exists.
    assert host._no_sources_banner.isVisible()
    assert host._no_sources_add_btn.isVisible()
    assert host._no_sources_add_btn.isEnabled()
    assert "no source" in host._no_sources_lbl.text().lower()
    # Honest cause, never blames search/filters.
    assert "search" not in host.status_bar.currentMessage().lower()
    assert "filter" not in host.status_bar.currentMessage().lower()
    assert "source" in host.status_bar.currentMessage().lower()
    assert "source" in host.stats_label.text().lower()

    # The button must invoke the SAME handler the sidebar '+' / manager '+'
    # buttons use — assert the real connection fires, not a parallel path.
    host.add_provider.assert_not_called()
    host._no_sources_add_btn.click()
    host.add_provider.assert_called_once()


def test_zero_sources_banner_hidden_before_load(qapp, file_db):
    """Sanity: the banner starts hidden (only load_channels()'s zero-provider
    branch reveals it) — guards against it being shown unconditionally."""
    host = _make_channel_load_host(qapp, file_db)
    assert not host._no_sources_banner.isVisible()


# ---------------------------------------------------------------------------
# 2. >=1 source configured, zero matching channels — ORIGINAL message unchanged
# ---------------------------------------------------------------------------

def test_sources_exist_zero_channels_keeps_original_message_and_no_banner(qapp, file_db):
    _seed_provider(file_db)  # a real source exists; it just has no channels yet

    host = _make_channel_load_host(qapp, file_db)
    host.load_channels()

    # The pre-existing filter/search zero-results message is UNCHANGED.
    assert host.status_bar.currentMessage() == (
        "No channels match — try a different search or check filter settings"
    )
    assert host.stats_label.text() == "Showing 0 of 0"

    # This is the guard that stops the new state leaking into ordinary
    # "no results" use: the Add-Source banner/button must stay hidden.
    assert not host._no_sources_banner.isVisible()
