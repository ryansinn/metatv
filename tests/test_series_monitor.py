"""Behavioral tests for the series monitor feature.

Covers:
- Config helpers: add/remove/is_monitored/update/clear_unseen round-trip.
- SeriesMonitorManager._worker_check_entries detects a delta and emits _notify_new.
- SeriesMonitorManager._on_new_episodes updates config and fires new_episodes_found.
- No notification or config change when episode count is unchanged (delta == 0).
- NewEpisodesSection.refresh() renders entries with unseen > 0 and empty state.
- channel_menu: monitor_series action applies only to series, not live/movie.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# qapp fixture (headless Qt)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Minimal Config stub
# ---------------------------------------------------------------------------

class _FakeConfig:
    """In-memory Config stub that implements the monitored_series helpers."""

    def __init__(self):
        self.monitored_series = []

    def save(self):
        pass  # no-op for tests

    def add_monitored_series(self, entry: dict) -> None:
        cid = entry.get("series_channel_id")
        if not cid:
            return
        if not self.is_series_monitored(cid):
            self.monitored_series = list(self.monitored_series) + [entry]

    def remove_monitored_series(self, series_channel_id: str) -> None:
        self.monitored_series = [
            e for e in self.monitored_series
            if e.get("series_channel_id") != series_channel_id
        ]

    def is_series_monitored(self, series_channel_id: str) -> bool:
        return any(
            e.get("series_channel_id") == series_channel_id
            for e in self.monitored_series
        )

    def get_monitored_series(self) -> list:
        return list(self.monitored_series)

    def get_monitored_for_provider(self, provider_id: str) -> list:
        return [
            e for e in self.monitored_series
            if e.get("provider_id") == provider_id
        ]

    def update_monitored_series(self, series_channel_id: str, **fields) -> None:
        updated = []
        for e in self.monitored_series:
            if e.get("series_channel_id") == series_channel_id:
                merged = dict(e)
                merged.update(fields)
                updated.append(merged)
            else:
                updated.append(e)
        self.monitored_series = updated

    def clear_unseen(self, series_channel_id: str) -> None:
        self.update_monitored_series(series_channel_id, unseen_new=0)


# ===========================================================================
# Part 1: Config helper round-trips
# ===========================================================================

class TestConfigHelpers:
    """Config helper round-trips for the monitored_series list."""

    def _make_entry(self, cid: str = "ch1", provider_id: str = "p1") -> dict:
        return {
            "series_channel_id": cid,
            "source_id": "s1",
            "provider_id": provider_id,
            "title": "Test Series",
            "baseline_episode_count": 10,
            "unseen_new": 0,
            "last_checked": None,
        }

    def test_add_and_is_monitored(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        assert cfg.is_series_monitored("ch1")

    def test_add_is_idempotent(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        cfg.add_monitored_series(self._make_entry("ch1"))
        assert len(cfg.get_monitored_series()) == 1

    def test_not_monitored_returns_false(self):
        cfg = _FakeConfig()
        assert not cfg.is_series_monitored("nonexistent")

    def test_remove_monitored(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        cfg.remove_monitored_series("ch1")
        assert not cfg.is_series_monitored("ch1")
        assert len(cfg.get_monitored_series()) == 0

    def test_remove_nonexistent_is_noop(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        cfg.remove_monitored_series("does_not_exist")
        assert len(cfg.get_monitored_series()) == 1

    def test_update_monitored_series_fields(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        cfg.update_monitored_series("ch1", baseline_episode_count=15, unseen_new=5)
        entry = cfg.get_monitored_series()[0]
        assert entry["baseline_episode_count"] == 15
        assert entry["unseen_new"] == 5

    def test_clear_unseen_resets_to_zero(self):
        cfg = _FakeConfig()
        entry = self._make_entry("ch1")
        entry["unseen_new"] = 3
        cfg.add_monitored_series(entry)
        cfg.clear_unseen("ch1")
        found = cfg.get_monitored_series()[0]
        assert found["unseen_new"] == 0

    def test_get_monitored_for_provider_filters_correctly(self):
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1", provider_id="p1"))
        cfg.add_monitored_series(self._make_entry("ch2", provider_id="p2"))
        result = cfg.get_monitored_for_provider("p1")
        assert len(result) == 1
        assert result[0]["series_channel_id"] == "ch1"

    def test_get_monitored_returns_copy(self):
        """Mutating the returned list must not affect config state."""
        cfg = _FakeConfig()
        cfg.add_monitored_series(self._make_entry("ch1"))
        lst = cfg.get_monitored_series()
        lst.clear()
        assert len(cfg.get_monitored_series()) == 1


# ===========================================================================
# Part 2: SeriesMonitorManager — worker detects delta
# ===========================================================================

def _make_file_backed_db(tmp_path: Path):
    """Create a file-backed Database with tables (NOT :memory: — each connection
    on :memory: gets a separate empty DB, which breaks pooled sessions)."""
    from metatv.core.database import Database
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    return db


def _make_provider_db(session, provider_id: str = "p1"):
    """Insert a minimal ProviderDB row."""
    from metatv.core.database import ProviderDB
    provider = ProviderDB(
        id=provider_id,
        name="Test Provider",
        type="xtream",
        url="http://test.example.com",  # NOT NULL in the schema
        urls='[{"url": "http://test.example.com", "primary": true}]',
        username="user",
        password="pass",
        is_active=True,
    )
    session.add(provider)
    session.flush()
    return provider


def _make_series_channel(session, channel_id: str = "ch1", provider_id: str = "p1",
                          source_id: str = "s1"):
    """Insert a minimal series ChannelDB row."""
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id,
        source_id=source_id,
        provider_id=provider_id,
        name="Test Series",
        media_type="series",
    )
    session.add(ch)
    session.flush()
    return ch


class TestSeriesMonitorWorker:
    """Tests for the worker thread and main-thread slot."""

    def test_worker_emits_notify_new_when_delta_positive(self, tmp_path):
        """Worker emits _notify_new with the right delta when episode count grows."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "My Series",
            "baseline_episode_count": 10,
            "unseen_new": 0,
            "last_checked": None,
        })

        # Insert provider into DB
        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        # Build a fake plugin that returns 15 episodes
        _fake_data = {
            "episodes": {
                "1": [{"info": {}} for _ in range(8)],
                "2": [{"info": {}} for _ in range(7)],
            }
        }  # 15 total

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider") as mock_get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as mock_run:

            mock_plugin = MagicMock()
            mock_get_provider.return_value = mock_plugin
            mock_run.return_value = _fake_data

            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, total: notify_args.append((cid, delta, title, total))
            )

            entries = cfg.get_monitored_for_provider("p1")
            manager._worker_check_entries(entries)

            # Process pending signals
            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        assert len(notify_args) == 1, f"Expected 1 notification, got: {notify_args}"
        cid, delta, title, new_total = notify_args[0]
        assert cid == "ch1"
        assert delta == 5, f"Expected delta=5 (15-10), got {delta}"
        assert new_total == 15
        assert "My Series" in title

        manager.shutdown()

    def test_worker_emits_zero_delta_when_unchanged(self, tmp_path):
        """Worker emits _notify_new with delta=0 when count is unchanged."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Stable Series",
            "baseline_episode_count": 10,
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        _fake_data = {"episodes": {"1": [{}] * 10}}  # exactly 10

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider") as mock_get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as mock_run:

            mock_plugin = MagicMock()
            mock_get_provider.return_value = mock_plugin
            mock_run.return_value = _fake_data

            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, total: notify_args.append((cid, delta, title, total))
            )

            entries = cfg.get_monitored_for_provider("p1")
            manager._worker_check_entries(entries)

            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        # Should still emit (delta=0 branch) but with delta=0
        assert len(notify_args) == 1
        _, delta, _, _ = notify_args[0]
        assert delta == 0

        manager.shutdown()

    def test_worker_none_baseline_establishes_without_alerting(self, tmp_path):
        """A monitored entry whose baseline was never established (None) must NOT
        alert on the whole back-catalog — the first check just establishes it.

        Regression guard: previously baseline defaulted to 0, so a failed/late
        set_baseline left baseline=0 and the next check reported the entire
        back-catalog as 'new episodes'.
        """
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Fresh Series",
            "baseline_episode_count": None,   # never established
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1")

        _fake_data = {"episodes": {"1": [{}] * 42}}  # a big back-catalog

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider") as mock_get_provider, \
             patch("metatv.core.series_monitor.asyncio.run") as mock_run:

            mock_get_provider.return_value = MagicMock()
            mock_run.return_value = _fake_data

            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, total: notify_args.append((cid, delta, title, total))
            )

            manager._worker_check_entries(cfg.get_monitored_for_provider("p1"))

            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        # Establishes the baseline (delta=0) — must NOT report 42 "new" episodes.
        assert len(notify_args) == 1
        _cid, delta, _title, new_total = notify_args[0]
        assert delta == 0, f"None-baseline must establish (delta 0), got {delta}"
        assert new_total == 42

        manager.shutdown()

    def test_on_new_episodes_updates_config_and_fires_signal(self, qapp, tmp_path):
        """_on_new_episodes updates baseline + unseen and emits new_episodes_found."""
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Growing Series",
            "baseline_episode_count": 10,
            "unseen_new": 0,
            "last_checked": None,
        })

        found_signal_args: list[tuple] = []
        notif_mock = MagicMock()

        manager = SeriesMonitorManager(db, cfg, notifications=notif_mock)
        manager.new_episodes_found.connect(
            lambda cid, total_unseen: found_signal_args.append((cid, total_unseen))
        )

        # Call the main-thread slot directly (delta > 0)
        manager._on_new_episodes("ch1", 5, "Growing Series", 15)

        # Config was updated
        entries = cfg.get_monitored_series()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["baseline_episode_count"] == 15, \
            f"baseline should be 15, got {entry['baseline_episode_count']}"
        assert entry["unseen_new"] == 5, \
            f"unseen_new should be 5, got {entry['unseen_new']}"
        assert entry["last_checked"] is not None

        # Notification was shown
        assert notif_mock.show.called, "NotificationManager.show() should have been called"
        call_kwargs = notif_mock.show.call_args
        assert "new episode" in str(call_kwargs).lower()

        # Signal was emitted
        assert len(found_signal_args) == 1
        assert found_signal_args[0] == ("ch1", 5)

        manager.shutdown()

    def test_on_new_episodes_no_notification_when_delta_zero(self, qapp, tmp_path):
        """_on_new_episodes with delta=0 updates config but does NOT show a notification."""
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Stable Series",
            "baseline_episode_count": 10,
            "unseen_new": 0,
            "last_checked": None,
        })

        notif_mock = MagicMock()
        found_signal_args: list = []

        manager = SeriesMonitorManager(db, cfg, notifications=notif_mock)
        manager.new_episodes_found.connect(
            lambda cid, n: found_signal_args.append((cid, n))
        )

        manager._on_new_episodes("ch1", 0, "Stable Series", 10)

        # Baseline updated, last_checked set
        entry = cfg.get_monitored_series()[0]
        assert entry["baseline_episode_count"] == 10
        assert entry["last_checked"] is not None

        # No notification for delta=0
        assert not notif_mock.show.called, \
            "No notification should fire when delta=0"
        # No public signal for delta=0
        assert len(found_signal_args) == 0

        manager.shutdown()

    def test_on_new_episodes_accumulates_unseen(self, qapp, tmp_path):
        """If the user hasn't cleared unseen, additional deltas accumulate."""
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        # Start with 2 already-unseen
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Accumulating Series",
            "baseline_episode_count": 12,
            "unseen_new": 2,
            "last_checked": None,
        })

        manager = SeriesMonitorManager(db, cfg, notifications=MagicMock())

        # Now 3 more appear
        manager._on_new_episodes("ch1", 3, "Accumulating Series", 15)

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 5, \
            f"Expected 2+3=5 unseen, got {entry['unseen_new']}"
        assert entry["baseline_episode_count"] == 15

        manager.shutdown()


# ===========================================================================
# Part 3: NewEpisodesSection render
# ===========================================================================

class TestNewEpisodesSection:
    """Tests for NewEpisodesSection.refresh() rendering."""

    def _make_section(self, config, qapp):
        """Create a NewEpisodesSection via __new__ so no window is needed."""
        from metatv.gui.sidebar.new_episodes import NewEpisodesSection
        from PyQt6.QtWidgets import QListWidget

        section = NewEpisodesSection.__new__(NewEpisodesSection)
        # Initialize base CollapsibleSection state without calling the full __init__
        section.config = config
        section.is_empty = True
        section._user_collapsed = False
        section.is_collapsed = False

        # Give it a real QListWidget for testing
        section._list = QListWidget()
        return section

    def test_refresh_renders_entries_with_unseen(self, qapp):
        """refresh() creates one row per series with unseen_new > 0."""
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "My Watched Show",
            "baseline_episode_count": 10,
            "unseen_new": 3,
            "last_checked": None,
        })
        cfg.add_monitored_series({
            "series_channel_id": "ch2",
            "source_id": "s2",
            "provider_id": "p1",
            "title": "Caught Up Show",
            "baseline_episode_count": 5,
            "unseen_new": 0,
            "last_checked": None,
        })

        from metatv.gui.sidebar.new_episodes import NewEpisodesSection
        from PyQt6.QtWidgets import QListWidget

        section = self._make_section(cfg, qapp)

        # Minimal stubs for set_empty (it normally touches Qt widgets)
        section.set_empty = lambda v: setattr(section, "is_empty", v)

        section.refresh()

        # Should have "My Watched Show" row + "Mark seen" sub-row, but NOT ch2
        texts = [
            section._list.item(i).text()
            for i in range(section._list.count())
        ]
        assert any("My Watched Show" in t for t in texts), \
            f"Expected 'My Watched Show' row, got: {texts}"
        assert any("+3" in t for t in texts), \
            f"Expected +3 eps badge, got: {texts}"
        assert not any("Caught Up Show" in t for t in texts), \
            f"Caught-up series should not appear: {texts}"
        # Mark-seen sub-row
        assert any("Mark seen" in t for t in texts), \
            f"Expected 'Mark seen' sub-row, got: {texts}"

    def test_refresh_empty_state_when_no_unseen(self, qapp):
        """refresh() renders a muted 'No new episodes' row when all are caught up."""
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Fully Caught Up",
            "baseline_episode_count": 8,
            "unseen_new": 0,
            "last_checked": None,
        })

        section = self._make_section(cfg, qapp)
        section.set_empty = lambda v: setattr(section, "is_empty", v)

        section.refresh()

        texts = [
            section._list.item(i).text()
            for i in range(section._list.count())
        ]
        assert any("No new episodes" in t for t in texts), \
            f"Expected 'No new episodes', got: {texts}"

    def test_refresh_empty_state_when_nothing_monitored(self, qapp):
        """refresh() shows empty state when no series are monitored at all."""
        cfg = _FakeConfig()
        section = self._make_section(cfg, qapp)
        section.set_empty = lambda v: setattr(section, "is_empty", v)

        section.refresh()

        texts = [
            section._list.item(i).text()
            for i in range(section._list.count())
        ]
        assert any("No new episodes" in t for t in texts), \
            f"Expected empty state, got: {texts}"

    def test_refresh_ep_singular_label(self, qapp):
        """'1 new ep' should use singular 'ep' label."""
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "One More Episode",
            "baseline_episode_count": 9,
            "unseen_new": 1,
            "last_checked": None,
        })

        section = self._make_section(cfg, qapp)
        section.set_empty = lambda v: setattr(section, "is_empty", v)

        section.refresh()

        texts = [
            section._list.item(i).text()
            for i in range(section._list.count())
        ]
        # Should say "+1 ep" not "+1 eps"
        assert any("+1 ep" in t and "+1 eps" not in t for t in texts), \
            f"Expected '+1 ep' (singular), got: {texts}"


# ===========================================================================
# Part 4: channel_menu monitor_series applies correctly
# ===========================================================================

class TestMonitorSeriesMenuAction:
    """Behavioral tests for the monitor_series action in channel_menu."""

    def _ctx(self, media_type: str, is_monitored: bool = False,
             is_hidden: bool = False, surface: str = "channel") -> "ChannelMenuContext":
        from metatv.gui.channel_menu import ChannelMenuContext
        return ChannelMenuContext(
            channel_ids=["ch1"],
            surface=surface,
            media_type=media_type,
            is_favorite=False,
            in_queue=False,
            rating=0,
            is_hidden=is_hidden,
            is_watched=False,
            is_series_monitored=is_monitored,
            has_unavailable=False,
            channel_name="Test",
            channel_found=True,
        )

    def test_monitor_applies_to_series(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("series")
        assert ACTIONS["monitor_series"].applies(ctx), \
            "monitor_series must apply to media_type='series'"

    def test_monitor_does_not_apply_to_movie(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("movie")
        assert not ACTIONS["monitor_series"].applies(ctx), \
            "monitor_series must NOT apply to media_type='movie'"

    def test_monitor_does_not_apply_to_live(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("live")
        assert not ACTIONS["monitor_series"].applies(ctx), \
            "monitor_series must NOT apply to media_type='live'"

    def test_monitor_does_not_apply_when_hidden(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("series", is_hidden=True)
        assert not ACTIONS["monitor_series"].applies(ctx), \
            "monitor_series must not apply to hidden channels"

    def test_monitor_label_unmonitored(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("series", is_monitored=False)
        label = ACTIONS["monitor_series"].label(ctx)
        assert "Alert" in label, f"Expected 'Alert …', got {label!r}"
        assert "Stop" not in label, \
            f"Expected NOT a 'Stop …' label when un-alerted, got {label!r}"

    def test_monitor_label_when_already_monitored(self, qapp):
        from metatv.gui.channel_menu import ACTIONS
        ctx = self._ctx("series", is_monitored=True)
        label = ACTIONS["monitor_series"].label(ctx)
        assert "Stop new-episode alerts" in label, f"Expected 'Stop new-episode alerts', got {label!r}"
        assert "Alert me to new" not in label

    def test_monitor_action_present_in_channel_surface_layout(self):
        from metatv.gui.channel_menu import SURFACE_LAYOUTS
        assert "monitor_series" in SURFACE_LAYOUTS["channel"], \
            "'monitor_series' must be listed in the 'channel' surface layout"

    def test_monitor_action_present_in_recommended_surface_layout(self):
        from metatv.gui.channel_menu import SURFACE_LAYOUTS
        assert "monitor_series" in SURFACE_LAYOUTS["recommended"], \
            "'monitor_series' must be listed in the 'recommended' surface layout"

    def test_monitor_action_present_in_all_engaged_surfaces(self):
        """Regression: action must appear on EVERY series-bearing surface, not only
        the main channel list (was reported missing on history/favorites/queue)."""
        from metatv.gui.channel_menu import SURFACE_LAYOUTS
        for surface in ("history", "favorites", "queue", "recommended"):
            assert "monitor_series" in SURFACE_LAYOUTS[surface], \
                f"'monitor_series' must be in the '{surface}' surface layout"

    def test_monitor_menu_built_for_series_on_engaged_surfaces(self, qapp):
        """build_channel_menu on history/favorites/queue includes Monitor for a series
        ctx (the shared seam supplies handler + media_type for all surfaces)."""
        from metatv.gui.channel_menu import build_channel_menu
        handlers = {a: (lambda: None) for a in (
            "play", "play_new_window", "favorite", "queue", "like", "dislike",
            "monitor_series", "hide", "remove_history", "clear_unavailable",
        )}
        for surface in ("history", "favorites", "queue"):
            ctx = self._ctx("series", surface=surface)
            menu = build_channel_menu(ctx, handlers, parent=None)
            texts = [a.text() for a in menu.actions() if not a.isSeparator()]
            assert any("Alert" in t for t in texts), \
                f"Alert action missing on '{surface}' surface; got {texts}"

    def test_monitor_menu_action_triggers_handler(self, qapp):
        """build_channel_menu wires up the monitor_series handler correctly."""
        from metatv.gui.channel_menu import build_channel_menu
        ctx = self._ctx("series")
        called: list[bool] = []
        handlers = {
            "play": lambda: None,
            "play_new_window": lambda: None,
            "favorite": lambda: None,
            "queue": lambda: None,
            "like": lambda: None,
            "dislike": lambda: None,
            "monitor_series": lambda: called.append(True),
            "watch": lambda: None,
            "track": lambda: None,
            "hide": lambda: None,
            "category": lambda: None,
        }
        menu = build_channel_menu(ctx, handlers, parent=None)
        acts = [a for a in menu.actions() if not a.isSeparator()]
        monitor_act = next(
            (a for a in acts if "Alert" in a.text() or "alert" in a.text().lower()),
            None
        )
        assert monitor_act is not None, \
            f"Expected an alert action in menu; actions: {[a.text() for a in acts]}"
        monitor_act.trigger()
        assert called, "monitor_series handler should have been called"


# ===========================================================================
# Part 5: details-pane action-bar Monitor button (series only)
# ===========================================================================

class TestActionBarMonitorButton:
    """Behavioral tests for the details-pane Monitor toggle button."""

    def _bar(self):
        from metatv.core.config import Config
        from metatv.gui.details_actions import _ActionBar
        return _ActionBar(Config())

    def test_monitor_button_hidden_for_non_series(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=False, is_monitored=False)
        assert bar.monitor_button.isHidden(), \
            "Monitor button must be hidden for non-series channels"

    def test_monitor_button_shown_for_series_with_label(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=True, is_monitored=False)
        assert not bar.monitor_button.isHidden(), \
            "Alert button must be shown for series"
        assert "Alert" in bar.monitor_button.text()
        assert "Alerting" not in bar.monitor_button.text()

    def test_monitor_button_reflects_monitored_state(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=True, is_monitored=True)
        assert "Alerting" in bar.monitor_button.text(), \
            "An alerting series must show the 'Alerting' label"

    def test_monitor_click_toggles_and_emits(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=True, is_monitored=False)
        emitted: list[bool] = []
        bar.monitor_clicked.connect(lambda: emitted.append(True))
        bar._on_monitor_clicked()
        assert bar._is_monitored is True
        assert "Alerting" in bar.monitor_button.text()
        assert emitted, "monitor_clicked must emit on toggle"


# ===========================================================================
# Part 6: Monitored Series management dialog (see-all + stop)
# ===========================================================================

class TestMonitoredSeriesDialog:
    """Behavioral tests for the see-all / stop-monitoring dialog."""

    def _cfg(self, n: int):
        cfg = _FakeConfig()
        for i in range(n):
            cfg.add_monitored_series({
                "series_channel_id": f"ch{i}",
                "source_id": f"s{i}",
                "provider_id": "p1",
                "title": f"Series {i}",
                "baseline_episode_count": 10,
                "unseen_new": (3 if i == 0 else 0),
                "last_checked": None,
            })
        return cfg

    def _rows(self, dlg) -> list:
        return [
            dlg._scroll_vl.itemAt(i).widget()
            for i in range(dlg._scroll_vl.count())
            if dlg._scroll_vl.itemAt(i).widget() is not None
        ]

    def test_lists_every_monitored_series(self, qapp):
        from metatv.gui.monitored_series_dialog import MonitoredSeriesDialog
        dlg = MonitoredSeriesDialog(self._cfg(3))
        assert len(self._rows(dlg)) == 3, "one row per monitored series"

    def test_empty_state_when_nothing_monitored(self, qapp):
        from metatv.gui.monitored_series_dialog import MonitoredSeriesDialog
        dlg = MonitoredSeriesDialog(_FakeConfig())
        assert len(self._rows(dlg)) == 1, "a single empty-state row"

    def test_stop_removes_entry_refreshes_and_emits_changed(self, qapp):
        from metatv.gui.monitored_series_dialog import MonitoredSeriesDialog
        cfg = self._cfg(2)
        dlg = MonitoredSeriesDialog(cfg)
        changed: list[bool] = []
        dlg.changed.connect(lambda: changed.append(True))

        dlg._stop("ch0")

        assert not cfg.is_series_monitored("ch0"), "stopped series must be removed"
        assert cfg.is_series_monitored("ch1"), "other series must remain"
        assert changed, "changed must emit so the host refreshes its views"
        assert len(self._rows(dlg)) == 1, "list refreshes to the remaining series"
