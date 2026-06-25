"""Behavioral tests for the three EPG-refresh-cluster improvements.

Part 1: Periodic refresh scheduler on EpgManager.
Part 2: 'auto' self-tuning interval in needs_refresh + epg_auto_delta math.
Part 3: Indeterminate ↔ determinate progress bar switching in NotificationCard.

All DB-backed tests use a file-backed Database (NOT :memory:).
"""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.database import Database, ProviderDB
from metatv.core.epg_manager import EpgManager
from metatv.core.epg_utils import (
    EPG_AUTO_MAX_DELTA,
    EPG_AUTO_MIN_DELTA,
    EPG_INTERVAL_CHOICES,
    epg_auto_delta,
    now_utc,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    """Process-wide QApplication for headless Qt widget tests."""
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def db(tmp_path):
    """File-backed Database with tables created (avoids :memory: pool isolation)."""
    path = tmp_path / "test.db"
    database = Database(f"sqlite:///{path}")
    database.create_tables()
    yield database
    database.engine.dispose()


def _add_provider(session, pid, *, is_active=True, epg_url="http://e/xmltv.php",
                  epg_enabled=True, epg_data_end=None, epg_last_fetched=None,
                  epg_data_start=None, epg_refresh_interval="default",
                  epg_url_override=None):
    """Seed a ProviderDB row with EPG columns."""
    session.add(ProviderDB(
        id=pid, name=pid, type="xtream", url="http://e.com",
        username="u", password="p",
        is_active=is_active,
        epg_url=epg_url,
        epg_enabled=epg_enabled,
        epg_data_end=epg_data_end,
        epg_last_fetched=epg_last_fetched,
        epg_data_start=epg_data_start,
        epg_refresh_interval=epg_refresh_interval,
        epg_url_override=epg_url_override,
    ))
    session.flush()


def _make_manager(db, *, epg_default="auto"):
    """Create an EpgManager with a mock config using the given global default."""
    config = MagicMock()
    config.epg_auto_refresh = True
    config.epg_default_refresh_interval = epg_default
    return EpgManager(db, config, notifications=None)


# ===========================================================================
# PART 1 — Periodic scheduler
# ===========================================================================

def test_start_scheduler_creates_timer(qapp, db):
    """start_scheduler() creates and starts the QTimer."""
    manager = _make_manager(db)
    assert manager._scheduler_timer is None  # not started yet

    manager.start_scheduler()
    assert manager._scheduler_timer is not None
    assert manager._scheduler_timer.isActive()

    manager.stop_scheduler()
    manager._executor.shutdown(wait=False)


def test_start_scheduler_is_idempotent(qapp, db):
    """Calling start_scheduler() twice does not create a second timer."""
    manager = _make_manager(db)
    manager.start_scheduler()
    first_timer = manager._scheduler_timer
    manager.start_scheduler()
    assert manager._scheduler_timer is first_timer  # same object

    manager.stop_scheduler()
    manager._executor.shutdown(wait=False)


def test_stop_scheduler_stops_and_clears_timer(qapp, db):
    """stop_scheduler() stops the timer and sets _scheduler_timer to None."""
    manager = _make_manager(db)
    manager.start_scheduler()
    assert manager._scheduler_timer is not None

    manager.stop_scheduler()
    assert manager._scheduler_timer is None
    manager._executor.shutdown(wait=False)


def test_shutdown_stops_scheduler(qapp, db):
    """shutdown() calls stop_scheduler so the timer does not outlive the manager."""
    manager = _make_manager(db)
    manager.start_scheduler()
    assert manager._scheduler_timer is not None

    manager.shutdown()
    assert manager._scheduler_timer is None


def test_scheduler_interval_is_one_hour(db):
    """The scheduler ticks at the documented 1-hour interval."""
    assert EpgManager._SCHEDULER_INTERVAL_MS == 60 * 60 * 1_000


def test_scheduler_timer_calls_refresh_all_if_needed(qapp, db):
    """When the scheduler timer fires, refresh_all_if_needed() is called."""
    manager = _make_manager(db)
    with patch.object(manager, "refresh_all_if_needed") as mock_refresh:
        manager.start_scheduler()
        # Manually call the slot (simulates timer tick without waiting an hour)
        manager._scheduler_timer.timeout.emit()
        mock_refresh.assert_called_once()

    manager.stop_scheduler()
    manager._executor.shutdown(wait=False)


# ===========================================================================
# PART 2 — 'auto' self-tuning interval
# ===========================================================================

class TestEpgAutoDelta:
    """Unit tests for epg_auto_delta() math."""

    def test_two_day_depth_resolves_to_one_day(self):
        """A 2-day feed → half = 1 day (within [6h, 7d] clamp)."""
        now = now_utc()
        start = now - timedelta(days=2)
        end = now
        delta = epg_auto_delta(start, end)
        assert delta == timedelta(days=1)

    def test_seven_day_depth_resolves_to_three_and_a_half_days(self):
        """A 7-day feed → half = 3.5 days (within clamp)."""
        now = now_utc()
        start = now
        end = now + timedelta(days=7)
        delta = epg_auto_delta(start, end)
        assert delta == timedelta(hours=84)  # 3.5 * 24

    def test_short_feed_clamped_to_six_hours(self):
        """A 4-hour feed → half = 2h, clamped up to 6h minimum."""
        now = now_utc()
        start = now
        end = now + timedelta(hours=4)
        delta = epg_auto_delta(start, end)
        assert delta == EPG_AUTO_MIN_DELTA  # 6 hours

    def test_long_feed_clamped_to_seven_days(self):
        """A 30-day feed → half = 15 days, clamped down to 7 days maximum."""
        now = now_utc()
        start = now
        end = now + timedelta(days=30)
        delta = epg_auto_delta(start, end)
        assert delta == EPG_AUTO_MAX_DELTA  # 7 days

    def test_none_depth_returns_one_day_fallback(self):
        """No depth info → fallback of 1 day (avoid hammering on first fetch)."""
        delta = epg_auto_delta(None, None)
        assert delta == timedelta(days=1)

    def test_none_start_returns_one_day_fallback(self):
        """Only epg_data_end known → fallback of 1 day."""
        delta = epg_auto_delta(None, now_utc())
        assert delta == timedelta(days=1)


class TestNeedsRefreshAutoInterval:
    """Integration tests for needs_refresh when effective interval = 'auto'."""

    def test_auto_two_day_feed_within_interval_returns_false(self, db):
        """Auto on a 2-day feed → 1-day delta; fetched 6h ago → no refresh.

        Feed: start = now-1d, end = now+1d → depth = 2 days → half = 1 day.
        Fetched 6h ago < 1 day → within interval → False.
        """
        now = now_utc()
        with db.session_scope() as session:
            _add_provider(session, "auto-within",
                          epg_last_fetched=now - timedelta(hours=6),
                          epg_data_start=now - timedelta(days=1),
                          epg_data_end=now + timedelta(days=1),  # guide valid: +1d ahead
                          epg_refresh_interval="auto")

        manager = _make_manager(db)
        with db.session_scope(commit=False) as s:
            p = s.query(ProviderDB).filter_by(id="auto-within").first()
            assert manager.needs_refresh(p) is False
        manager._executor.shutdown(wait=False)

    def test_auto_two_day_feed_past_interval_returns_true(self, db):
        """Auto on a 2-day feed → 1-day delta; fetched 25h ago → refresh needed.

        Feed: start = now-1d, end = now+1d → depth = 2 days → half = 1 day.
        Fetched 25h ago > 1 day → past interval → True.
        """
        now = now_utc()
        with db.session_scope() as session:
            _add_provider(session, "auto-past",
                          epg_last_fetched=now - timedelta(hours=25),
                          epg_data_start=now - timedelta(days=1),
                          epg_data_end=now + timedelta(days=1),  # guide still valid
                          epg_refresh_interval="auto")

        manager = _make_manager(db)
        with db.session_scope(commit=False) as s:
            p = s.query(ProviderDB).filter_by(id="auto-past").first()
            assert manager.needs_refresh(p) is True
        manager._executor.shutdown(wait=False)

    def test_auto_expired_guide_returns_true_before_interval(self, db):
        """Auto: expiry floor fires even if within computed delta."""
        now = now_utc()
        with db.session_scope() as session:
            # 2-day feed → 1-day delta; fetched only 6h ago BUT guide already ended
            _add_provider(session, "auto-expiry",
                          epg_last_fetched=now - timedelta(hours=6),
                          epg_data_start=now - timedelta(days=2),
                          epg_data_end=now - timedelta(hours=1),  # guide expired
                          epg_refresh_interval="auto")

        manager = _make_manager(db)
        with db.session_scope(commit=False) as s:
            p = s.query(ProviderDB).filter_by(id="auto-expiry").first()
            assert manager.needs_refresh(p) is True, (
                "Expiry floor must fire under Auto even within the computed delta"
            )
        manager._executor.shutdown(wait=False)

    def test_auto_via_global_default_resolves_correctly(self, db):
        """A provider with per-source='default' inherits the global 'auto' default.

        Feed: start = now, end = now+4d → depth = 4 days → half = 2 days.
        Fetched 3 days ago > 2-day auto delta → must refresh.
        """
        now = now_utc()
        with db.session_scope() as session:
            # 4-day feed → 2-day delta; fetched 3 days ago → should refresh
            _add_provider(session, "auto-global",
                          epg_last_fetched=now - timedelta(days=3),
                          epg_data_start=now,
                          epg_data_end=now + timedelta(days=4),  # guide still ahead
                          epg_refresh_interval="default")

        # Global default = "auto"
        manager = _make_manager(db, epg_default="auto")
        with db.session_scope(commit=False) as s:
            p = s.query(ProviderDB).filter_by(id="auto-global").first()
            assert manager.needs_refresh(p) is True, (
                "3 days > 2-day auto delta → must refresh"
            )
        manager._executor.shutdown(wait=False)


def test_auto_appears_in_epg_interval_choices():
    """EPG_INTERVAL_CHOICES includes the 'auto' sentinel."""
    values = [v for v, _ in EPG_INTERVAL_CHOICES]
    assert "auto" in values, "'auto' must be listed in EPG_INTERVAL_CHOICES"


def test_auto_is_first_choice():
    """'auto' is the first entry so it is naturally the default in dropdowns."""
    assert EPG_INTERVAL_CHOICES[0][0] == "auto"


def test_auto_has_nonempty_label():
    """'auto' has a human-readable label."""
    for value, label in EPG_INTERVAL_CHOICES:
        if value == "auto":
            assert label  # non-empty
            return
    pytest.fail("'auto' not found in EPG_INTERVAL_CHOICES")


# ===========================================================================
# PART 3 — Indeterminate ↔ determinate progress bar
# ===========================================================================

class TestNotificationCardProgressBar:
    """Headless widget tests for the indeterminate ↔ determinate bar switch."""

    def _make_progress_notification(self, progress=None):
        """Build a minimal PROGRESS Notification object."""
        from metatv.core.notifications import Notification, NotificationType
        return Notification(
            title="EPG: test",
            type=NotificationType.PROGRESS,
            progress=progress,
            progress_current=None,
            progress_total=None,
            dismissible=False,
        )

    def _make_card(self, qapp, notification):
        from metatv.gui.notification_widget import NotificationCard
        config = MagicMock()
        card = NotificationCard(notification, config, parent=None)
        return card

    def test_initial_indeterminate_sets_range_0_0(self, qapp):
        """A PROGRESS notification with progress=None starts in busy/marquee mode."""
        notif = self._make_progress_notification(progress=None)
        card = self._make_card(qapp, notif)
        assert card.progress_bar.minimum() == 0
        assert card.progress_bar.maximum() == 0, (
            "progress=None → indeterminate; QProgressBar.maximum() must be 0"
        )

    def test_initial_determinate_sets_range_0_100(self, qapp):
        """A PROGRESS notification with a known fraction starts in determinate mode."""
        notif = self._make_progress_notification(progress=0.5)
        card = self._make_card(qapp, notif)
        assert card.progress_bar.maximum() == 100
        assert card.progress_bar.value() == 50

    def test_update_switches_indeterminate_to_determinate(self, qapp):
        """update_notification with progress=0.3 switches from busy to determinate."""
        notif = self._make_progress_notification(progress=None)
        card = self._make_card(qapp, notif)
        assert card.progress_bar.maximum() == 0  # starts indeterminate

        notif2 = self._make_progress_notification(progress=0.3)
        card.update_notification(notif2)
        assert card.progress_bar.maximum() == 100
        assert card.progress_bar.value() == 30

    def test_update_switches_determinate_to_indeterminate(self, qapp):
        """update_notification with progress=None switches back to busy mode."""
        notif = self._make_progress_notification(progress=0.5)
        card = self._make_card(qapp, notif)
        assert card.progress_bar.maximum() == 100  # starts determinate

        notif2 = self._make_progress_notification(progress=None)
        card.update_notification(notif2)
        assert card.progress_bar.maximum() == 0, (
            "Reverting to progress=None must re-enter indeterminate mode"
        )

    def test_determinate_update_does_not_regress(self, qapp):
        """Updating from one known fraction to another stays determinate."""
        notif = self._make_progress_notification(progress=0.1)
        card = self._make_card(qapp, notif)

        notif2 = self._make_progress_notification(progress=0.8)
        card.update_notification(notif2)
        assert card.progress_bar.maximum() == 100
        assert card.progress_bar.value() == 80
