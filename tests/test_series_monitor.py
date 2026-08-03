"""Behavioral tests for the series monitor feature.

Covers:
- Config helpers: add/remove/is_monitored/update/clear_unseen round-trip.
- SeriesMonitorManager._worker_check_entries detects a delta and emits _notify_new.
- SeriesMonitorManager._on_new_episodes updates config and fires new_episodes_found.
- No notification or config change when episode count is unchanged (delta == 0).
- channel_menu: monitor_series action applies only to series, not live/movie.

The monitored-series RENDER surface now lives in the Watch Alerts section (see
tests/test_watch_alerts_consolidation.py) — NewEpisodesSection was retired.
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


def _make_provider_db(session, provider_id: str = "p1", name: str = "Test Provider"):
    """Insert a minimal ProviderDB row."""
    from metatv.core.database import ProviderDB
    provider = ProviderDB(
        id=provider_id,
        name=name,
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
                          source_id: str = "s1", content_key: str | None = None):
    """Insert a minimal series ChannelDB row."""
    from metatv.core.database import ChannelDB
    ch = ChannelDB(
        id=channel_id,
        source_id=source_id,
        provider_id=provider_id,
        name="Test Series",
        media_type="series",
        content_key=content_key,
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
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )

            entries = cfg.get_monitored_for_provider("p1")
            manager._worker_check_entries(entries)

            # Process pending signals
            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        assert len(notify_args) == 1, f"Expected 1 notification, got: {notify_args}"
        cid, delta, title, payload = notify_args[0]
        assert cid == "ch1"
        assert delta == 5, f"Expected delta=5 (15-10), got {delta}"
        assert payload["baselines"]["p1|s1"] == 15
        assert payload["grown_provider_names"] == ["Test Provider"]
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
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )

            entries = cfg.get_monitored_for_provider("p1")
            manager._worker_check_entries(entries)

            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        # Should still emit (delta=0 branch) but with delta=0
        assert len(notify_args) == 1
        _, delta, _, payload = notify_args[0]
        assert delta == 0
        assert payload["baselines"]["p1|s1"] == 10
        assert payload["grown_provider_names"] == []

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
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )

            manager._worker_check_entries(cfg.get_monitored_for_provider("p1"))

            if QCoreApplication.instance():
                QCoreApplication.processEvents()

        # Establishes the baseline (delta=0) — must NOT report 42 "new" episodes.
        assert len(notify_args) == 1
        _cid, delta, _title, payload = notify_args[0]
        assert delta == 0, f"None-baseline must establish (delta 0), got {delta}"
        assert payload["baselines"]["p1|s1"] == 42

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
        payload = {"baselines": {"p1": 15}, "grown_provider_names": ["Test Provider"]}
        manager._on_new_episodes("ch1", 5, "Growing Series", payload)

        # Config was updated
        entries = cfg.get_monitored_series()
        assert len(entries) == 1
        entry = entries[0]
        assert entry["baselines"]["p1"] == 15, \
            f"baseline should be 15, got {entry.get('baselines')}"
        assert entry["unseen_new"] == 5, \
            f"unseen_new should be 5, got {entry['unseen_new']}"
        assert entry["growth_providers"] == ["Test Provider"]
        assert entry["last_checked"] is not None

        # Notification was shown and names the provider that grew
        assert notif_mock.show.called, "NotificationManager.show() should have been called"
        call_kwargs = notif_mock.show.call_args
        assert "new episode" in str(call_kwargs).lower()
        assert "Test Provider" in str(call_kwargs)

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

        manager._on_new_episodes(
            "ch1", 0, "Stable Series",
            {"baselines": {"p1": 10}, "grown_provider_names": []},
        )

        # Baseline updated, last_checked set
        entry = cfg.get_monitored_series()[0]
        assert entry["baselines"]["p1"] == 10
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
        manager._on_new_episodes(
            "ch1", 3, "Accumulating Series",
            {"baselines": {"p1": 15}, "grown_provider_names": ["Test Provider"]},
        )

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 5, \
            f"Expected 2+3=5 unseen, got {entry['unseen_new']}"
        assert entry["baselines"]["p1"] == 15

        manager.shutdown()


# ===========================================================================
# Part 3: Movies & Series series rows live in the Watch Alerts section now — see
# tests/test_watch_alerts_consolidation.py (NewEpisodesSection was retired).
# ===========================================================================


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
        # Icon-only rail: state is conveyed via :checked + tooltip, not button text.
        assert not bar.monitor_button.isChecked(), \
            "A not-yet-monitored series must show the Alert button unchecked"
        assert "Alert me" in bar.monitor_button.toolTip()

    def test_monitor_button_reflects_monitored_state(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=True, is_monitored=True)
        assert bar.monitor_button.isChecked(), \
            "An alerting series must show the Alert button checked"
        assert "Stop" in bar.monitor_button.toolTip()

    def test_monitor_click_toggles_and_emits(self, qapp):
        bar = self._bar()
        bar.set_monitorable(is_series=True, is_monitored=False)
        emitted: list[bool] = []
        bar.monitor_clicked.connect(lambda: emitted.append(True))
        bar._on_monitor_clicked()
        assert bar._is_monitored is True
        assert bar.monitor_button.isChecked()
        assert emitted, "monitor_clicked must emit on toggle"


# ===========================================================================
# Part 6: The see-all / stop-monitoring surface moved into ManageVodAlertsDialog
# (the "Series — new-episode alerts" section) — see
# tests/test_watch_alerts_consolidation.py.  MonitoredSeriesDialog was retired.
# ===========================================================================


# ===========================================================================
# Part 7: Per-provider baseline migration (legacy scalar -> baselines dict)
# ===========================================================================

class TestBaselineMigration:
    """normalize_monitored_entry / Config.get_monitored_series migrate a
    legacy single-provider ``baseline_episode_count`` entry to the
    per-provider ``baselines`` shape — old key tolerated, migrated shape
    written back on first read."""

    def test_normalize_migrates_legacy_scalar_baseline(self):
        from metatv.core.series_monitor import normalize_monitored_entry

        entry = {
            "series_channel_id": "ch1", "provider_id": "p1", "source_id": "s1",
            "title": "Old Shape", "baseline_episode_count": 7,
            "unseen_new": 0, "last_checked": None,
        }
        migrated = normalize_monitored_entry(entry)
        assert migrated["baselines"] == {"p1|s1": 7}
        assert migrated is not entry, "migration must not mutate the original dict"
        assert entry["baseline_episode_count"] == 7, "old key tolerated, left intact"

    def test_normalize_tolerates_none_legacy_baseline(self):
        """A never-established legacy baseline (None) migrates to {} — NOT to
        {provider_id: None}, which would look like an established zero-count
        baseline and mis-trigger on the whole back-catalog."""
        from metatv.core.series_monitor import normalize_monitored_entry

        entry = {"series_channel_id": "ch1", "provider_id": "p1",
                  "baseline_episode_count": None}
        migrated = normalize_monitored_entry(entry)
        assert migrated["baselines"] == {}

    def test_normalize_passthrough_when_already_migrated(self):
        """An entry that already carries baselines is returned unchanged (same
        object) — no needless copy on every read."""
        from metatv.core.series_monitor import normalize_monitored_entry

        entry = {"series_channel_id": "ch1",
                 "baselines": {"p1|s1": 3, "p2|s9": 4}}
        migrated = normalize_monitored_entry(entry)
        assert migrated is entry

    def test_config_get_monitored_series_migrates_and_persists(self, tmp_path):
        """Config.get_monitored_series() migrates a legacy entry on first read
        AND writes the migrated shape back to the stored list — not just the
        returned copy — so a second read sees the new shape without a second
        migration pass."""
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [{
            "series_channel_id": "ch1", "provider_id": "p1", "source_id": "s1",
            "title": "Legacy Entry", "baseline_episode_count": 9,
            "unseen_new": 0, "last_checked": None,
        }]

        result = cfg.get_monitored_series()
        assert result[0]["baselines"] == {"p1|s1": 9}
        # Written back to the raw stored field, not just the returned copy.
        assert cfg.monitored_series[0]["baselines"] == {"p1|s1": 9}

    def test_config_get_monitored_for_provider_matches_baseline_providers(self, tmp_path):
        """get_monitored_for_provider matches both the PRIMARY provider_id and
        any provider recorded in the entry's baselines dict (a mirror discovered
        by a prior check_all pass).

        Baseline keys are now ``provider|source``, so this cannot be a plain
        membership test — it has to compare the provider HALF of each key.
        """
        from metatv.core.config import Config

        cfg = Config(config_dir=tmp_path / "cfg")
        cfg.monitored_series = [{
            "series_channel_id": "ch1", "provider_id": "p1", "source_id": "s1",
            "title": "Mirrored", "baselines": {"p1|s1": 10, "p2|s9": 10},
            "unseen_new": 0, "last_checked": None,
        }]

        assert len(cfg.get_monitored_for_provider("p1")) == 1
        assert len(cfg.get_monitored_for_provider("p2")) == 1, \
            "a provider known only via baselines (not the primary) must still match"
        assert len(cfg.get_monitored_for_provider("p3")) == 0

    def test_normalize_drops_unattributable_sibling_baselines(self):
        """Provider-keyed → mirror-keyed: only the PRIMARY provider's baseline
        survives, because it is the only one whose source_id the entry records.

        A sibling provider's count cannot be tied to a specific listing, and
        keeping it under a guessed key would preserve exactly the ambiguity the
        migration exists to remove. It re-establishes silently on the next check
        (the ``prev is None`` path never alerts), so the cost is one quiet cycle.
        ``unseen_new`` is zeroed rather than clamped because a count produced by
        the collision is proven corrupt, not merely implausible.
        """
        from metatv.core.series_monitor import normalize_monitored_entry

        entry = {
            "series_channel_id": "ch1", "provider_id": "p1", "source_id": "s1",
            "title": "Mirrored", "baselines": {"p1": 15, "p2": 8},
            "unseen_new": 23, "growth_providers": ["Some Source"],
        }
        migrated = normalize_monitored_entry(entry)

        assert migrated["baselines"] == {"p1|s1": 15}
        assert migrated["unseen_new"] == 0
        assert migrated["growth_providers"] == []
        assert entry["baselines"] == {"p1": 15, "p2": 8}, "original left intact"

    def test_normalize_is_idempotent_on_migrated_entries(self):
        """A second pass over an already-migrated entry must not re-zero
        unseen_new — otherwise every config read would wipe legitimate new-episode
        counts accumulated since the migration."""
        from metatv.core.series_monitor import normalize_monitored_entry

        entry = {
            "series_channel_id": "ch1", "provider_id": "p1", "source_id": "s1",
            "baselines": {"p1|s1": 15}, "unseen_new": 4,
        }
        migrated = normalize_monitored_entry(entry)

        assert migrated is entry, "already-migrated entry returned unchanged"
        assert migrated["unseen_new"] == 4


# ===========================================================================
# Part 8: New-episode detection when only ONE of several providers grows
# ===========================================================================

class TestPerProviderMirrorDetection:
    """A series monitored via its PRIMARY provider also detects growth landing
    on any OTHER provider mirroring the same content (content_key sibling) —
    the core behavior of the per-provider-baselines upgrade."""

    def test_same_provider_mirrors_do_not_manufacture_growth(self, tmp_path):
        """Two listings on ONE provider sharing a content_key each keep their
        own baseline — the owner-reported false-alert bug (2026-08-02).

        ``content_key`` is a generous identity, so one provider routinely
        carries several listings that collapse to it. Under the old
        provider-only baseline key, every one of those listings wrote to the
        same slot AND was compared against the same stale ``prev``: here s2's
        16 episodes measured against s1's baseline of 8 reported "+8 new
        episodes" on a series where nothing had changed, and repeated it every
        launch until the clamp pinned it to the provider's TOTAL episode count
        ("Rick And Morty +132 eps").

        Pre-fix this fails with delta == 8. Post-fix s1 is unchanged (8 vs 8)
        and s2 is a brand-new mirror, so it establishes silently — the
        ``prev is None`` path never alerts on a back-catalogue.
        """
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Fallout",
            "baselines": {"p1|s1": 8},
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat (Ottcst)")
            # Both listings live on the SAME provider — the case the old key
            # could not represent.
            _make_series_channel(session, "ch1", "p1", "s1", content_key="fallout|series")
            _make_series_channel(session, "ch2", "p1", "s2", content_key="fallout|series")

        class _FakePlugin:
            async def fetch_series_info(self, provider, source_id):
                # A different listing of the same show, with its own catalogue.
                count = 16 if source_id == "s2" else 8
                return {"episodes": {"1": [{}] * count}}

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider", return_value=_FakePlugin()):
            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )
            manager._worker_check_entries(cfg.get_monitored_series())
            if QCoreApplication.instance():
                QCoreApplication.processEvents()
            manager.shutdown()

        assert len(notify_args) == 1, f"expected exactly one notify, got {notify_args}"
        _cid, delta, _title, payload = notify_args[0]
        assert delta == 0, (
            f"a second listing on the same provider was counted as {delta} new "
            f"episodes — this is the fabricated-alert bug; baselines="
            f"{payload['baselines']}"
        )
        assert payload["baselines"] == {"p1|s1": 8, "p1|s2": 16}, (
            "each listing on the provider must hold its own baseline rather "
            "than overwriting a single per-provider slot"
        )

    def test_same_provider_mirror_growth_is_still_detected(self, tmp_path):
        """Guard against over-correcting: once a same-provider mirror HAS a
        baseline, real growth on it must still alert."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Fallout",
            "baselines": {"p1|s1": 8, "p1|s2": 16},
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat (Ottcst)")
            _make_series_channel(session, "ch1", "p1", "s1", content_key="fallout|series")
            _make_series_channel(session, "ch2", "p1", "s2", content_key="fallout|series")

        class _FakePlugin:
            async def fetch_series_info(self, provider, source_id):
                count = 19 if source_id == "s2" else 8   # s2 gained 3
                return {"episodes": {"1": [{}] * count}}

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider", return_value=_FakePlugin()):
            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )
            manager._worker_check_entries(cfg.get_monitored_series())
            if QCoreApplication.instance():
                QCoreApplication.processEvents()
            manager.shutdown()

        _cid, delta, _title, payload = notify_args[0]
        assert delta == 3, f"real growth on a same-provider mirror missed, got {delta}"
        assert payload["baselines"] == {"p1|s1": 8, "p1|s2": 19}
        # One provider grew, so its name appears ONCE even though the growth
        # came from a specific listing among several it carries.
        assert payload["grown_provider_names"] == ["ProSat (Ottcst)"]

    def test_growth_on_sibling_provider_triggers_primary_unaffected(self, tmp_path):
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Mirrored Show",
            "baselines": {"p1|s1": 10, "p2|s2": 10},
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat")
            _make_provider_db(session, "p2", name="IPTV Ninja")
            _make_series_channel(session, "ch1", "p1", "s1", content_key="mirrored show|series")
            _make_series_channel(session, "ch2", "p2", "s2", content_key="mirrored show|series")

        class _FakePlugin:
            async def fetch_series_info(self, provider, source_id):
                if source_id == "s2":
                    return {"episodes": {"1": [{}] * 12}}  # p2 grew 10 -> 12
                return {"episodes": {"1": [{}] * 10}}       # p1 unchanged

        notify_args: list[tuple] = []

        with patch("metatv.providers.factory.get_provider", return_value=_FakePlugin()):
            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )
            manager._worker_check_entries(cfg.get_monitored_series())
            if QCoreApplication.instance():
                QCoreApplication.processEvents()
            manager.shutdown()

        assert len(notify_args) == 1, f"expected exactly one notify, got {notify_args}"
        cid, delta, title, payload = notify_args[0]
        assert cid == "ch1"
        assert delta == 2, f"only p2's +2 should count toward the total, got delta={delta}"
        assert payload["baselines"] == {"p1|s1": 10, "p2|s2": 12}
        assert payload["grown_provider_names"] == ["IPTV Ninja"], \
            "the toast/tooltip attribution must name the provider that actually grew"

    def test_hidden_sibling_provider_is_never_checked(self, tmp_path):
        """A content_key sibling on a DISABLED provider is excluded (the same
        absolute gate as get_content_key_siblings' other callers) — its growth
        must never trigger an alert."""
        from PyQt6.QtCore import QCoreApplication
        from metatv.core.database import ProviderDB
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1",
            "source_id": "s1",
            "provider_id": "p1",
            "title": "Mirrored Show",
            "baselines": {"p1|s1": 10, "p2|s2": 10},
            "unseen_new": 0,
            "last_checked": None,
        })

        with db.session_scope() as session:
            _make_provider_db(session, "p1", name="ProSat")
            disabled = ProviderDB(
                id="p2", name="Disabled Source", type="xtream",
                url="http://h", urls='[{"url": "http://h", "primary": true}]',
                username="u", password="p", is_active=False,
            )
            session.add(disabled)
            _make_series_channel(session, "ch1", "p1", "s1", content_key="mirrored show|series")
            _make_series_channel(session, "ch2", "p2", "s2", content_key="mirrored show|series")

        class _FakePlugin:
            async def fetch_series_info(self, provider, source_id):
                # p2 (disabled) claims growth — must never be fetched at all.
                return {"episodes": {"1": [{}] * (99 if source_id == "s2" else 10)}}

        notify_args: list[tuple] = []
        with patch("metatv.providers.factory.get_provider", return_value=_FakePlugin()):
            manager = SeriesMonitorManager(db, cfg, notifications=None)
            manager._notify_new.connect(
                lambda cid, delta, title, payload: notify_args.append((cid, delta, title, payload))
            )
            manager._worker_check_entries(cfg.get_monitored_series())
            if QCoreApplication.instance():
                QCoreApplication.processEvents()
            manager.shutdown()

        assert len(notify_args) == 1
        _, delta, _, payload = notify_args[0]
        assert delta == 0, "the disabled sibling's growth must never surface"
        # p2's baseline stays at its pre-existing value (10) — proof it was
        # never fetched/re-baselined while hidden (the fake plugin would have
        # returned 99, which must never make it into the payload).
        assert payload["baselines"].get("p2|s2") == 10, \
            f"a hidden provider must never be (re)checked; got {payload['baselines']}"


# ===========================================================================
# Part 9: Drill-in clears the sticky unseen badge
# ===========================================================================

class TestDrillInClearsUnseen:
    """Opening a monitored series' season/episode tree (main_window_series.py
    on_series_loaded, success path) clears its sticky 'unseen' badge — the
    same effect as the explicit 'Mark seen' action — via config.clear_unseen.
    """

    def _host(self, config, current_series):
        from metatv.gui.main_window_series import _SeriesMixin

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.config = config
        host.current_series = current_series
        host.notification_manager = MagicMock()
        host.active_threads = []
        host.status_bar = MagicMock()
        host.sender = lambda: SimpleNamespace()  # no notification_id -> skip dismiss branch
        host.switch_to_series_view = MagicMock()
        # Composite chokepoint (Wave 3): a drill-in clears the badge everywhere
        # (Watch Alerts section AND Watch Queue's Alerts Matched matched-series
        # rows), not just the narrower _refresh_vod_alerts_section.
        host._refresh_alert_visibility = MagicMock()
        return host

    def test_success_clears_unseen_for_monitored_series(self, qapp):
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1", "source_id": "s1", "provider_id": "p1",
            "title": "Show", "baselines": {"p1": 10}, "unseen_new": 3,
            "last_checked": None,
        })
        channel = SimpleNamespace(id="ch1", name="Show")
        host = self._host(cfg, channel)

        host.on_series_loaded(True, "2 seasons", {"seasons": []})

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 0
        host._refresh_alert_visibility.assert_called_once()
        host.switch_to_series_view.assert_called_once()

    def test_not_monitored_series_is_noop(self, qapp):
        """Drilling into a series that isn't monitored never touches config
        (the is_series_monitored gate) but still opens normally."""
        cfg = _FakeConfig()
        channel = SimpleNamespace(id="ch-unmonitored", name="Other Show")
        host = self._host(cfg, channel)

        host.on_series_loaded(True, "1 season", {"seasons": []})

        assert cfg.get_monitored_series() == []
        host._refresh_alert_visibility.assert_not_called()
        host.switch_to_series_view.assert_called_once()

    def test_failed_load_does_not_clear_unseen(self, qapp):
        """A failed load never shows the tree, so the badge must survive."""
        cfg = _FakeConfig()
        cfg.add_monitored_series({
            "series_channel_id": "ch1", "source_id": "s1", "provider_id": "p1",
            "title": "Show", "baselines": {"p1": 10}, "unseen_new": 3,
            "last_checked": None,
        })
        channel = SimpleNamespace(id="ch1", name="Show")
        host = self._host(cfg, channel)

        host.on_series_loaded(False, "network error", None)

        entry = cfg.get_monitored_series()[0]
        assert entry["unseen_new"] == 3, "a failed load must not clear the badge"
        host.switch_to_series_view.assert_not_called()


# ===========================================================================
# Part 10: Recurring recheck timer — 0 = off
# ===========================================================================

class TestRecurringScheduler:
    """SeriesMonitorManager.start_scheduler arms a recurring QTimer per
    config.series_monitor_interval_minutes; 0 (or falsy) disables it."""

    def test_zero_interval_disables_timer(self, tmp_path, qapp):
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.series_monitor_interval_minutes = 0

        manager = SeriesMonitorManager(db, cfg, notifications=None)
        manager.start_scheduler()
        assert not manager._timer.isActive()
        manager.shutdown()

    def test_positive_interval_arms_timer(self, tmp_path, qapp):
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.series_monitor_interval_minutes = 30

        manager = SeriesMonitorManager(db, cfg, notifications=None)
        manager.start_scheduler()
        assert manager._timer.isActive()
        assert manager._timer.interval() == 30 * 60 * 1000
        manager.shutdown()

    def test_default_interval_is_sixty_minutes(self, tmp_path, qapp):
        """A config stub that doesn't define the field at all falls back to 60."""
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()  # no series_monitor_interval_minutes attribute

        manager = SeriesMonitorManager(db, cfg, notifications=None)
        manager.start_scheduler()
        assert manager._timer.isActive()
        assert manager._timer.interval() == 60 * 60 * 1000
        manager.shutdown()

    def test_shutdown_stops_the_timer(self, tmp_path, qapp):
        from metatv.core.series_monitor import SeriesMonitorManager

        db = _make_file_backed_db(tmp_path)
        cfg = _FakeConfig()
        cfg.series_monitor_interval_minutes = 15

        manager = SeriesMonitorManager(db, cfg, notifications=None)
        manager.start_scheduler()
        assert manager._timer.isActive()
        manager.shutdown()
        assert not manager._timer.isActive()


# ===========================================================================
# Part 11: Ingestion parser warning for non-numeric episode-group keys
# ===========================================================================

class TestNonNumericSeasonKeyWarning:
    """provider_loader.SeriesLoadThread warns (once per series listing) when an
    episode-group key can't be mapped to a numeric season — those episodes are
    otherwise silently dropped.  Mirrors the ``--live`` dump's "NON-NUMERIC keys
    DROPPED" diagnostic at ingestion time, so the drop is greppable instead of
    an invisible season gap.

    Loguru doesn't route through stdlib ``logging`` by default, so pytest's
    ``caplog`` fixture can't see it — a temporary loguru sink achieves the same
    "capture the warning" goal.
    """

    def test_warns_once_for_nonnumeric_episode_group_keys(self, tmp_path, qapp):
        import asyncio
        from loguru import logger as _loguru_logger

        from metatv.core.database import Database
        from metatv.core.models import Provider
        from metatv.core.provider_loader import SeriesLoadThread

        class _FakePlugin:
            async def fetch_series_info(self, provider, series_id):
                return {
                    "info": {"name": "Weird Show"},
                    "seasons": [],
                    "episodes": {
                        "1": [{"id": "1", "episode_num": 1, "title": "a",
                               "container_extension": "mp4", "info": {}}],
                        "Temporada 2": [{"id": "2", "episode_num": 1, "title": "b",
                                          "container_extension": "mp4", "info": {}}],
                    },
                }

        db = Database(f"sqlite:///{tmp_path / 'warn.db'}")
        db.create_tables()

        messages: list[str] = []
        sink_id = _loguru_logger.add(
            lambda msg: messages.append(msg.record["message"]), level="WARNING"
        )
        try:
            provider = Provider(id="provW", name="W", type="xtream",
                                 url="http://h", username="u", password="p")
            with patch("metatv.core.provider_loader.get_provider", return_value=_FakePlugin()):
                thread = SeriesLoadThread(provider=provider, series_id="99",
                                          series_name="Weird Show", db=db)
                asyncio.run(thread.load_series())
        finally:
            _loguru_logger.remove(sink_id)
            db.close()

        warnings = [m for m in messages if "non-numeric" in m.lower()]
        assert len(warnings) == 1, f"expected exactly one warning, got: {messages}"
        assert "Temporada 2" in warnings[0], "the dropped key must be listed by name"
        assert "Weird Show" in warnings[0]
