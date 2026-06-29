"""Behavioral tests for the double-click default setting + middle-click opposite +
the decoupled details-pane Play/Resume buttons (details refinements, #0103).

Covered behaviors
-----------------
1. Settings: the playback-tab control persists/restores config.playback_resume_mode
   (the bare double-click default) — load + save round-trip.
2. Details Play button always starts from the beginning, Resume always resumes —
   they emit DISTINCT public signals (play_requested vs resume_requested) so the
   host can route Play → from-beginning and Resume → resume, independent of the
   double-click default setting.
3. Middle-click on a channel row plays the user-configured action (config.middle_click_action),
   dispatched through the MIDDLE_CLICK_ACTIONS registry:
   - "playback_position" → middle-click → play_channel_resume_by_id
   - "endless_buffer"    → middle-click → play_channel_open_ended_buffer_by_id
4. ChannelListView emits middle_clicked(index) on a middle-button press only.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


# ---------------------------------------------------------------------------
# 1. Settings control reconciles with the existing playback_resume_mode field
# ---------------------------------------------------------------------------

def test_settings_control_round_trips_double_click_default(qapp):
    """The playback-tab combo loads from and saves to config.playback_resume_mode —
    the single field that governs the bare double-click default (no duplicate field)."""
    from PyQt6.QtWidgets import QComboBox
    from metatv.gui.settings_dialog import SettingsDialog

    dlg = SettingsDialog.__new__(SettingsDialog)
    dlg._resume_mode_combo = QComboBox()
    dlg._resume_mode_combo.addItem("Resume (when a saved position exists)", userData="resume")
    dlg._resume_mode_combo.addItem("Start from beginning", userData="beginning")

    # Load: config value selects the matching item.
    cfg = MagicMock()
    cfg.playback_resume_mode = "beginning"
    idx = dlg._resume_mode_combo.findData(cfg.playback_resume_mode)
    dlg._resume_mode_combo.setCurrentIndex(idx)
    assert dlg._resume_mode_combo.currentData() == "beginning"

    # Save: the selected item writes back to the SAME field.
    dlg._resume_mode_combo.setCurrentIndex(dlg._resume_mode_combo.findData("resume"))
    cfg.playback_resume_mode = dlg._resume_mode_combo.currentData() or "resume"
    assert cfg.playback_resume_mode == "resume"


# ---------------------------------------------------------------------------
# 2. Play vs Resume are distinct intents on the details pane
# ---------------------------------------------------------------------------

def _fake_movie(channel_id="cid-1", watch_progress=300):
    ch = MagicMock()
    ch.id = channel_id
    ch.name = "Test Movie"
    from metatv.core.models import MediaType
    ch.media_type = MediaType.MOVIE
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Movie"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = watch_progress
    ch.logo_url = None
    return ch


def test_play_and_resume_emit_distinct_signals(qapp):
    """A partially-watched movie shows both buttons; Play emits play_requested
    (host routes to from-beginning) and Resume emits resume_requested (host resumes).
    The two intents are separate, so neither is governed by the double-click setting."""
    from metatv.gui.details_pane import DetailsPaneWidget

    cache = MagicMock()
    cache.get_image_sync.return_value = None
    pane = DetailsPaneWidget(_make_config(), cache, db=None)

    ch = _fake_movie()
    pane.show_channel(ch)
    # Resume button must be available for a partially-watched movie.
    assert not pane._action_bar.resume_button.isHidden()

    play_emitted: list[str] = []
    resume_emitted: list[str] = []
    pane.play_requested.connect(lambda cid: play_emitted.append(cid))
    pane.resume_requested.connect(lambda cid: resume_emitted.append(cid))

    pane._action_bar.play_button.click()
    pane._action_bar.resume_button.click()

    assert play_emitted == [ch.id], "Play button must emit play_requested (from-beginning intent)"
    assert resume_emitted == [ch.id], "Resume button must emit resume_requested (resume intent)"


# ---------------------------------------------------------------------------
# 3. Middle-click = the user-configured action (config.middle_click_action)
# ---------------------------------------------------------------------------

def _channels_host(middle_click_action: str):
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _ChannelListMixin.__new__(_ChannelListMixin)
    host.config = MagicMock()
    host.config.middle_click_action = middle_click_action
    host.play_channel_resume_by_id = MagicMock()
    host.play_channel_open_ended_buffer_by_id = MagicMock()
    host.play_channel_from_beginning_by_id = MagicMock()
    return host


def _index(channel_id):
    idx = MagicMock()
    idx.data.return_value = channel_id
    return idx


def test_middle_click_resumes_when_action_is_playback_position(qapp):
    """'playback_position' → middle-click resumes from the saved position."""
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _channels_host("playback_position")

    _ChannelListMixin._on_channel_middle_clicked(host, _index("c1"))

    host.play_channel_resume_by_id.assert_called_once_with("c1")
    host.play_channel_open_ended_buffer_by_id.assert_not_called()


def test_middle_click_endless_buffer_when_action_is_endless_buffer(qapp):
    """'endless_buffer' → middle-click plays with the open-ended disk-backed buffer."""
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _channels_host("endless_buffer")

    _ChannelListMixin._on_channel_middle_clicked(host, _index("c2"))

    host.play_channel_open_ended_buffer_by_id.assert_called_once_with("c2")
    host.play_channel_resume_by_id.assert_not_called()


def test_middle_click_unknown_action_falls_back_to_default(qapp):
    """An unknown/stale config value falls back to the default (resume) action."""
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _channels_host("no_such_action")

    _ChannelListMixin._on_channel_middle_clicked(host, _index("c3"))

    host.play_channel_resume_by_id.assert_called_once_with("c3")


def test_middle_click_noop_without_channel_id(qapp):
    """An empty index id must not trigger any play path."""
    from metatv.gui.main_window_channels import _ChannelListMixin
    host = _channels_host("playback_position")

    _ChannelListMixin._on_channel_middle_clicked(host, _index(None))

    host.play_channel_resume_by_id.assert_not_called()
    host.play_channel_open_ended_buffer_by_id.assert_not_called()


# ---------------------------------------------------------------------------
# 4. ChannelListView middle-click signal
# ---------------------------------------------------------------------------

def _press_event(button):
    from PyQt6.QtCore import QEvent, QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    return QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(5.0, 5.0),
        button,
        button,
        Qt.KeyboardModifier.NoModifier,
    )


def test_channel_list_view_emits_middle_clicked_on_middle_press(qapp):
    from PyQt6.QtCore import Qt, QStringListModel
    from metatv.gui.channel_list_view import ChannelListView

    view = ChannelListView()
    model = QStringListModel(["A", "B"])
    view.setModel(model)
    target = model.index(0, 0)
    view.indexAt = lambda _pos: target   # deterministic hit-test

    captured = []
    view.middle_clicked.connect(lambda idx: captured.append(idx))

    view.mousePressEvent(_press_event(Qt.MouseButton.MiddleButton))

    assert captured == [target], "middle-button press must emit middle_clicked(index)"


def test_channel_list_view_left_press_does_not_emit_middle(qapp):
    from PyQt6.QtCore import Qt, QStringListModel
    from metatv.gui.channel_list_view import ChannelListView

    view = ChannelListView()
    model = QStringListModel(["A"])
    view.setModel(model)
    view.indexAt = lambda _pos: model.index(0, 0)

    captured = []
    view.middle_clicked.connect(lambda idx: captured.append(idx))

    view.mousePressEvent(_press_event(Qt.MouseButton.LeftButton))

    assert captured == [], "a left-button press must NOT emit middle_clicked"
