"""Behavioral tests for EPG On Now display — PR-3, PR-4, and Slice 3C.

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

Slice 3C coverage (EPG content-type filter + collapsible prefix groups):
- The tree is grouped by prefix: top-level rows are group headers ("{prefix} (count)"),
  programme rows are children one level down. All PR-3 assertions now navigate one level
  deeper (``tree.topLevelItem(0).child(0)``) to reach the programme row.
- The "All Types ▼" dropdown is populated from ``classify_channel_content_type()`` and
  composes with search + the Category dropdown in ``_apply_on_now_filters``.
- A group's expand/collapse state persists to ``config.epg_filter_state["on_now_group_collapsed"]``
  and is honored on the next render.
- ``on_now_header_state`` is gated by a version key — a state saved without a matching
  version is discarded (not fed to ``restoreState()``), so it can never crash or scramble
  columns.
- Hide-click / double-click / selection-changed all guard against group header rows and
  keep working on child (programme) rows.

Design: tests target the METHODS directly, not the full widget. ``_render_on_now``
receives a real ``QTreeWidget`` (and real ``FilterDropdown``s) injected onto a lightweight
namespace; ``_build_on_now_tab`` is called on a similarly lightweight namespace so the
header assertions are against real Qt state, not shape. This avoids the ~20 config attrs
that ``_setup_ui`` reads from tabs we don't care about.
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
    on_now_header_state_version: int | None = None,
    on_now_group_collapsed: dict | None = None,
    on_now_type_filter: list | None = None,
) -> SimpleNamespace:
    """Config stub covering only what _render_on_now + _build_on_now_tab need."""
    state: dict = dict(epg_filter_state or {})
    if on_now_header_state is not None:
        state["on_now_header_state"] = on_now_header_state
    if on_now_header_state_version is not None:
        state["on_now_header_state_version"] = on_now_header_state_version
    if on_now_group_collapsed is not None:
        state["on_now_group_collapsed"] = on_now_group_collapsed
    if on_now_type_filter is not None:
        state["on_now_type_filter"] = on_now_type_filter
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
    """Minimal namespace for calling EpgView._render_on_now (and friends) directly.

    Injects a real QTreeWidget and real FilterDropdowns so actual item/widget state
    can be asserted — no full _setup_ui, only the attributes the On-Now methods read.
    """
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QLineEdit, QTreeWidget, QLabel
    from metatv.gui.epg_view import EpgView, _ProgressBarDelegate
    from metatv.gui.filter_bar import FilterDropdown

    cfg = config or _minimal_config()
    host = SimpleNamespace()
    host.config = cfg

    # Real QTreeWidget with the same 6-column setup _build_on_now_tab creates
    tree = QTreeWidget()
    tree.setColumnCount(6)
    tree.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
    delegate = _ProgressBarDelegate(tree)
    tree.setItemDelegateForColumn(4, delegate)
    # Establish a sort indicator up front, mirroring _build_on_now_tab's one-time
    # sortByColumn() call — without it, toggling setSortingEnabled() inside
    # _render_on_now has no established column/order to re-sort by.
    tree.setSortingEnabled(True)
    tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)

    host.on_now_list = tree
    host.on_now_search = QLineEdit()
    host.on_now_stats = QLabel("")
    host.status_message = MagicMock()
    host.on_now_prefix_dropdown = FilterDropdown("Category", {}, all_selected=True)
    host.on_now_type_dropdown = FilterDropdown("All Types", {}, all_selected=True)

    # Maps — caller seeds these as needed
    host._channel_name_map = {}
    host._channel_quality_map = {}
    host._channel_prefix_map = {}
    host._channel_title_map = {}
    host._channel_region_map = {}   # read by the render loop's global-exclusion fallback
    host._on_now_excluded_ct_ids = set()  # content-provenance drop set (resolved in _fetch_on_now)

    # Bind the real methods under test
    host._render_on_now = lambda progs: EpgView._render_on_now(host, progs)
    # _on_now_hidden_prefixes is a @staticmethod — expose it on the namespace
    host._on_now_hidden_prefixes = EpgView._on_now_hidden_prefixes
    host._apply_on_now_filters = lambda: EpgView._apply_on_now_filters(host)
    host._sync_on_now_type_dropdown = lambda tc: EpgView._sync_on_now_type_dropdown(host, tc)
    host._on_now_type_filter_changed = lambda: EpgView._on_now_type_filter_changed(host)
    host._on_now_group_toggled = lambda item: EpgView._on_now_group_toggled(host, item)
    host._on_now_item_clicked = lambda item, col: EpgView._on_now_item_clicked(host, item, col)
    host._on_now_double_click = lambda item, col: EpgView._on_now_double_click(host, item, col)
    host._on_now_selection_changed = lambda cur, prev: EpgView._on_now_selection_changed(host, cur, prev)
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
    host._on_now_type_filter_changed = lambda: None
    host._on_now_group_toggled = lambda item: None

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
# (Slice 3C: assertions now navigate group → child, since the tree is grouped)
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
    assert tree.topLevelItemCount() == 1, "Expected exactly one prefix group"
    group = tree.topLevelItem(0)
    assert group.text(0) == "US (1)"
    assert group.childCount() == 1
    item = group.child(0)
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

    group = host.on_now_list.topLevelItem(0)
    assert group.text(0) == "(No Category) (1)"
    item = group.child(0)
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

    group = host.on_now_list.topLevelItem(0)
    assert group.text(0) == "ESPN (1)"
    item = group.child(0)
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

    item = host.on_now_list.topLevelItem(0).child(0)
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

    item = host.on_now_list.topLevelItem(0).child(0)
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
    """_save_on_now_header_state must write a base64 string + version to epg_filter_state."""
    from metatv.gui.epg_on_now_mixin import _ON_NOW_HEADER_STATE_VERSION

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
    # Slice 3C: a version key must be written alongside the state
    assert config.epg_filter_state["on_now_header_state_version"] == _ON_NOW_HEADER_STATE_VERSION
    config.save.assert_called()


def test_restore_state_path_survives_rebuild(qapp):
    """When a valid state + matching version is present, restoreState runs without error."""
    from metatv.gui.epg_on_now_mixin import _ON_NOW_HEADER_STATE_VERSION

    # Capture real state from a clean build
    config1 = _minimal_config()
    host1 = _make_on_now_tab_host(qapp, config=config1)
    host1._save_on_now_header_state()
    saved = config1.epg_filter_state["on_now_header_state"]

    # Rebuild with saved state + matching version — the real restore path
    config2 = _minimal_config(
        on_now_header_state=saved,
        on_now_header_state_version=_ON_NOW_HEADER_STATE_VERSION,
    )
    host2 = _make_on_now_tab_host(qapp, config=config2)

    # Must not raise and stretchLastSection must remain False
    assert not host2.on_now_list.header().stretchLastSection(), \
        "stretchLastSection must remain False after restoreState"


def test_corrupt_header_state_with_matching_version_falls_back_gracefully(qapp):
    """A corrupt saved state (even under the current version) must not crash startup."""
    from metatv.gui.epg_on_now_mixin import _ON_NOW_HEADER_STATE_VERSION

    config = _minimal_config(
        on_now_header_state="!!! not valid base64 !!!",
        on_now_header_state_version=_ON_NOW_HEADER_STATE_VERSION,
    )
    host = _make_on_now_tab_host(qapp, config=config)
    # Widget must still be usable with 6 columns
    assert host.on_now_list.columnCount() == 6
    assert not host.on_now_list.header().stretchLastSection()


def test_stale_header_state_missing_version_falls_back_safely(qapp):
    """A pre-Slice-3C state with no version key is discarded, not fed to restoreState()."""
    # Simulates a config saved by a version of the app that predates the version key.
    config = _minimal_config(on_now_header_state="c29tZSBvbGQgc3RhdGU=")
    host = _make_on_now_tab_host(qapp, config=config)
    assert host.on_now_list.columnCount() == 6
    assert not host.on_now_list.header().stretchLastSection()
    # Falls back to the default column order rather than attempting to restore.
    hdr = host.on_now_list.header()
    assert hdr.visualIndex(3) == 2, "Show should be at its default visual position"


def test_stale_header_state_wrong_version_falls_back_safely(qapp):
    """A state saved under a future/different version is discarded."""
    config = _minimal_config(on_now_header_state="c29tZSBvbGQgc3RhdGU=", on_now_header_state_version=999)
    host = _make_on_now_tab_host(qapp, config=config)
    assert host.on_now_list.columnCount() == 6
    assert not host.on_now_list.header().stretchLastSection()


# ---------------------------------------------------------------------------
# Slice 3C — collapsible prefix groups
# ---------------------------------------------------------------------------

def test_render_on_now_groups_by_prefix_with_counts(qapp):
    """Top-level rows are prefix-group headers labeled '{prefix} (count)', sorted by name."""
    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._channel_prefix_map["ch2"] = "US"
    host._channel_title_map["ch2"] = "Fox News"
    host._channel_name_map["ch2"] = "US ★ Fox News"
    host._channel_prefix_map["ch3"] = "UK"
    host._channel_title_map["ch3"] = "BBC One"
    host._channel_name_map["ch3"] = "UK ★ BBC One"

    progs = [
        _FakeProgram(channel_db_id="ch1", channel_epg_id="e1"),
        _FakeProgram(channel_db_id="ch2", channel_epg_id="e2"),
        _FakeProgram(channel_db_id="ch3", channel_epg_id="e3"),
    ]
    host._render_on_now(progs)

    tree = host.on_now_list
    assert tree.topLevelItemCount() == 2  # "UK" and "US" groups
    uk_group, us_group = tree.topLevelItem(0), tree.topLevelItem(1)
    assert uk_group.text(0) == "UK (1)"
    assert uk_group.childCount() == 1
    assert us_group.text(0) == "US (2)"
    assert us_group.childCount() == 2


def test_group_header_row_not_selectable(qapp):
    """Group rows must not be user-selectable (they're a header, not a channel)."""
    from PyQt6.QtCore import Qt

    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    group = host.on_now_list.topLevelItem(0)
    assert not (group.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_group_collapse_state_persists_and_restores(qapp):
    """Collapsing a group persists to config and is honored on the next render."""
    config = _minimal_config()
    host = _make_render_host(config=config)
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    group = host.on_now_list.topLevelItem(0)
    assert group.isExpanded(), "Groups must default to expanded"

    # Simulate the real user-toggle path: setExpanded(False) then the itemCollapsed
    # signal handler (called directly here — blockSignals() suppresses it during render).
    group.setExpanded(False)
    host._on_now_group_toggled(group)

    assert config.epg_filter_state["on_now_group_collapsed"] == {"US": True}

    # A later reload (periodic refresh) must respect the persisted collapse.
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])
    group2 = host.on_now_list.topLevelItem(0)
    assert not group2.isExpanded(), "Persisted collapse must be honored on next render"


def test_group_toggle_ignores_child_items(qapp):
    """_on_now_group_toggled must no-op for a non-top-level (child) item."""
    config = _minimal_config()
    host = _make_render_host(config=config)
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    child = host.on_now_list.topLevelItem(0).child(0)
    host._on_now_group_toggled(child)

    assert "on_now_group_collapsed" not in config.epg_filter_state


def test_known_categories_reads_raw_group_key_not_label(qapp):
    """_known_categories must read the raw prefix (UserRole+1), not the '(count)' label."""
    from metatv.gui.epg_view import EpgView

    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    known = EpgView._known_categories(host)
    assert "US" in known
    assert not any("(" in c for c in known), f"A group label leaked into categories: {known}"


# ---------------------------------------------------------------------------
# Slice 3C — EPG content-type "All Types ▼" filter
# ---------------------------------------------------------------------------

def test_render_on_now_classifies_and_counts_content_types(qapp):
    """Each row is classified once and the All-Types dropdown counts reflect it."""
    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN International"
    host._channel_name_map["ch1"] = "US ★ CNN International"  # News (keyword: cnn)
    host._channel_prefix_map["ch2"] = "US"
    host._channel_title_map["ch2"] = "Disney Junior"
    host._channel_name_map["ch2"] = "US ★ Disney Junior"      # Kids (keyword: disney)
    host._channel_prefix_map["ch3"] = "US"
    host._channel_title_map["ch3"] = "Local Access 12"
    host._channel_name_map["ch3"] = "US ★ Local Access 12"    # Other (no match)

    progs = [
        _FakeProgram(channel_db_id="ch1", channel_epg_id="e1"),
        _FakeProgram(channel_db_id="ch2", channel_epg_id="e2"),
        _FakeProgram(channel_db_id="ch3", channel_epg_id="e3"),
    ]
    host._render_on_now(progs)

    assert host.on_now_type_dropdown.groups == {"News": 1, "Kids": 1, "Other": 1}


def test_type_filter_hides_and_shows_rows_and_composes_with_search(qapp):
    """Deselecting a type hides only that type's rows; search still narrows within it."""
    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN International"
    host._channel_name_map["ch1"] = "US ★ CNN International"
    host._channel_prefix_map["ch2"] = "US"
    host._channel_title_map["ch2"] = "Disney Junior"
    host._channel_name_map["ch2"] = "US ★ Disney Junior"

    progs = [
        _FakeProgram(channel_db_id="ch1", channel_epg_id="e1", title="Breaking News"),
        _FakeProgram(channel_db_id="ch2", channel_epg_id="e2", title="Cartoon Hour"),
    ]
    host._render_on_now(progs)

    group = host.on_now_list.topLevelItem(0)  # "US (2)"
    assert group.childCount() == 2

    # Narrow the All-Types selection to "News" only.
    host.on_now_type_dropdown.selected_groups = {"News"}
    host._apply_on_now_filters()

    visible = [group.child(i) for i in range(group.childCount()) if not group.child(i).isHidden()]
    assert len(visible) == 1
    assert visible[0].text(1) == "CNN International"
    assert group.isHidden() is False, "Group with at least one visible child stays visible"

    # Compose with search: narrowing further to a term that matches nothing under News.
    host.on_now_search.setText("cartoon")
    host._apply_on_now_filters()
    visible = [group.child(i) for i in range(group.childCount()) if not group.child(i).isHidden()]
    assert visible == []
    assert group.isHidden() is True, "Group must hide once no children remain visible"


def test_type_filter_selection_persists_to_config(qapp):
    """Changing the All-Types dropdown to a genuine subset persists it to epg_filter_state."""
    config = _minimal_config()
    host = _make_render_host(config=config)
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"           # News
    host._channel_prefix_map["ch2"] = "US"
    host._channel_title_map["ch2"] = "Disney Junior"
    host._channel_name_map["ch2"] = "US ★ Disney Junior"  # Kids
    host._render_on_now([
        _FakeProgram(channel_db_id="ch1", channel_epg_id="e1"),
        _FakeProgram(channel_db_id="ch2", channel_epg_id="e2"),
    ])

    # Two types present (News, Kids) — selecting only one is a genuine subset,
    # distinct from the "[] == all selected" sentinel.
    host.on_now_type_dropdown.selected_groups = {"News"}
    host._on_now_type_filter_changed()

    assert config.epg_filter_state["on_now_type_filter"] == ["News"]


def test_type_filter_selection_restored_on_first_load(qapp):
    """A persisted on_now_type_filter selection is restored the first time types populate."""
    config = _minimal_config(on_now_type_filter=["News"])
    host = _make_render_host(config=config)
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN International"
    host._channel_name_map["ch1"] = "US ★ CNN International"
    host._channel_prefix_map["ch2"] = "US"
    host._channel_title_map["ch2"] = "Disney Junior"
    host._channel_name_map["ch2"] = "US ★ Disney Junior"

    host._render_on_now([
        _FakeProgram(channel_db_id="ch1", channel_epg_id="e1"),
        _FakeProgram(channel_db_id="ch2", channel_epg_id="e2"),
    ])

    assert host.on_now_type_dropdown.get_selected() == ["News"]


# ---------------------------------------------------------------------------
# Slice 3C — interactions must keep working on child rows, no-op on group rows
# ---------------------------------------------------------------------------

def test_hide_click_and_double_click_noop_on_group_row(qapp):
    """Hide-column click and double-click must be no-ops on a group header row."""
    host = _make_render_host()
    host._show_hide_dialog = MagicMock()
    host._play_channel = MagicMock()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    group = host.on_now_list.topLevelItem(0)
    host._on_now_item_clicked(group, 5)
    host._show_hide_dialog.assert_not_called()

    host._on_now_double_click(group, 1)
    host._play_channel.assert_not_called()


def test_hide_click_and_double_click_still_work_on_child_row(qapp):
    """Hide-column click and double-click must still work on a programme (child) row."""
    host = _make_render_host()
    host._show_hide_dialog = MagicMock()
    host._play_channel = MagicMock()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1", title="News Hour")])

    child = host.on_now_list.topLevelItem(0).child(0)
    child.setSelected(True)

    host._on_now_item_clicked(child, 5)
    host._show_hide_dialog.assert_called_once()

    host._on_now_double_click(child, 1)
    host._play_channel.assert_called_once_with("ch1")


def test_selection_changed_noop_on_group_row(qapp):
    """currentItemChanged must not emit channel-selected for a group header row."""
    host = _make_render_host()
    host._emit_channel_selected = MagicMock()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    group = host.on_now_list.topLevelItem(0)
    host._on_now_selection_changed(group, None)
    host._emit_channel_selected.assert_not_called()


def test_selection_changed_still_works_on_child_row(qapp):
    """currentItemChanged must still emit channel-selected for a programme (child) row."""
    host = _make_render_host()
    host._emit_channel_selected = MagicMock()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    child = host.on_now_list.topLevelItem(0).child(0)
    host._on_now_selection_changed(child, None)
    host._emit_channel_selected.assert_called_once_with("ch1")


def test_context_menu_selected_items_excludes_group_rows(qapp):
    """selectedItems() filtering in _on_now_context_menu must drop any group row."""
    host = _make_render_host()
    host._channel_prefix_map["ch1"] = "US"
    host._channel_title_map["ch1"] = "CNN"
    host._channel_name_map["ch1"] = "US ★ CNN"
    host._render_on_now([_FakeProgram(channel_db_id="ch1", channel_epg_id="e1")])

    group = host.on_now_list.topLevelItem(0)
    child = group.child(0)
    # Group rows aren't ItemIsSelectable, but select the child explicitly and assert
    # the filtering the context-menu handler applies keeps it.
    child.setSelected(True)
    items = [i for i in host.on_now_list.selectedItems() if i.parent() is not None]
    assert items == [child]
