"""Behavioral tests for the source-refresh step checklist.

Covers:
- ``_advance_steps``: message→step-status mapper marks the right step active /
  prior steps done as the progress percentage increases.
- ``_advance_epg_steps``: started/finished stages advance the EPG pair correctly.
- ``NotificationCard`` with steps renders a row per step with the right glyph.
- EPG steps absent when ``epg_enabled=False``, present when True.
- ``NotificationManager.set_steps`` updates the step list and notifies listeners.
"""

from __future__ import annotations

import pytest

from metatv.core.notifications import Notification, NotificationManager, NotificationType, StepStatus
from metatv.gui.main_window_providers import (
    _STEP_FETCH,
    _STEP_STORE,
    _STEP_PARSE,
    _STEP_EPG_DL,
    _STEP_EPG_PARSE,
    _advance_steps,
    _advance_epg_steps,
    _has_epg_steps,
    _make_steps,
)


# ── Helper ────────────────────────────────────────────────────────────────────

def _status(steps: list, label: str) -> StepStatus:
    """Return the status for *label* in *steps*."""
    return dict(steps)[label]


# ── _make_steps ───────────────────────────────────────────────────────────────

class TestMakeSteps:
    def test_base_steps_no_epg(self):
        steps = _make_steps(epg=False)
        labels = [lbl for lbl, _ in steps]
        assert labels == [_STEP_FETCH, _STEP_STORE, _STEP_PARSE]

    def test_epg_steps_appended_when_enabled(self):
        steps = _make_steps(epg=True)
        labels = [lbl for lbl, _ in steps]
        assert labels == [_STEP_FETCH, _STEP_STORE, _STEP_PARSE, _STEP_EPG_DL, _STEP_EPG_PARSE]

    def test_all_start_pending(self):
        for _, status in _make_steps(epg=True):
            assert status == StepStatus.PENDING

    def test_epg_false_has_no_epg_steps(self):
        steps = _make_steps(epg=False)
        assert not _has_epg_steps(steps)

    def test_epg_true_has_epg_steps(self):
        steps = _make_steps(epg=True)
        assert _has_epg_steps(steps)


# ── _advance_steps ────────────────────────────────────────────────────────────

class TestAdvanceSteps:
    """Tests execute the mapper and assert which step is active/done after each
    phase transition — these are the concrete regressions the mapper must not break.
    """

    def _base(self) -> list:
        return _make_steps(epg=False)

    def test_early_fetch_phase_fetch_is_active(self):
        steps = _advance_steps(self._base(), "Connecting…", 5)
        assert _status(steps, _STEP_FETCH) == StepStatus.ACTIVE
        assert _status(steps, _STEP_STORE) == StepStatus.PENDING
        assert _status(steps, _STEP_PARSE) == StepStatus.PENDING

    def test_mid_fetch_phase(self):
        steps = _advance_steps(self._base(), "Fetching VOD content…", 40)
        assert _status(steps, _STEP_FETCH) == StepStatus.ACTIVE
        assert _status(steps, _STEP_STORE) == StepStatus.PENDING

    def test_at_70_fetch_done_store_active(self):
        """pct=70 means channels fetched and storing just started."""
        steps = _advance_steps(self._base(), "Stored 10,000 channels", 70)
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.ACTIVE
        assert _status(steps, _STEP_PARSE) == StepStatus.PENDING

    def test_storing_batch_progress(self):
        """In-progress batches (pct 70-86) keep store active."""
        steps = _advance_steps(self._base(), "Storing channels (5,000/10,000)...", 80)
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.ACTIVE
        assert _status(steps, _STEP_PARSE) == StepStatus.PENDING

    def test_at_87_detecting_prefixes_store_done_parse_active(self):
        steps = _advance_steps(self._base(), "Detecting channel prefixes…", 87)
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.DONE
        assert _status(steps, _STEP_PARSE) == StepStatus.ACTIVE

    def test_categorizing_content_triggers_parse_active(self):
        steps = _advance_steps(self._base(), "Categorizing content (PPV/Events/Sports)…", 72)
        assert _status(steps, _STEP_PARSE) == StepStatus.ACTIVE

    def test_at_97_filter_stats_all_channel_steps_done(self):
        steps = _advance_steps(self._base(), "Updating filter statistics…", 97)
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.DONE
        assert _status(steps, _STEP_PARSE) == StepStatus.DONE

    def test_at_100_loaded_all_done(self):
        steps = _advance_steps(self._base(), "Loaded 10,000 channels", 100)
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.DONE
        assert _status(steps, _STEP_PARSE) == StepStatus.DONE

    def test_epg_steps_unaffected_by_channel_mapper(self):
        """EPG steps must remain PENDING while channel phases run."""
        steps = _make_steps(epg=True)
        steps = _advance_steps(steps, "Loaded 10,000 channels", 100)
        assert _status(steps, _STEP_EPG_DL) == StepStatus.PENDING
        assert _status(steps, _STEP_EPG_PARSE) == StepStatus.PENDING


# ── _advance_epg_steps ────────────────────────────────────────────────────────

class TestAdvanceEpgSteps:
    def _epg_steps(self) -> list:
        steps = _make_steps(epg=True)
        # Channel steps all done — simulate post-channel-load state.
        return _advance_steps(steps, "Loaded 10,000 channels", 100)

    def test_started_makes_dl_active(self):
        steps = _advance_epg_steps(self._epg_steps(), "started")
        assert _status(steps, _STEP_EPG_DL) == StepStatus.ACTIVE
        assert _status(steps, _STEP_EPG_PARSE) == StepStatus.PENDING

    def test_finished_marks_both_done(self):
        steps = _advance_epg_steps(self._epg_steps(), "started")
        steps = _advance_epg_steps(steps, "finished")
        assert _status(steps, _STEP_EPG_DL) == StepStatus.DONE
        assert _status(steps, _STEP_EPG_PARSE) == StepStatus.DONE

    def test_channel_steps_unaffected_by_epg_mapper(self):
        steps = _advance_epg_steps(self._epg_steps(), "finished")
        assert _status(steps, _STEP_FETCH) == StepStatus.DONE
        assert _status(steps, _STEP_STORE) == StepStatus.DONE
        assert _status(steps, _STEP_PARSE) == StepStatus.DONE


# ── NotificationManager.set_steps ────────────────────────────────────────────

class TestNotificationManagerSetSteps:
    def test_set_steps_updates_notification_and_notifies(self):
        """set_steps mutates the step list and fires listeners."""
        received: list[list] = []
        mgr = NotificationManager()
        mgr.add_listener(lambda notifs: received.append(notifs))

        notif_id = mgr.show_progress(
            title="Refreshing MySource",
            steps=_make_steps(epg=False),
        )
        received.clear()  # discard the show() notification

        new_steps = _advance_steps(_make_steps(epg=False), "Fetching VOD content…", 40)
        mgr.set_steps(notif_id, new_steps)

        # Listener must have fired
        assert len(received) == 1

        # The notification's step list must reflect the new state
        notif = mgr.notifications[0]
        assert notif.steps is not None
        assert _status(notif.steps, _STEP_FETCH) == StepStatus.ACTIVE

    def test_show_progress_without_steps_backward_compatible(self):
        """show_progress without steps= still creates a plain progress notification."""
        mgr = NotificationManager()
        notif_id = mgr.show_progress(title="Test", total=100)
        notif = mgr.notifications[0]
        assert notif.steps is None
        assert notif.progress == 0.0


# ── NotificationCard rendering ────────────────────────────────────────────────

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


class TestNotificationCardSteps:
    """Tests construct NotificationCard directly and assert widget state.

    The card is the main-thread-only half — this is what regressions affect.
    """

    def _make_card(self, qapp, steps):
        from PyQt6.QtWidgets import QWidget
        from metatv.core.config import Config
        from metatv.gui.notification_widget import NotificationCard

        notif = Notification(
            title="Refreshing MySource",
            type=NotificationType.PROGRESS,
            steps=steps,
        )
        parent = QWidget()
        card = NotificationCard(notif, Config(), parent)
        card._parent_keepalive = parent
        return card

    def test_step_rows_created_for_each_step(self, qapp):
        """One _StepRow widget per step label."""
        steps = _make_steps(epg=False)
        card = self._make_card(qapp, steps)
        assert len(card._step_rows) == 3  # FETCH, STORE, PARSE

    def test_pending_step_has_pending_glyph(self, qapp):
        """A PENDING step row carries the migration_pending_icon glyph."""
        from metatv.gui import icons as _icons
        steps = _make_steps(epg=False)
        card = self._make_card(qapp, steps)
        glyph = card._step_rows[0]._glyph.text()
        assert glyph == _icons.migration_pending_icon

    def test_active_step_has_progress_glyph(self, qapp):
        """An ACTIVE step row carries the notification_progress_icon glyph."""
        from metatv.gui import icons as _icons
        steps = _advance_steps(_make_steps(epg=False), "Connecting…", 5)
        card = self._make_card(qapp, steps)
        # Step 0 = FETCH = ACTIVE at pct 5
        assert card._step_rows[0]._glyph.text() == _icons.notification_progress_icon

    def test_done_step_has_done_glyph(self, qapp):
        """A DONE step row carries the migration_done_icon glyph."""
        from metatv.gui import icons as _icons
        steps = _advance_steps(_make_steps(epg=False), "Stored 10,000 channels", 70)
        card = self._make_card(qapp, steps)
        # Step 0 = FETCH = DONE at pct 70 (in_storing → True)
        assert card._step_rows[0]._glyph.text() == _icons.migration_done_icon

    def test_no_steps_card_has_progress_bar_not_step_rows(self, qapp):
        """A card without steps renders the classic progress bar."""
        from PyQt6.QtWidgets import QWidget
        from metatv.core.config import Config
        from metatv.gui.notification_widget import NotificationCard

        notif = Notification(
            title="Plain progress",
            type=NotificationType.PROGRESS,
        )
        parent = QWidget()
        card = NotificationCard(notif, Config(), parent)

        assert hasattr(card, 'progress_bar'), "classic card must have a progress_bar"
        assert len(card._step_rows) == 0

    def test_epg_steps_present_when_epg_true(self, qapp):
        """Five step rows when EPG is enabled."""
        steps = _make_steps(epg=True)
        card = self._make_card(qapp, steps)
        assert len(card._step_rows) == 5

    def test_epg_steps_absent_when_epg_false(self, qapp):
        """Three step rows when EPG is disabled."""
        steps = _make_steps(epg=False)
        card = self._make_card(qapp, steps)
        assert len(card._step_rows) == 3

    def test_update_notification_advances_row_glyph(self, qapp):
        """update_notification transitions a PENDING row to ACTIVE in-place."""
        from metatv.gui import icons as _icons

        steps = _make_steps(epg=False)
        card = self._make_card(qapp, steps)

        # Initially the FETCH row is PENDING
        assert card._step_rows[0]._glyph.text() == _icons.migration_pending_icon

        # Simulate progress update
        new_steps = _advance_steps(steps, "Connecting…", 5)
        card.notification.steps = new_steps
        card.update_notification(card.notification)

        # Now FETCH should show the ACTIVE (progress) glyph
        assert card._step_rows[0]._glyph.text() == _icons.notification_progress_icon

    def test_update_notification_rebuilds_rows_on_count_change(self, qapp):
        """Adding EPG steps mid-refresh rebuilds the row list."""
        steps_3 = _make_steps(epg=False)
        card = self._make_card(qapp, steps_3)
        assert len(card._step_rows) == 3

        steps_5 = _make_steps(epg=True)
        card.notification.steps = steps_5
        card.update_notification(card.notification)
        assert len(card._step_rows) == 5
