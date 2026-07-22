"""Behavioral tests for EPG On Now display — PR-3 and PR-4.

PR-3 coverage:
- ``_render_on_now`` reads category/bare-name from stored prefix/title maps instead of
  calling ``parse_channel_name`` at render time.
- The category tooltip uses ``resolve_category_name``, not the deleted ``_CATEGORY_FULL_NAMES``.
- ``_CATEGORY_FULL_NAMES`` no longer exists on the class.

PR-4 coverage:
- On Now header has ``sectionsMovable() == True`` and ``stretchLastSection() == False``.
- Show column (logical 3) is the only Stretch section.
- ``_save_on_now_header_state`` writes to ``config.epg_filter_state["on_now_header_state"]``
  and calls ``config.save()``.
- Constructing with a saved ``on_now_header_state`` runs the restore path without error
  and leaves ``stretchLastSection() == False``.

Design: tests target the METHODS directly, not the full widget.  ``_render_on_now``
receives a real ``QTreeWidget`` injected onto a lightweight namespace; ``_build_on_now_tab``
is called on a similarly lightweight namespace so the header assertions are against
real Qt state, not shape.  This avoids the ~20 config attrs that ``_setup_ui`` reads from
tabs we don't care about.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_config(
    *,
    epg_category_overrides: dict | None = None,
    epg_watchlist_patterns: list | None = None,
    epg_filter_state: dict | None = None,
    epg_hidden_prefixes: list | None = None,
    global_filter_excluded_categories: list | None = None,
    global_filter_excluded_prefixes: list | None = None,
    global_filter_paused: bool = False,
    category_name_overrides: dict | None = None,
    on_now_header_state: str | None = None,
) -> SimpleNamespace:
    """Config stub covering only what _render_on_now + _build_on_now_tab need."""
    state: dict = dict(epg_filter_state or {})
    if on_now_header_state is not None:
        state["on_now_header_state"] = on_now_header_state
    return SimpleNamespace(
        epg_category_overrides=epg_category_overrides or {},
        epg_watchlist_patterns=epg_watchlist_patterns or [],
        epg_filter_state=state,
        epg_hidden_prefixes=epg_hidden_prefixes or [],
        global_filter_excluded_categories=global_filter_excluded_categories or [],
        global_filter_excluded_prefixes=global_filter_excluded_prefixes or [],
        global_filter_paused=global_filter_paused,
        category_name_overrides=category_name_overrides or {},
        # icons used only by _build_on_now_tab
        close_icon="×",
        hide_icon="🚫",
        save=MagicMock(),
    )


def _make_render_host(config=None) -> SimpleNamespace:
    """Minimal namespace for calling EpgView._render_on_now directly.

    Injects a real QTreeWidget so actual item data can be asserted.
    No full _setup_ui — only the attributes _render_on_now reads.
    """
    from PyQt6.QtWidgets import QTreeWidget, QLabel
    from metatv.gui.epg_view import EpgView, _ProgressBarDelegate

    cfg = config or _minimal_config()
    host = SimpleNamespace()
    host.config = cfg

    # Real QTreeWidget with the same 6-column setup _build_on_now_tab creates
    tree = QTreeWidget()
    tree.setColumnCount(6)
    tree.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
    delegate = _ProgressBarDelegate(tree)
    tree.setItemDelegateForColumn(4, delegate)

    host.on_now_list = tree
    host.on_now_stats = QLabel("")
    host.status_message = MagicMock()
    host.on_now_prefix_dropdown = MagicMock()

    # Maps — caller seeds these as needed
    host._channel_name_map = {}
    host._channel_quality_map = {}
    host._channel_prefix_map = {}
    host._channel_title_map = {}
    host._channel_region_map = {}   # read by the render loop's global-exclusion fallback
    host._on_now_excluded_ct_ids = set()  # content-provenance drop set (resolved in _fetch_on_now)

    # Bind the real method
    host._render_on_now = lambda progs: EpgView._render_on_now(host, progs)
    # _on_now_hidden_prefixes is a @staticmethod — expose it on the namespace
    host._on_now_hidden_prefixes = EpgView._on_now_hidden_prefixes
    host._apply_on_now_filters = lambda: None
    host._update_filler_btn_label = lambda: None

    return host


def _make_on_now_tab_host(qapp, config=None) -> SimpleNamespace:
    """Namespace that can run _build_on_now_tab (needs a QWidget parent for layout)."""
    from PyQt6.QtWidgets import QWidget, QStackedWidget
    from metatv.gui.epg_view import EpgView

    cfg = config or _minimal_config()
    # Simulate just enough of EpgView so _build_on_now_tab succeeds
    host = QWidget.__new__(QWidget)
    QWidget.__init__(host, None)

    host.config = cfg
    host.stack = QStackedWidget(host)

    # Bind real methods
    host._build_on_now_tab = lambda: EpgView._build_on_now_tab(host)
    host._save_on_now_header_state = lambda: EpgView._save_on_now_header_state(host)
    host._save_epg_sort = lambda tab, col, order: None
    # Stubs for signals connected in _build_on_now_tab
    host._apply_on_now_filters = lambda: None
    host._on_filler_toggled = lambda: None
    host._on_now_context_menu = lambda pos: None
    host._on_now_double_click = lambda item, col: None
    host._on_now_item_clicked = lambda item, col: None
    host._on_now_selection_changed = lambda cur, prev: None

    host._build_on_now_tab()
    return host


# ---------------------------------------------------------------------------
# Fake EPG program
# ---------------------------------------------------------------------------

class _FakeProgram:
    """Minimal stub satisfying _render_on_now's attribute reads."""
    def __init__(
        self,
        channel_db_id: str = "ch1",
        channel_epg_id: str = "epg1",
        title: str = "Test Show",
        start_time=None,
        stop_time=None,
        is_live: bool = False,
        is_new: bool = False,
    ):
        from datetime import datetime, timedelta
        _now = datetime(2026, 6, 19, 20, 0, 0)
        self.channel_db_id = channel_db_id
        self.channel_epg_id = channel_epg_id
        self.title = title
        self.start_time = start_time or (_now - timedelta(minutes=30))
        self.stop_time = stop_time or (_now + timedelta(minutes=30))
        self.is_live = is_live
        self.is_new = is_new


# ---------------------------------------------------------------------------
# PR-3 — _render_on_now reads stored prefix/title maps, no parse_channel_name
# ---------------------------------------------------------------------------

def test_render_on_now_uses_stored_prefix_map(qapp):
    """Category cell must come from _channel_prefix_map, not parse_channel_name."""
    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN International"
    host._channel_name_map["ch1"] = "US ★ CNN International"

    prog = _FakeProgram(channel_db_id="ch1", title="Breaking News")

    # parse_channel_name must NOT be invoked during render
    with patch(
        "metatv.gui.epg_view.parse_channel_name",
        side_effect=AssertionError("parse_channel_name called at render time"),
    ):
        host._render_on_now([prog])

    tree = host.on_now_list
    assert tree.topLevelItemCount() == 1
    item = tree.topLevelItem(0)
    assert item.text(0) == "US", f"Expected category 'US', got '{item.text(0)}'"
    assert item.text(1) == "CNN International", (
        f"Expected bare name 'CNN International', got '{item.text(1)}'"
    )


def test_render_on_now_bare_name_fallback_to_ch_name(qapp):
    """When prefix/title maps have no entry, bare_name falls back to the channel name."""
    host = _make_render_host()
    host._channel_name_map["ch2"] = "Mystery Channel"
    # No prefix/title map entries for ch2

    prog = _FakeProgram(channel_db_id="ch2", title="Episode 1")

    with patch(
        "metatv.gui.epg_view.parse_channel_name",
        side_effect=AssertionError("called"),
    ):
        host._render_on_now([prog])

    item = host.on_now_list.topLevelItem(0)
    assert item.text(0) == "", f"Expected empty category, got '{item.text(0)}'"
    assert item.text(1) == "Mystery Channel", f"Got '{item.text(1)}'"


def test_render_on_now_category_override_wins_over_prefix_map(qapp):
    """An epg_category_overrides entry overrides the stored prefix map."""
    config = _minimal_config(epg_category_overrides={"ch3": "ESPN"})
    host = _make_render_host(config=config)
    host._channel_prefix_map["ch3"] = "US"
    host._channel_title_map["ch3"] = "ESPN SportsCenter"
    host._channel_name_map["ch3"] = "US ★ ESPN SportsCenter"

    prog = _FakeProgram(channel_db_id="ch3", title="SportsCenter")

    with patch(
        "metatv.gui.epg_view.parse_channel_name",
        side_effect=AssertionError("called"),
    ):
        host._render_on_now([prog])

    item = host.on_now_list.topLevelItem(0)
    assert item.text(0) == "ESPN", f"Expected 'ESPN', got '{item.text(0)}'"
    # bare_name is ch_name when override is active
    assert item.text(1) == "US ★ ESPN SportsCenter"


def test_render_on_now_category_tooltip_uses_resolve_category_name(qapp):
    """Column-0 tooltip must be resolved via resolve_category_name."""
    host = _make_render_host()
    host._channel_prefix_map["ch4"] = "US"
    host._channel_title_map["ch4"] = "NBC News"
    host._channel_name_map["ch4"] = "US ★ NBC News"

    prog = _FakeProgram(channel_db_id="ch4", title="Nightly News")

    host._render_on_now([prog])

    item = host.on_now_list.topLevelItem(0)
    # resolve_category_name("US", config) → "United States" (from REGION_FULL_NAMES)
    assert item.toolTip(0) == "United States", f"Expected 'United States', got '{item.toolTip(0)}'"


def test_render_on_now_unknown_code_tooltip_falls_back_to_raw_code(qapp):
    """For a prefix not in REGION_FULL_NAMES, tooltip shows the raw code."""
    host = _make_render_host()
    host._channel_prefix_map["ch5"] = "XYZ"
    host._channel_title_map["ch5"] = "Some Channel"
    host._channel_name_map["ch5"] = "XYZ ★ Some Channel"

    prog = _FakeProgram(channel_db_id="ch5", title="Some Show")

    host._render_on_now([prog])

    item = host.on_now_list.topLevelItem(0)
    # resolve_category_name("XYZ", ...) returns "" → fallback is raw "XYZ"
    assert item.toolTip(0) == "XYZ", f"Expected 'XYZ', got '{item.toolTip(0)}'"


def test_category_full_names_class_attr_deleted():
    """_CATEGORY_FULL_NAMES must no longer exist on EpgView (single source of truth rule)."""
    from metatv.gui.epg_view import EpgView
    assert not hasattr(EpgView, "_CATEGORY_FULL_NAMES"), (
        "_CATEGORY_FULL_NAMES was not deleted — all category lookups must go through "
        "resolve_category_name / REGION_FULL_NAMES in channel_name_utils.py"
    )


# ---------------------------------------------------------------------------
# PR-4 — On Now header: movable, no stretch-last, Show=Stretch, persist state
# ---------------------------------------------------------------------------

def test_on_now_header_sections_movable(qapp):
    """On Now header must report sectionsMovable() == True."""
    host = _make_on_now_tab_host(qapp)
    assert host.on_now_list.header().sectionsMovable()


def test_on_now_header_stretch_last_section_false(qapp):
    """stretchLastSection must be False so Quality column doesn't hog width."""
    host = _make_on_now_tab_host(qapp)
    assert not host.on_now_list.header().stretchLastSection()


def test_on_now_show_column_is_only_stretch(qapp):
    """Show column (logical 3) must be Stretch; all others must not be."""
    from PyQt6.QtWidgets import QHeaderView
    host = _make_on_now_tab_host(qapp)
    hdr = host.on_now_list.header()
    assert hdr.sectionResizeMode(3) == QHeaderView.ResizeMode.Stretch, \
        "Logical column 3 (Show) must be Stretch"
    for col in [0, 1, 2, 4, 5]:
        assert hdr.sectionResizeMode(col) != QHeaderView.ResizeMode.Stretch, \
            f"Column {col} must not be Stretch"


def test_save_on_now_header_state_writes_to_config(qapp):
    """_save_on_now_header_state must write a base64 string to epg_filter_state."""
    config = _minimal_config()
    host = _make_on_now_tab_host(qapp, config=config)

    host._save_on_now_header_state()

    assert "on_now_header_state" in config.epg_filter_state, \
        "on_now_header_state key must be written to epg_filter_state"
    stored = config.epg_filter_state["on_now_header_state"]
    assert isinstance(stored, str) and len(stored) > 0
    # Must be valid base64
    decoded = base64.b64decode(stored.encode("ascii"))
    assert len(decoded) > 0
    config.save.assert_called()


def test_restore_state_path_survives_rebuild(qapp):
    """When a valid on_now_header_state is present, restoreState runs without error."""
    # Capture real state from a clean build
    config1 = _minimal_config()
    host1 = _make_on_now_tab_host(qapp, config=config1)
    host1._save_on_now_header_state()
    saved = config1.epg_filter_state["on_now_header_state"]

    # Rebuild with saved state
    config2 = _minimal_config(on_now_header_state=saved)
    host2 = _make_on_now_tab_host(qapp, config=config2)

    # Must not raise and stretchLastSection must remain False
    assert not host2.on_now_list.header().stretchLastSection(), \
        "stretchLastSection must remain False after restoreState"


def test_corrupt_header_state_falls_back_gracefully(qapp):
    """A corrupt saved state must not crash startup — falls back to default order."""
    config = _minimal_config(on_now_header_state="!!! not valid base64 !!!")
    host = _make_on_now_tab_host(qapp, config=config)
    # Widget must still be usable with 6 columns
    assert host.on_now_list.columnCount() == 6
    assert not host.on_now_list.header().stretchLastSection()
