"""Behavioral tests for the wave5 "alerts click semantics" fix — owner-reported,
third surface with this disease (Watch Queue + Alerts Matched were #365):

    "same double click and right click menu problem with the watch alerts for
    series as well" — then, once the double-click fix landed:

    "even the right click 'Open Series' just loads it into the details panel
    but doesn't browse the series."

Both reports trace to the SAME root cause: the monitored-series row in the
Watch Alerts sidebar section (metatv/gui/sidebar/alerts.py, the "Movies &
Series" sub-list) routed BOTH single-click, double-click, AND the right-click
"Open series" menu action through the identical details-only ``seriesClicked``
signal — so double-click and "Open series" never actually browsed/drilled into
the series, only single-click's intended behavior did anything useful.

Covers:
- Double-click on a monitored-series row now emits the new ``seriesActivated``
  signal (drill-in) — never the details-only ``seriesClicked`` a single click
  still (correctly, unchanged) uses.
- The right-click "Open series" menu action now triggers ``seriesActivated``
  too (previously it triggered ``seriesClicked`` — the exact second bug the
  owner reported). "Mark seen" / "Stop alerts" / "Manage…" remain reachable
  from the same menu, unaffected.
- ``_show_series_context_menu`` / ``_build_series_context_menu`` split (build
  vs exec) mirrors queue.py's already-shipped ``_build_matched_series_menu``
  (#365) — building the menu is never itself a mark-viewed/navigate side
  effect, and only a triggered action is.
- ``MainWindow.create_section("alerts")`` wires the new ``seriesActivated``
  signal to the SAME ``play_queue_item_id`` chokepoint #365 established for
  the Watch Queue / Alerts Matched ``matched_series`` row — proven by actually
  invoking the real ``create_section`` code path, not a source-text shape
  check.
- Regression pin: queue.py's ``_build_matched_series_menu`` "Open series" was
  audited alongside this fix and found to ALREADY route through the correct
  ``itemDoubleClicked`` -> ``play_queue_item_id`` chokepoint (not
  ``show_channel_details_by_id``) — no code change was needed there; this
  re-affirms test_queue_click_semantics.py's existing
  ``test_matched_series_menu_open_action_navigates`` coverage still holds.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _series(cid: str, title: str, unseen: int, display: str | None = None) -> dict:
    return {
        "series_channel_id": cid,
        "source_id": "s",
        "provider_id": "p1",
        "title": title,
        "display_title": display,
        "unseen_new": unseen,
        "baseline_episode_count": 10,
        "last_checked": None,
    }


class _FakeConfig:
    """In-memory Config stub — mirrors test_watch_alerts_consolidation.py's
    ``_FakeConfig`` so the real render/click/menu code runs unmodified."""

    expand_icon = ">"
    collapse_icon = "v"

    #: These tests assert how a row RENDERS and how a click routes, not
    #: which entries are eligible to be listed. The section now lists only
    #: firing entries by default, so they opt into the full list — the
    #: filter itself is covered by tests/test_alerts_new_only.py.
    alerts_show_idle_items = True

    def __init__(self):
        self.monitored_series = []
        self.vod_watch_alerts = []

    def save(self):
        pass

    def add_monitored_series(self, entry: dict) -> None:
        self.monitored_series = list(self.monitored_series) + [entry]

    def get_monitored_series(self) -> list:
        return list(self.monitored_series)

    def get_vod_watch_alerts(self) -> list:
        return list(self.vod_watch_alerts)

    def get_rules_with_new_matches_count(self) -> int:
        return 0

    def get_unviewed_vod_match_count(self) -> int:
        return 0

    def get_vod_rule_unviewed_count(self, _created: str) -> int:
        return 0


def _make_section(config):
    """A WatchAlertsSection stub exercising only the Movies & Series render path
    (same technique as test_watch_alerts_consolidation.py's ``_make_section``).

    Built via ``__new__`` (no QObject ``__init__``), so every pyqtSignal this
    section can emit/connect is pre-stubbed as a MagicMock here — a real bound
    signal accessed on an un-``__init__``'d QObject raises
    ``RuntimeError: super-class __init__() ... was never called``. Tests that
    care about a specific signal's calls reassign it fresh (shadowing these
    defaults, same technique test_watch_alerts_consolidation.py uses).
    """
    from PyQt6.QtWidgets import QListWidget
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    section = WatchAlertsSection.__new__(WatchAlertsSection)
    section.config = config
    from tests.conftest import wire_watch_alerts_group_state
    wire_watch_alerts_group_state(section)
    section._series_collapsed = False
    section._vod_list = QListWidget()
    section._update_vod_toggle_label = MagicMock()
    section.update_new_match_badge = MagicMock()
    section.seriesClicked = MagicMock()
    section.seriesActivated = MagicMock()
    section.seriesMarkSeenRequested = MagicMock()
    section.seriesStopRequested = MagicMock()
    section.manageWatchForClicked = MagicMock()
    return section


# ===========================================================================
# Part 1: double-click routing
# ===========================================================================

class TestSeriesDoubleClick:

    def test_series_row_double_click_emits_series_activated_not_series_clicked(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()
        section.seriesClicked = MagicMock()
        section.seriesActivated = MagicMock()

        lst = section._vod_list
        # item 0 is the "──── Series ────" divider; item 1 is the series row.
        section._on_vod_item_double_clicked(lst.item(1))

        section.seriesActivated.emit.assert_called_once_with("a")
        section.seriesClicked.emit.assert_not_called()

    def test_single_click_keeps_details_only_behavior(self, qapp):
        """Regression guard: single click is unchanged by this fix — only
        double-click/menu-open move off the details-only seam."""
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()
        section.seriesClicked = MagicMock()
        section.seriesActivated = MagicMock()

        section._on_vod_item_clicked(section._vod_list.item(1))

        section.seriesClicked.emit.assert_called_once_with("a")
        section.seriesActivated.emit.assert_not_called()

    def test_double_clicking_a_group_heading_does_nothing(self, qapp):
        """A heading is chrome. Double-clicking it must not open anything.

        The item is NoItemFlags and its widget owns single-click collapse, so a
        double-click has nowhere to go — which is the point: it used to be an
        item whose kind the handler had to special-case.
        """
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()

        item = section._vod_list.item(0)
        from metatv.gui.sidebar.base import GroupHeading

        assert isinstance(section._vod_list.itemWidget(item), GroupHeading)
        section.seriesClicked = MagicMock()
        section._on_vod_item_double_clicked(item)
        section.seriesClicked.emit.assert_not_called()

    def test_rule_row_double_click_still_opens_manage_dialog(self, qapp):
        """Regression guard: keyword-rule row double-click is untouched by
        this series-only fix."""
        cfg = _FakeConfig()
        cfg.vod_watch_alerts = [{
            "text": "Dune", "match_type": "movie",
            "created": datetime.now(timezone.utc).isoformat(),
            "alerted_ids": [], "viewed_ids": [],
        }]
        section = _make_section(cfg)
        section.refresh_vod_rules()
        section.manageWatchForClicked = MagicMock()

        section._on_vod_item_double_clicked(section._vod_list.item(0))

        section.manageWatchForClicked.emit.assert_called_once()


# ===========================================================================
# Part 2: right-click "Open series" menu action
# ===========================================================================

class TestSeriesContextMenu:

    def test_build_series_context_menu_has_expected_actions(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)

        menu = section._build_series_context_menu("a")
        labels = [act.text() for act in menu.actions()]

        assert any("Open series" in t for t in labels), labels
        assert any("Mark seen" in t for t in labels), labels
        assert any("Stop alerts" in t for t in labels), labels
        assert any("Manage" in t for t in labels), labels

    def test_mark_seen_action_hidden_when_no_unseen(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 0, "Apple"))
        section = _make_section(cfg)

        menu = section._build_series_context_menu("a")
        labels = [act.text() for act in menu.actions()]

        assert not any("Mark seen" in t for t in labels), labels

    def test_open_series_action_triggers_series_activated_not_series_clicked(self, qapp):
        """The core owner-reported bug: right-click "Open series" used to
        trigger the details-only ``seriesClicked``. It must now trigger
        ``seriesActivated`` — the SAME drill chokepoint double-click uses."""
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.seriesClicked = MagicMock()
        section.seriesActivated = MagicMock()

        menu = section._build_series_context_menu("a")
        open_action = next(a for a in menu.actions() if "Open series" in a.text())
        open_action.trigger()

        section.seriesActivated.emit.assert_called_once_with("a")
        section.seriesClicked.emit.assert_not_called()

    def test_mark_seen_action_emits_mark_seen_request(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.seriesMarkSeenRequested = MagicMock()

        menu = section._build_series_context_menu("a")
        seen_action = next(a for a in menu.actions() if "Mark seen" in a.text())
        seen_action.trigger()

        section.seriesMarkSeenRequested.emit.assert_called_once_with("a")

    def test_stop_alerts_action_emits_stop_request(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.seriesStopRequested = MagicMock()

        menu = section._build_series_context_menu("a")
        stop_action = next(a for a in menu.actions() if "Stop alerts" in a.text())
        stop_action.trigger()

        section.seriesStopRequested.emit.assert_called_once_with("a")

    def test_building_menu_never_activates_or_marks_seen(self, qapp):
        """Merely building (opening) the menu must not navigate or mutate
        anything — only an explicit triggered action does."""
        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.seriesActivated = MagicMock()
        section.seriesMarkSeenRequested = MagicMock()

        section._build_series_context_menu("a")

        section.seriesActivated.emit.assert_not_called()
        section.seriesMarkSeenRequested.emit.assert_not_called()

    def test_show_series_context_menu_routes_through_the_same_builder(self, qapp, monkeypatch):
        """``_show_series_context_menu`` (the actual right-click entry point)
        must build via ``_build_series_context_menu`` — not a parallel,
        hand-duplicated menu — so the fix above is what a real right-click
        exercises. Stubs ``QMenu.exec`` so the test does not block on a real
        popup event loop."""
        from PyQt6.QtWidgets import QMenu

        cfg = _FakeConfig()
        cfg.add_monitored_series(_series("a", "Apple", 2, "Apple"))
        section = _make_section(cfg)
        section.refresh_vod_rules()

        exec_calls = []
        monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: exec_calls.append(self))

        item = section._vod_list.item(1)
        pos = section._vod_list.visualItemRect(item).center()
        section._show_series_context_menu(item, pos)

        assert len(exec_calls) == 1
        labels = [act.text() for act in exec_calls[0].actions()]
        assert any("Open series" in t for t in labels), labels


# ===========================================================================
# Part 3: MainWindow.create_section("alerts") wiring
# ===========================================================================

class TestCreateSectionWiring:
    """Exercises the REAL MainWindow.create_section("alerts") code path — not
    a source-text shape check — to prove seriesActivated is actually connected
    to the play_queue_item_id chokepoint (the same one #365 wired the Watch
    Queue / Alerts Matched matched_series row's navigate signal to)."""

    def _stub_host(self, tmp_path: Path):
        """A real QWidget (NOT a SimpleNamespace) carrying MagicMock handler
        attributes: create_section passes ``self`` as WatchAlertsSection's
        ``parent`` positional arg, which PyQt requires to be a QWidget/None —
        a plain SimpleNamespace raises a TypeError there."""
        from PyQt6.QtWidgets import QWidget
        from metatv.core.config import Config
        from metatv.core.database import Database

        db = Database(f"sqlite:///{tmp_path / 'test.db'}")
        db.create_tables()
        cfg, _ = Config.load()  # isolated to a tmp HOME by the autouse fixture

        host = QWidget()
        host.config = cfg
        host.db = db
        host.stream_retry_manager = MagicMock()
        host.vod_watch_alert_manager = MagicMock()
        host.series_monitor = MagicMock()
        host._on_alert_clicked = MagicMock()
        host._on_alert_channel_details = MagicMock()
        host._on_alert_channel_context_menu = MagicMock()
        host._on_retry_play_requested = MagicMock()
        host._on_retry_context_menu_requested = MagicMock()
        host._on_add_watch_for = MagicMock()
        host._open_vod_alerts_dialog = MagicMock()
        host.show_channel_details_by_id = MagicMock()
        host._on_vod_rule_view_matches = MagicMock()
        host._on_vod_rule_show_matches = MagicMock()
        host._on_vod_rule_remove = MagicMock()
        host._clear_all_alerts = MagicMock()
        host._clear_vod_rule_alert = MagicMock()
        host.play_queue_item_id = MagicMock()
        host._on_mark_series_seen = MagicMock()
        host._unmonitor_series = MagicMock()
        host._refresh_alert_visibility = MagicMock()
        host._refresh_vod_alerts_section = MagicMock()
        host._backfill_series_display_titles = MagicMock()
        return host

    def test_series_activated_wired_to_play_queue_item_id(self, tmp_path, qapp):
        from metatv.gui.main_window import MainWindow

        host = self._stub_host(tmp_path)
        section = MainWindow.create_section(host, "alerts")

        section.seriesActivated.emit("cid-123")

        host.play_queue_item_id.assert_called_once_with("cid-123")

    def test_series_clicked_still_wired_to_details_only(self, tmp_path, qapp):
        """Regression guard: single-click details routing is unchanged."""
        from metatv.gui.main_window import MainWindow

        host = self._stub_host(tmp_path)
        section = MainWindow.create_section(host, "alerts")

        section.seriesClicked.emit("cid-456")

        host.show_channel_details_by_id.assert_called_once_with("cid-456")
