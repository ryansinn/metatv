"""Behavioral tests for the EPG Browse results-list makeover (wave3/browse-makeover).

Covers the owner-approved Q1-Q6 + Q8 design-review items (Q7 lands separately):

Q1/Q2 — Category + Quality columns, populated by an extended ``_fetch_browse``
        (mirrors ``_fetch_on_now``'s prefix/quality maps).
Q3    — Day-separator rows: appear only in the default Time-ascending sort, are
        recomputed/extended across a keyset "load more" append, disappear the
        instant the user picks any other column/order, and are skipped (not
        bailed out on) by the scroll→scrubber-handle sync.
Q4    — Provider glyph in the Channel cell, gated on >1 ENABLED (non-hidden)
        source, computed once per fetch (not per row).
Q5    — Exact footer copy.
Q6    — Header tooltips/movable/persisted state (new ``browse_header_state`` key,
        stale-state no-op) + the one-time old→new sort-column migration.
Q8    — The shared ``apply_watchlist_highlight`` helper bolds the right column in
        both On Now and Browse.
"""

from __future__ import annotations
from tests.conftest import with_programme_render_fields

import base64
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import Qt

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import now_utc
from metatv.gui.epg_browse_mixin import (
    _EpgBrowseMixin,
    _SEPARATOR_ROLE,
    _START_ROLE,
)
from metatv.gui.epg_widgets import _EpgTreeItem, apply_watchlist_highlight


# ---------------------------------------------------------------------------
# Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# All grouping/label assertions run under a frozen UTC "local" timezone so the
# local-midnight boundary math is deterministic regardless of the host machine's
# real timezone (CLAUDE.md: EPG time always via epg_utils, never inline tz math).
_FROZEN_TZ_PATCH = "metatv.core.epg_utils._local_tz"


@with_programme_render_fields
class _FakeProg:
    """Minimal EpgProgramDB stand-in with explicit start/stop for day-boundary tests."""

    def __init__(self, channel_db_id, title, start_time, stop_time=None,
                 channel_epg_id="epg1", is_live=False, is_new=False):
        self.channel_db_id = channel_db_id
        self.channel_epg_id = channel_epg_id
        self.title = title
        self.start_time = start_time
        self.stop_time = stop_time or (start_time + timedelta(minutes=30))
        self.is_live = is_live
        self.is_new = is_new
        self.id = id(self)


def _make_render_host(qapp, *, name_map=None, title_map=None, prefix_map=None,
                      quality_map=None, provider_map=None, show_glyph=False,
                      provider_icon_map=None):
    from PyQt6.QtWidgets import QTreeWidget, QLabel

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.config = SimpleNamespace(epg_watchlist_patterns=[], category_name_overrides={},
                                   epg_filter_state={})
    host._channel_name_map = dict(name_map or {})
    host._channel_title_map = dict(title_map or {})
    host._channel_prefix_map = dict(prefix_map or {})
    host._channel_quality_map = dict(quality_map or {})
    host._channel_provider_map = dict(provider_map or {})
    host._browse_show_provider_glyph = show_glyph
    host._browse_provider_icon_map = dict(provider_icon_map or {})
    host.browse_list = QTreeWidget()
    host.browse_list.setColumnCount(6)
    host.browse_list.setHeaderLabels(
        ["Time", "Category", "Channel", "Quality", "Show", "Duration"]
    )
    host.browse_list.setSortingEnabled(True)
    host.browse_placeholder = QLabel()
    host.browse_stats = QLabel()
    host.status_message = SimpleNamespace(emit=MagicMock())
    host._browse_exhausted = True
    return host


# ===========================================================================
# Q1/Q2 — Category + Quality columns
# ===========================================================================

def test_render_browse_shows_category_and_quality_columns(qapp):
    """Category (col 1) shows detected_prefix; Quality (col 3) shows the
    viewer-facing quality_display text, centered, with a tooltip."""
    host = _make_render_host(
        qapp,
        name_map={"c1": "US| ESPN HD"},
        title_map={"c1": "ESPN"},
        prefix_map={"c1": "US"},
        quality_map={"c1": "HD"},
    )
    prog = _FakeProg("c1", "SportsCenter", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])

    item = host.browse_list.topLevelItem(0)
    assert item.text(1) == "US", f"Category column must show detected_prefix, got {item.text(1)!r}"
    assert item.text(3) == "HD", f"Quality column must show quality_display(token), got {item.text(3)!r}"
    assert item.textAlignment(3) & Qt.AlignmentFlag.AlignCenter
    assert item.toolTip(3), "Quality cell must carry a tooltip"
    assert item.toolTip(1), "Category cell must carry a resolve_category_name tooltip"


def test_render_browse_category_quality_blank_when_unknown(qapp):
    """No prefix/quality map entry → blank cells, no crash."""
    host = _make_render_host(qapp, name_map={"c9": "Mystery"}, title_map={})
    prog = _FakeProg("c9", "Ep 1", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    item = host.browse_list.topLevelItem(0)
    assert item.text(1) == ""
    assert item.text(3) == ""


def test_fetch_browse_populates_prefix_and_quality_maps(tmp_path):
    """_fetch_browse must extend the shared maps with detected_prefix/quality,
    mirroring _fetch_on_now (Q1/Q2)."""
    db = Database(f"sqlite:///{tmp_path / 'q1q2.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Only", type="xtream", url="http://a",
                         username="u", password="p", is_active=True,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="US| ESPN HD",
                        detected_title="ESPN", detected_prefix="US", detected_quality="hd"))
        s.add(EpgProgramDB(
            provider_id="p1", channel_epg_id="c1.epg", channel_db_id="c1",
            channel_name="c1", title="SportsCenter", description="d",
            start_time=now + timedelta(hours=1), stop_time=now + timedelta(hours=2),
        ))

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.db = db
    host.config = SimpleNamespace(epg_filler_patterns=[], epg_browse_hide_older_than_hours=0)
    host._channel_name_map = {}
    host._channel_title_map = {}
    host._channel_prefix_map = {}
    host._channel_quality_map = {}
    host._channel_provider_map = {}
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))

    _EpgBrowseMixin._fetch_browse(
        host, provider_ids=["p1"], anchor=None, search="",
        hide_filler=False, after=None, append=False, gen=1,
    )
    assert host._channel_prefix_map["c1"] == "US"
    assert host._channel_quality_map["c1"] == "HD"
    assert host._channel_provider_map["c1"] == "p1"


# ===========================================================================
# Q3 — Day separators
# ===========================================================================

def _ascending(host):
    host.browse_list.sortByColumn(0, Qt.SortOrder.AscendingOrder)


def _other_sort(host):
    host.browse_list.sortByColumn(2, Qt.SortOrder.AscendingOrder)  # Channel


def test_separators_appear_in_time_ascending_sort(qapp):
    with patch(_FROZEN_TZ_PATCH, lambda: timezone.utc), \
         patch("metatv.core.epg_utils.now_utc",
               lambda: datetime(2026, 8, 1, 19, 0, 0)):
        # now_utc frozen too: the label's Tonight/Tomorrow naming compares the
        # boundary against NOW — with fixed seed dates but a live clock this
        # test broke the moment the real date passed Aug 1 (and flaked after
        # 18:00 UTC-negative local time even ON Aug 1).
        host = _make_render_host(qapp, title_map={"c1": "ESPN"})
        _ascending(host)
        day1 = datetime(2026, 8, 1, 20, 0, 0)
        day2 = datetime(2026, 8, 2, 9, 0, 0)
        progs = [
            _FakeProg("c1", "Show A", day1),
            _FakeProg("c1", "Show B", day2),
        ]
        _EpgBrowseMixin._render_browse(host, progs)

        # 2 real rows + 2 day-separator rows (one per distinct day).
        assert host.browse_list.topLevelItemCount() == 4
        seps = [
            host.browse_list.topLevelItem(i) for i in range(4)
            if host.browse_list.topLevelItem(i).data(0, _SEPARATOR_ROLE)
        ]
        assert len(seps) == 2
        assert seps[0].text(0) == "Tonight · Sat Aug 1"
        assert seps[1].text(0) == "Tomorrow · Sun Aug 2"
        # Separators are excluded from the footer's programme count.
        assert host.browse_stats.text() == "2 programmes · times shown in your local time"


def test_separators_absent_when_sorted_by_other_column(qapp):
    with patch(_FROZEN_TZ_PATCH, lambda: timezone.utc):
        host = _make_render_host(qapp, title_map={"c1": "ESPN"})
        _other_sort(host)
        day1 = datetime(2026, 8, 1, 20, 0, 0)
        day2 = datetime(2026, 8, 2, 9, 0, 0)
        progs = [_FakeProg("c1", "Show A", day1), _FakeProg("c1", "Show B", day2)]
        _EpgBrowseMixin._render_browse(host, progs)
        assert host.browse_list.topLevelItemCount() == 2, "No separators outside Time-ascending"
        assert host.browse_stats.text() == "2 programmes · times shown in your local time"


def test_separator_rows_are_non_selectable(qapp):
    with patch(_FROZEN_TZ_PATCH, lambda: timezone.utc):
        host = _make_render_host(qapp, title_map={"c1": "ESPN"})
        _ascending(host)
        _EpgBrowseMixin._render_browse(host, [_FakeProg("c1", "Show A", datetime(2026, 8, 1, 20, 0, 0))])
        sep = host.browse_list.topLevelItem(0)
        assert sep.data(0, _SEPARATOR_ROLE) is True
        assert not (sep.flags() & Qt.ItemFlag.ItemIsSelectable)


def test_separators_recompute_across_append_page(qapp):
    """A keyset 'load more' page continuing the SAME day must not duplicate the
    separator; a page that crosses into a NEW day gets one."""
    with patch(_FROZEN_TZ_PATCH, lambda: timezone.utc):
        host = _make_render_host(qapp, title_map={"c1": "ESPN"})
        _ascending(host)
        page1 = [_FakeProg("c1", "Show A", datetime(2026, 8, 1, 20, 0, 0))]
        _EpgBrowseMixin._render_browse(host, page1, append=False)
        assert host.browse_list.topLevelItemCount() == 2  # 1 separator + 1 row

        page2 = [
            _FakeProg("c1", "Show B", datetime(2026, 8, 1, 22, 0, 0)),  # same day
            _FakeProg("c1", "Show C", datetime(2026, 8, 2, 8, 0, 0)),   # next day
        ]
        _EpgBrowseMixin._render_browse(host, page2, append=True)
        # 2 separators total (day1 once, day2 once) + 3 real rows = 5.
        assert host.browse_list.topLevelItemCount() == 5
        sep_count = sum(
            1 for i in range(host.browse_list.topLevelItemCount())
            if host.browse_list.topLevelItem(i).data(0, _SEPARATOR_ROLE)
        )
        assert sep_count == 2


def test_on_sort_changed_rebuilds_separators_from_cache(qapp):
    """_on_browse_sort_changed rebuilds from the cached _browse_programs without
    a re-fetch — separators appear/disappear as the (col, order) changes."""
    with patch(_FROZEN_TZ_PATCH, lambda: timezone.utc):
        host = _make_render_host(qapp, title_map={"c1": "ESPN"})
        host._save_epg_sort = MagicMock()
        _ascending(host)
        progs = [
            _FakeProg("c1", "Show A", datetime(2026, 8, 1, 20, 0, 0)),
            _FakeProg("c1", "Show B", datetime(2026, 8, 2, 9, 0, 0)),
        ]
        _EpgBrowseMixin._render_browse(host, progs)
        assert host.browse_list.topLevelItemCount() == 4  # 2 rows + 2 separators

        # Simulate the user clicking the Channel header (col 2) — the header's own
        # sort indicator changes BEFORE the signal fires (real Qt behavior); we
        # mirror that by setting it first, then invoking the handler.
        _other_sort(host)
        _EpgBrowseMixin._on_browse_sort_changed(host, 2, Qt.SortOrder.AscendingOrder)
        host._save_epg_sort.assert_called_once_with("browse", 2, Qt.SortOrder.AscendingOrder)
        assert host.browse_list.topLevelItemCount() == 2, "Separators must be gone (rebuilt flat)"

        # And back to Time-ascending brings them back.
        _ascending(host)
        _EpgBrowseMixin._on_browse_sort_changed(host, 0, Qt.SortOrder.AscendingOrder)
        assert host.browse_list.topLevelItemCount() == 4


def test_on_sort_changed_noop_without_cache(qapp):
    """No cached page data (e.g. sort changed before any fetch completed) → no crash,
    no render attempted."""
    host = _make_render_host(qapp)
    host._save_epg_sort = MagicMock()
    host._browse_programs = []
    called = []
    host._render_browse = lambda *a, **k: called.append(True)
    _EpgBrowseMixin._on_browse_sort_changed(host, 0, Qt.SortOrder.AscendingOrder)
    host._save_epg_sort.assert_called_once()
    assert called == []


# ---------------------------------------------------------------------------
# Q3 — scroll→scrubber sync skips separator rows
# ---------------------------------------------------------------------------

def test_sync_scrubber_skips_separator_row(qapp):
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._scrubber_ready = True
    host._scrubber_left = datetime(2026, 8, 1, 0, 0, 0)
    host._scrubber_increment = 30
    host._last_seek_value = None
    host._scrubber_syncing = False
    host._update_scrubber_labels = lambda: None

    seen_values = []
    host._browse_scrubber = SimpleNamespace(
        value=lambda: 0,
        minimum=lambda: 0,
        maximum=lambda: 1000,
        setValue=lambda v: seen_values.append(v),
    )

    tree = QTreeWidget()
    tree.setColumnCount(6)
    sep = QTreeWidgetItem(["Tonight · Sat Aug 1", "", "", "", "", ""])
    sep.setData(0, _SEPARATOR_ROLE, True)
    tree.addTopLevelItem(sep)
    real_start = datetime(2026, 8, 1, 20, 0, 0)  # 40 * 30-min steps from left
    real = QTreeWidgetItem(["8:00 PM", "", "ESPN", "", "SportsCenter", "30m"])
    real.setData(0, _START_ROLE, real_start)
    tree.addTopLevelItem(real)

    host.browse_list = tree
    # Simulate the topmost visible row being the (non-interactive) separator —
    # the sync must skip forward to the next real row instead of bailing out.
    host.browse_list.itemAt = lambda x, y: sep

    _EpgBrowseMixin._sync_scrubber_to_scroll(host)

    assert seen_values == [40], (
        f"Expected the scrubber to sync past the separator to the real row's time, got {seen_values}"
    )
    assert host._last_seek_value == 40


def test_sync_scrubber_returns_when_only_separators_visible(qapp):
    """No real row anywhere below the topmost separator → no-op, no crash."""
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._scrubber_ready = True
    host._scrubber_left = datetime(2026, 8, 1, 0, 0, 0)
    host._scrubber_increment = 30
    host._last_seek_value = None
    host._scrubber_syncing = False
    host._update_scrubber_labels = lambda: None
    host._browse_scrubber = SimpleNamespace(
        value=lambda: 0, minimum=lambda: 0, maximum=lambda: 1000,
        setValue=lambda v: pytest.fail("must not seek — no real row present"),
    )

    tree = QTreeWidget()
    tree.setColumnCount(6)
    sep = QTreeWidgetItem(["Tonight · Sat Aug 1", "", "", "", "", ""])
    sep.setData(0, _SEPARATOR_ROLE, True)
    tree.addTopLevelItem(sep)
    host.browse_list = tree
    host.browse_list.itemAt = lambda x, y: sep

    _EpgBrowseMixin._sync_scrubber_to_scroll(host)  # must not raise


# ===========================================================================
# Separator rows are non-interactive (double-click / selection / context menu)
# ===========================================================================

def test_double_click_on_separator_is_noop(qapp):
    from PyQt6.QtWidgets import QTreeWidgetItem
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._play_channel = MagicMock()
    sep = QTreeWidgetItem(["Tonight · Sat Aug 1", "", "", "", "", ""])
    sep.setData(0, _SEPARATOR_ROLE, True)
    _EpgBrowseMixin._browse_double_click(host, sep, 0)
    host._play_channel.assert_not_called()


def test_selection_changed_on_separator_is_noop(qapp):
    from PyQt6.QtWidgets import QTreeWidgetItem
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._emit_channel_selected = MagicMock()
    sep = QTreeWidgetItem(["Tonight · Sat Aug 1", "", "", "", "", ""])
    sep.setData(0, _SEPARATOR_ROLE, True)
    _EpgBrowseMixin._browse_selection_changed(host, sep, None)
    host._emit_channel_selected.assert_not_called()


def test_context_menu_on_separator_is_noop(qapp):
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    tree = QTreeWidget()
    tree.setColumnCount(6)
    sep = QTreeWidgetItem(["Tonight · Sat Aug 1", "", "", "", "", ""])
    sep.setData(0, _SEPARATOR_ROLE, True)
    tree.addTopLevelItem(sep)
    tree.itemAt = lambda pos: sep
    host.browse_list = tree
    with patch("metatv.core.repositories.RepositoryFactory") as fac:
        _EpgBrowseMixin._on_browse_context_menu(host, MagicMock())
        fac.assert_not_called()


# ===========================================================================
# Q4 — Provider glyph, gated on >1 enabled provider, computed once per fetch
# ===========================================================================

def test_render_browse_shows_glyph_when_flag_set(qapp):
    host = _make_render_host(
        qapp,
        title_map={"c1": "ESPN"},
        provider_map={"c1": "p1"},
        show_glyph=True,
        provider_icon_map={"p1": "🔴"},
    )
    prog = _FakeProg("c1", "SportsCenter", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    item = host.browse_list.topLevelItem(0)
    assert item.text(2) == "🔴 ESPN", f"Expected glyph-prefixed channel name, got {item.text(2)!r}"


def test_render_browse_no_glyph_when_flag_unset(qapp):
    host = _make_render_host(
        qapp,
        title_map={"c1": "ESPN"},
        provider_map={"c1": "p1"},
        show_glyph=False,
        provider_icon_map={"p1": "🔴"},
    )
    prog = _FakeProg("c1", "SportsCenter", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    item = host.browse_list.topLevelItem(0)
    assert item.text(2) == "ESPN", f"Single-source setups must show no glyph, got {item.text(2)!r}"


def test_fetch_browse_glyph_flag_true_with_two_enabled_providers(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'q4_two.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="A", type="xtream", url="http://a",
                         username="u", password="p", is_active=True,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ProviderDB(id="p2", name="B", type="xtream", url="http://b",
                         username="u", password="p", is_active=True,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))
        s.add(EpgProgramDB(
            provider_id="p1", channel_epg_id="c1.epg", channel_db_id="c1",
            channel_name="c1", title="Show", description="d",
            start_time=now + timedelta(hours=1), stop_time=now + timedelta(hours=2),
        ))

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.db = db
    host.config = SimpleNamespace(epg_filler_patterns=[], epg_browse_hide_older_than_hours=0)
    host._channel_name_map = {}
    host._channel_title_map = {}
    host._channel_prefix_map = {}
    host._channel_quality_map = {}
    host._channel_provider_map = {}
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))

    _EpgBrowseMixin._fetch_browse(
        host, provider_ids=["p1"], anchor=None, search="",
        hide_filler=False, after=None, append=False, gen=1,
    )
    assert host._browse_show_provider_glyph is True
    assert host._browse_provider_icon_map["p1"]
    assert host._browse_provider_icon_map["p2"]


def test_fetch_browse_glyph_flag_false_with_one_enabled_provider(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'q4_one.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Solo", type="xtream", url="http://a",
                         username="u", password="p", is_active=True,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))
        s.add(EpgProgramDB(
            provider_id="p1", channel_epg_id="c1.epg", channel_db_id="c1",
            channel_name="c1", title="Show", description="d",
            start_time=now + timedelta(hours=1), stop_time=now + timedelta(hours=2),
        ))

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.db = db
    host.config = SimpleNamespace(epg_filler_patterns=[], epg_browse_hide_older_than_hours=0)
    host._channel_name_map = {}
    host._channel_title_map = {}
    host._channel_prefix_map = {}
    host._channel_quality_map = {}
    host._channel_provider_map = {}
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))

    _EpgBrowseMixin._fetch_browse(
        host, provider_ids=["p1"], anchor=None, search="",
        hide_filler=False, after=None, append=False, gen=1,
    )
    assert host._browse_show_provider_glyph is False


def test_fetch_browse_glyph_flag_false_when_second_provider_hidden(tmp_path):
    """A second provider that's inactive (hidden) must NOT count toward the >1
    enabled-provider gate."""
    db = Database(f"sqlite:///{tmp_path / 'q4_hidden.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="A", type="xtream", url="http://a",
                         username="u", password="p", is_active=True,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ProviderDB(id="p2", name="Hidden", type="xtream", url="http://b",
                         username="u", password="p", is_active=False,
                         account_exp_date=now + timedelta(days=30)))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))
        s.add(EpgProgramDB(
            provider_id="p1", channel_epg_id="c1.epg", channel_db_id="c1",
            channel_name="c1", title="Show", description="d",
            start_time=now + timedelta(hours=1), stop_time=now + timedelta(hours=2),
        ))

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.db = db
    host.config = SimpleNamespace(epg_filler_patterns=[], epg_browse_hide_older_than_hours=0)
    host._channel_name_map = {}
    host._channel_title_map = {}
    host._channel_prefix_map = {}
    host._channel_quality_map = {}
    host._channel_provider_map = {}
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))

    _EpgBrowseMixin._fetch_browse(
        host, provider_ids=["p1"], anchor=None, search="",
        hide_filler=False, after=None, append=False, gen=1,
    )
    assert host._browse_show_provider_glyph is False, (
        "An inactive (hidden) second provider must not trigger the glyph"
    )


# ===========================================================================
# Q5 — Footer text
# ===========================================================================

def test_footer_text_exact_with_more(qapp):
    host = _make_render_host(qapp, title_map={"c1": "ESPN"})
    host._browse_exhausted = False
    prog = _FakeProg("c1", "Show", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    assert host.browse_stats.text() == "1+ programmes · times shown in your local time"


def test_footer_text_exact_exhausted(qapp):
    host = _make_render_host(qapp, title_map={"c1": "ESPN"})
    host._browse_exhausted = True
    prog = _FakeProg("c1", "Show", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    assert host.browse_stats.text() == "1 programmes · times shown in your local time"


# ===========================================================================
# Q6 — Header tooltips/movable + persisted state + sort-col migration
# ===========================================================================

def _make_browse_tab_host(qapp, config=None):
    from PyQt6.QtWidgets import QWidget, QStackedWidget
    from metatv.gui.epg_view import EpgView

    cfg = config or SimpleNamespace(
        epg_hide_filler=False, epg_filter_state={}, save=MagicMock(),
    )
    host = QWidget.__new__(QWidget)
    QWidget.__init__(host, None)
    host.config = cfg
    host.stack = QStackedWidget(host)
    host._build_browse_tab = lambda: EpgView._build_browse_tab(host)
    # post-merge (wave3/epg-hygiene): build wires the persisting filler toggle
    host._on_hide_filler_toggled = MagicMock()
    host._update_hide_filler_btn_label = MagicMock()
    host._refresh_browse_anchors = lambda: EpgView._refresh_browse_anchors(host)
    host._on_search_changed = lambda *_: None
    host._reload_browse = lambda *_: None
    host._load_more_browse = lambda *_: None
    host._on_browse_scroll = lambda *_: None
    host._browse_double_click = lambda *_: None
    host._browse_selection_changed = lambda *_: None
    host._on_browse_context_menu = lambda *_: None
    host._save_epg_sort = lambda *a: None
    host._save_browse_header_state = lambda: EpgView._save_browse_header_state(host)
    host._on_browse_sort_changed = lambda *a: EpgView._on_browse_sort_changed(host, *a)
    host._on_anchor_selected = lambda *_: None
    host._on_scrubber_value_changed = lambda *_: None
    host._scrubber_seek = lambda *_: None
    host._build_browse_tab()
    return host


def test_browse_header_tooltips(qapp):
    host = _make_browse_tab_host(qapp)
    hdr = host.browse_list.headerItem()
    assert hdr.toolTip(1) == "Category / prefix extracted from channel name"
    assert hdr.toolTip(3) == "Stream quality (4K / FHD / HD / etc.)"


def test_browse_header_sections_movable(qapp):
    host = _make_browse_tab_host(qapp)
    assert host.browse_list.header().sectionsMovable()


def test_save_browse_header_state_writes_new_key(qapp):
    config = SimpleNamespace(epg_hide_filler=False, epg_filter_state={}, save=MagicMock())
    host = _make_browse_tab_host(qapp, config=config)
    host._save_browse_header_state()
    assert "browse_header_state" in config.epg_filter_state
    stored = config.epg_filter_state["browse_header_state"]
    assert isinstance(stored, str) and len(stored) > 0
    decoded = base64.b64decode(stored.encode("ascii"))
    assert len(decoded) > 0
    config.save.assert_called()


def test_restore_browse_header_state_round_trips(qapp):
    config1 = SimpleNamespace(epg_hide_filler=False, epg_filter_state={}, save=MagicMock())
    host1 = _make_browse_tab_host(qapp, config=config1)
    host1._save_browse_header_state()
    saved = config1.epg_filter_state["browse_header_state"]

    state2 = dict(config1.epg_filter_state)
    state2["browse_header_state"] = saved
    config2 = SimpleNamespace(epg_hide_filler=False, epg_filter_state=state2, save=MagicMock())
    host2 = _make_browse_tab_host(qapp, config=config2)  # must not raise
    assert host2.browse_list.columnCount() == 6


def test_corrupt_browse_header_state_is_noop(qapp):
    """A stale/corrupt saved state must not crash startup — no-op fallback."""
    config = SimpleNamespace(
        epg_hide_filler=False,
        epg_filter_state={"browse_header_state": "!!! not valid base64 !!!"},
        save=MagicMock(),
    )
    host = _make_browse_tab_host(qapp, config=config)  # must not raise
    assert host.browse_list.columnCount() == 6


def test_sort_col_migration_old_show_maps_to_new_show(qapp):
    """Old col 2 (Show) must migrate to new col 4 (Show), applied once."""
    config = SimpleNamespace(
        epg_hide_filler=False,
        epg_filter_state={"browse_sort_col": 2, "browse_sort_order": 0},
        save=MagicMock(),
    )
    host = _make_browse_tab_host(qapp, config=config)
    assert config.epg_filter_state["browse_sort_col"] == 4
    assert config.epg_filter_state["browse_col_migrated"] is True
    assert host.browse_list.header().sortIndicatorSection() == 4


def test_sort_col_migration_is_one_time_only(qapp):
    """Once migrated, a later launch must NOT re-map the now-new-format value —
    old col 2 and new col 2 (Channel) would otherwise collide."""
    config = SimpleNamespace(
        epg_hide_filler=False,
        epg_filter_state={
            "browse_sort_col": 4, "browse_sort_order": 0, "browse_col_migrated": True,
        },
        save=MagicMock(),
    )
    host = _make_browse_tab_host(qapp, config=config)
    assert config.epg_filter_state["browse_sort_col"] == 4, (
        "An already-migrated value must be read as-is, not re-mapped"
    )


def test_sort_col_migration_defaults_when_no_prior_state(qapp):
    config = SimpleNamespace(epg_hide_filler=False, epg_filter_state={}, save=MagicMock())
    host = _make_browse_tab_host(qapp, config=config)
    assert config.epg_filter_state["browse_sort_col"] == 0
    assert config.epg_filter_state["browse_col_migrated"] is True


# ===========================================================================
# Q8 — Shared watchlist-highlight helper
# ===========================================================================

def test_apply_watchlist_highlight_bolds_given_column(qapp):
    item = _EpgTreeItem(["a", "b", "c", "d", "e", "f"])
    apply_watchlist_highlight(item, range(6), 4)
    assert item.font(4).bold() is True
    assert item.font(0).bold() is False
    from metatv.gui import theme as _theme
    from PyQt6.QtGui import QColor
    assert item.foreground(0).color() == QColor(_theme.COLOR_ACCENT_HOVER)


def test_render_browse_bolds_show_column_for_watchlist_match(qapp):
    host = _make_render_host(qapp, title_map={"c1": "ESPN"})
    host.config.epg_watchlist_patterns = ["sportscenter"]
    prog = _FakeProg("c1", "SportsCenter", datetime(2026, 8, 1, 20, 0, 0))
    _EpgBrowseMixin._render_browse(host, [prog])
    item = host.browse_list.topLevelItem(0)
    assert item.font(4).bold() is True, "Browse must bold column 4 (Show) on a watchlist match"
    assert item.font(2).bold() is False


def test_render_on_now_bolds_show_column_for_watchlist_match(qapp):
    from metatv.gui.epg_on_now_mixin import _EpgOnNowMixin
    from PyQt6.QtWidgets import QTreeWidget, QLabel
    from metatv.gui.epg_widgets import _ProgressBarDelegate

    host = _EpgOnNowMixin.__new__(_EpgOnNowMixin)
    host.config = SimpleNamespace(
        epg_watchlist_patterns=["nightly news"],
        epg_filter_state={},
        epg_category_overrides={},
        epg_hidden_prefixes=[],
        global_filter_excluded_categories=[],
        global_filter_excluded_prefixes=[],
        global_filter_paused=False,
        category_name_overrides={},
        hide_icon="🚫",
    )
    tree = QTreeWidget()
    tree.setColumnCount(6)
    tree.setHeaderLabels(["", "Channel", "Quality", "Show", "Progress", "Hide"])
    tree.setItemDelegateForColumn(4, _ProgressBarDelegate(tree))
    host.on_now_list = tree
    host.on_now_stats = QLabel("")
    host.status_message = MagicMock()
    host.on_now_prefix_dropdown = MagicMock()
    host.on_now_type_dropdown = MagicMock()
    host.on_now_type_dropdown.get_selected.return_value = set()
    host._channel_name_map = {"ch4": "NBC"}
    host._channel_quality_map = {}
    host._channel_prefix_map = {}
    host._channel_title_map = {"ch4": "NBC"}
    host._channel_region_map = {}
    host._on_now_excluded_ct_ids = set()
    host._apply_on_now_filters = lambda: None
    host._update_filler_btn_label = lambda: None

    @with_programme_render_fields
    class _P:
        channel_db_id = "ch4"
        channel_epg_id = "epg4"
        title = "Nightly News"
        is_live = False
        is_new = False
        from datetime import datetime as _dt, timedelta as _td
        _now = _dt(2026, 6, 19, 20, 0, 0)
        start_time = _now - _td(minutes=30)
        stop_time = _now + _td(minutes=30)

    host._render_on_now([_P()])
    # Post-merge (wave3/epg-viewing-ux): On Now groups rows by prefix — the
    # programme row is the first CHILD of the first group header.
    group = host.on_now_list.topLevelItem(0)
    item = group.child(0) if group.childCount() else group
    assert item.font(3).bold() is True, "On Now must bold column 3 (Show) on a watchlist match"
    assert item.font(1).bold() is False
