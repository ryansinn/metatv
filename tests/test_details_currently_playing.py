"""Behavioral tests for the details-pane "currently playing" indicator.

When the title shown in the details pane is the one actively playing, the Play
button paints a GREEN outline and shows a LIVE elapsed timer (``▶ M:SS``) that
ticks up as playback progresses.  When playback stops, or a different channel is
shown, the indicator reverts to the normal Play button.

Covers:

1. _ActionBar level — set_playing_active paints the green style + timer label, the
   per-second tick advances the elapsed time, clear_playing reverts.
2. DetailsPaneWidget.set_playing — green + timer only when the reported channel_id
   matches the shown channel; a different id or None clears it; switching the shown
   channel clears it (and switching back to the playing one re-lights it).
3. Streaming source — the playback-health poll surfaces (channel_id, position) to
   the pane via set_playing, and clears it (None) when idle.

All QTimers/QPixmaps are touched on the main (test) thread.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _label_seconds(text: str) -> int:
    """Parse the elapsed seconds out of a Play-button label like '▶ 12:34'."""
    clock = text.split()[-1]                 # drop the leading play glyph
    parts = [int(p) for p in clock.split(":")]
    secs = 0
    for p in parts:
        secs = secs * 60 + p
    return secs


# ---------------------------------------------------------------------------
# 1. _ActionBar — green style + live timer
# ---------------------------------------------------------------------------

def test_action_bar_set_playing_active_paints_green_and_timer(qapp):
    """set_playing_active flips the Play button to the green style + a timer label."""
    from metatv.gui.details_actions import _ActionBar
    from metatv.gui import theme as _theme

    ab = _ActionBar(_make_config())
    assert ab.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN

    ab.set_playing_active(125)               # 2:05
    assert ab.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING, (
        "playing Play button must use the GREEN style"
    )
    assert _label_seconds(ab.play_button.text()) == 125, (
        f"timer label must show the reported position; got {ab.play_button.text()!r}"
    )
    assert "now playing" in ab.play_button.toolTip().lower()


def test_action_bar_timer_advances_between_position_reports(qapp):
    """The per-second tick counts up (the non-colour cue) without a new report."""
    from metatv.gui.details_actions import _ActionBar

    ab = _ActionBar(_make_config())
    ab.set_playing_active(10)
    first = _label_seconds(ab.play_button.text())

    # Simulate ~5s of wall-clock passing since the last position report, then tick.
    ab._playing_base_ts -= 5
    ab._playing_tick()
    second = _label_seconds(ab.play_button.text())

    assert second >= first + 4, (
        f"elapsed timer must advance with wall time ({first} -> {second})"
    )


def test_action_bar_clear_playing_reverts(qapp):
    """clear_playing restores the normal Play button (style + 'Play' label)."""
    from metatv.gui.details_actions import _ActionBar
    from metatv.gui import theme as _theme

    ab = _ActionBar(_make_config())
    ab.set_playing_active(30)
    assert ab.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING

    ab.clear_playing()
    assert ab.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN
    assert "Play" in ab.play_button.text()
    assert ab._playing_timer is None or not ab._playing_timer.isActive()


def test_action_bar_clear_resets_playing(qapp):
    """clear() (used on every show_channel) also drops the playing indicator."""
    from metatv.gui.details_actions import _ActionBar
    from metatv.gui import theme as _theme

    ab = _ActionBar(_make_config())
    ab.set_playing_active(30)
    ab.clear()
    assert ab.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN
    assert not ab._is_playing


# ---------------------------------------------------------------------------
# 2. DetailsPaneWidget.set_playing — id-matched gating
# ---------------------------------------------------------------------------

def _fake_channel(media_type="movie"):
    from metatv.core.models import MediaType
    ch = MagicMock()
    ch.id = str(uuid.uuid4())
    ch.name = "Test Title"
    ch.media_type = MediaType.MOVIE if media_type == "movie" else MediaType.LIVE
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Title"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    ch.logo_url = None
    return ch


def _make_details_pane(qapp):
    from metatv.gui.details_pane import DetailsPaneWidget
    cache = MagicMock()
    cache.get_image_sync.return_value = None
    return DetailsPaneWidget(_make_config(), cache, db=None)


def test_set_playing_matching_id_shows_indicator(qapp):
    """set_playing with the shown channel's id lights the green Play indicator."""
    from metatv.gui import theme as _theme

    pane = _make_details_pane(qapp)
    ch = _fake_channel("movie")
    pane.show_channel(ch)

    pane.set_playing(ch.id, 90)
    btn = pane._action_bar.play_button
    assert btn.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING
    assert _label_seconds(btn.text()) >= 90


def test_set_playing_other_id_no_indicator(qapp):
    """set_playing for a DIFFERENT channel leaves the Play button normal."""
    from metatv.gui import theme as _theme

    pane = _make_details_pane(qapp)
    ch = _fake_channel("movie")
    pane.show_channel(ch)

    pane.set_playing("some-other-id", 90)
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN


def test_set_playing_none_clears_indicator(qapp):
    """set_playing(None) (playback stopped) clears the indicator."""
    from metatv.gui import theme as _theme

    pane = _make_details_pane(qapp)
    ch = _fake_channel("movie")
    pane.show_channel(ch)
    pane.set_playing(ch.id, 90)
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING

    pane.set_playing(None, 0)
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN


def test_switching_shown_channel_clears_then_relights(qapp):
    """Showing a different channel clears the indicator; returning re-lights it."""
    from metatv.gui import theme as _theme

    pane = _make_details_pane(qapp)
    ch1 = _fake_channel("movie")
    ch2 = _fake_channel("movie")

    pane.show_channel(ch1)
    pane.set_playing(ch1.id, 30)
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING

    pane.show_channel(ch2)               # ch2 is not the playing one
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN

    pane.show_channel(ch1)               # back to the playing title
    assert pane._action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN_PLAYING


# ---------------------------------------------------------------------------
# 3. Streaming source — playback poll surfaces play-state to the pane
# ---------------------------------------------------------------------------

def test_health_poll_surfaces_play_state_to_pane(qapp):
    """The playback-health poll forwards (channel_id, position) to set_playing."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.details_pane = MagicMock()
    host._playback_health_label = MagicMock()
    host._playing_channels = {"k1": "chA"}
    host.player_manager = MagicMock()
    host.player_manager.active_keys.return_value = ["k1"]
    host._source_icon_for_key = lambda k: ""    # avoid the icon-cache lookup

    props = {
        "path": "http://stream",
        "demuxer-cache-duration": 5,
        "cache-speed": 1_000,
        "frame-drop-count": 0,
        "time-pos": 42,
    }
    host._on_playback_health_ready(("k1", props))

    host.details_pane.set_playing.assert_called_once_with("chA", 42)


def test_health_poll_clears_play_state_when_idle(qapp):
    """An idle probe (no loaded path) clears the indicator via set_playing(None)."""
    from metatv.gui.main_window_streaming import _StreamingMixin

    host = _StreamingMixin.__new__(_StreamingMixin)
    host.details_pane = MagicMock()
    host._playback_health_label = MagicMock()
    host._playback_health_timer = MagicMock()

    host._on_playback_health_ready(("k1", None))

    host.details_pane.set_playing.assert_called_once_with(None, 0)
