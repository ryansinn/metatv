"""Behavioral tests for the details action-rail Watched toggle + live logo poster.

Covers the two changes in PR feat/details-rail-watched:

1. Watched toggle button in the action rail:
   - Reflects the channel's watch_completed state (checked = watched).
   - Toggling flips state + emits, and tooltip reads the next action.
   - Hidden for live channels, shown for VOD (set_mode gating).
   - set_action_buttons places the Watched button directly above Hide.
   - DetailsPaneWidget emits watched_toggled(channel_id, new_state) and the host
     routes it through the shared mark/unmark chokepoint (no parallel path).

2. Live channel LOGO shown in the poster space:
   - load_live_logo reveals the poster frame, routes the URL through the async
     image path, and caps the poster box height (contained, not stretched).
   - on_image_loaded sets the (contained) pixmap on the poster label.
   - No logo → poster frame stays hidden (live header fallback).

All QPixmaps are built on the main thread (these tests run in the Qt thread).
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from PyQt6.QtGui import QPixmap


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


# ---------------------------------------------------------------------------
# 1. Watched toggle button on _ActionBar
# ---------------------------------------------------------------------------

def test_watched_button_hidden_for_live_shown_for_vod(qapp):
    """set_mode gates the Watched toggle: shown for VOD, hidden for live."""
    from metatv.gui.details_actions import _ActionBar

    ab = _ActionBar(_make_config())

    ab.set_mode(is_live=False)
    assert not ab.watched_button.isHidden(), "Watched toggle must show for VOD"

    ab.set_mode(is_live=True)
    assert ab.watched_button.isHidden(), "Watched toggle must hide for live channels"


def test_set_watched_reflects_state_and_tooltip(qapp):
    """set_watched checks the button when watched and sets the next-action tooltip."""
    from metatv.gui.details_actions import _ActionBar

    ab = _ActionBar(_make_config())

    ab.set_watched(True)
    assert ab.watched_button.isChecked(), "watched_button must be checked when watched"
    assert ab._watched is True
    assert ab.watched_button.toolTip() == "Mark as unwatched"

    ab.set_watched(False)
    assert not ab.watched_button.isChecked(), "watched_button must be unchecked when unwatched"
    assert ab._watched is False
    assert ab.watched_button.toolTip() == "Mark as watched"


def test_watched_button_click_toggles_state_and_emits(qapp):
    """Clicking the Watched toggle flips the optimistic state and emits watched_clicked."""
    from metatv.gui.details_actions import _ActionBar

    ab = _ActionBar(_make_config())
    ab.set_mode(is_live=False)
    ab.set_watched(False)

    fired: list[bool] = []
    ab.watched_clicked.connect(lambda: fired.append(True))

    ab.watched_button.click()       # unwatched → watched
    assert ab._watched is True, "click must flip optimistic watched state to True"
    assert ab.watched_button.isChecked()
    assert ab.watched_button.toolTip() == "Mark as unwatched"
    assert fired == [True], "watched_clicked must emit once per click"

    ab.watched_button.click()       # watched → unwatched
    assert ab._watched is False, "second click must flip back to unwatched"
    assert not ab.watched_button.isChecked()
    assert len(fired) == 2


def test_clear_resets_watched_state(qapp):
    """clear() resets the Watched toggle so a reused pane doesn't show stale state."""
    from metatv.gui.details_actions import _ActionBar

    ab = _ActionBar(_make_config())
    ab.set_watched(True)
    assert ab.watched_button.isChecked()

    ab.clear()
    assert ab._watched is False
    assert not ab.watched_button.isChecked(), "clear() must uncheck the Watched toggle"
    assert ab.watched_button.toolTip() == "Mark as watched"


# ---------------------------------------------------------------------------
# 2. set_action_buttons places Watched directly above Hide
# ---------------------------------------------------------------------------

def _rail_widgets_in_order(poster):
    """Return the rail's widgets in layout order (skipping spacers/stretches)."""
    layout = poster._action_rail_layout
    widgets = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is not None:
            widgets.append(w)
    return widgets


def test_set_action_buttons_places_watched_directly_above_hide(qapp):
    """The Watched toggle is the rail item immediately preceding Hide."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    ab = _ActionBar(cfg)

    poster.set_action_buttons(
        favorite=ab.favorite_button,
        play=ab.play_button,
        resume=ab.resume_button,
        queue=ab.queue_button,
        like=ab.like_button,
        not_interested=ab.not_interested_button,
        dislike=ab.dislike_button,
        watchlist=ab.watchlist_button,
        monitor=ab.monitor_button,
        watched=ab.watched_button,
        hide=ab.hide_button,
    )

    order = _rail_widgets_in_order(poster)
    assert ab.watched_button in order and ab.hide_button in order
    w_idx = order.index(ab.watched_button)
    h_idx = order.index(ab.hide_button)
    assert w_idx == h_idx - 1, (
        "Watched toggle must sit directly above Hide in the rail "
        f"(watched={w_idx}, hide={h_idx})"
    )


# ---------------------------------------------------------------------------
# 3. Live channel LOGO shown in the poster space (_PosterSection)
# ---------------------------------------------------------------------------

def test_load_live_logo_reveals_poster_and_caps_height(qapp):
    """load_live_logo shows the poster frame, routes the URL, and caps the box height."""
    from metatv.gui.details_sections import _PosterSection

    cache = MagicMock()
    cache.get_image_sync.return_value = None   # force async path
    poster = _PosterSection(_make_config(), cache)
    poster.set_mode(is_live=True)
    assert poster._poster_frame.isHidden(), "poster frame starts hidden for live"

    poster.load_live_logo("http://logo/x.png")

    assert poster._is_live_logo is True
    assert poster._poster_url == "http://logo/x.png", "URL must route through the async slot"
    assert not poster._poster_frame.isHidden(), "load_live_logo must reveal the poster frame"
    # Capped to the short live-logo box, NOT the tall VOD poster height.
    assert poster.poster_label.maximumHeight() == poster._LIVE_LOGO_MAX_H
    assert poster._LIVE_LOGO_MAX_H < poster._POSTER_MIN_H
    cache.get_image_async.assert_called_once()


def test_live_logo_pixmap_set_on_main_thread_slot(qapp):
    """on_image_loaded for a live logo sets a (non-null) pixmap on the poster label."""
    from metatv.gui.details_sections import _PosterSection

    cache = MagicMock()
    cache.get_image_sync.return_value = None
    poster = _PosterSection(_make_config(), cache)
    poster.set_mode(is_live=True)
    poster.load_live_logo("http://logo/y.png")

    pix = QPixmap(64, 64)        # built on the main (test) thread
    pix.fill()
    poster.on_image_loaded("http://logo/y.png", pix)

    assert poster.poster_label.pixmap() is not None
    assert not poster.poster_label.pixmap().isNull(), "logo pixmap must be displayed"


def test_live_logo_load_failure_falls_back_to_header(qapp):
    """If the logo fails to load, the poster frame hides (live header fallback)."""
    from metatv.gui.details_sections import _PosterSection

    cache = MagicMock()
    cache.get_image_sync.return_value = None
    poster = _PosterSection(_make_config(), cache)
    poster.set_mode(is_live=True)
    poster.load_live_logo("http://logo/z.png")
    assert not poster._poster_frame.isHidden()

    poster.on_image_failed("http://logo/z.png", "boom")
    assert poster._poster_frame.isHidden(), "failed live logo must hide the poster frame"


def test_switch_live_logo_to_vod_restores_tall_poster(qapp):
    """Switching from a live logo back to VOD restores the tall poster box metrics."""
    from metatv.gui.details_sections import _PosterSection

    cache = MagicMock()
    cache.get_image_sync.return_value = None
    poster = _PosterSection(_make_config(), cache)
    poster.set_mode(is_live=True)
    poster.load_live_logo("http://logo/a.png")
    assert poster.poster_label.maximumHeight() == poster._LIVE_LOGO_MAX_H

    poster.set_mode(is_live=False)   # back to VOD
    assert poster._is_live_logo is False
    assert poster.poster_label.maximumHeight() == poster._POSTER_MAX_H
    assert poster.poster_label.minimumHeight() == poster._POSTER_MIN_H


# ---------------------------------------------------------------------------
# 4. DetailsPaneWidget integration: state init, signal emit, live logo routing
# ---------------------------------------------------------------------------

def _fake_channel(media_type="movie", *, watch_completed=False, watch_progress=0,
                  logo_url=None):
    ch = MagicMock()
    ch.id = str(uuid.uuid4())
    ch.name = "Test Title"
    ch.media_type = media_type
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Test Title"
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = watch_completed
    ch.watch_progress = watch_progress
    ch.logo_url = logo_url
    return ch


def _make_details_pane(qapp):
    from metatv.gui.details_pane import DetailsPaneWidget
    cache = MagicMock()
    cache.get_image_sync.return_value = None
    return DetailsPaneWidget(_make_config(), cache, db=None)


def test_show_channel_initializes_watched_toggle_from_flag(qapp):
    """show_channel sets the Watched toggle from the channel's watch_completed flag."""
    pane = _make_details_pane(qapp)

    pane.show_channel(_fake_channel("movie", watch_completed=True))
    assert pane._action_bar.watched_button.isChecked(), (
        "Watched toggle must be checked for a completed movie"
    )

    # Reuse the pane for an unwatched title — state must reset, not linger.
    pane.show_channel(_fake_channel("movie", watch_completed=False))
    assert not pane._action_bar.watched_button.isChecked(), (
        "Watched toggle must reset to unchecked for an unwatched title"
    )


def test_details_watched_toggle_emits_new_state(qapp):
    """Clicking the Watched toggle emits watched_toggled(channel_id, new_state)."""
    pane = _make_details_pane(qapp)
    ch = _fake_channel("movie", watch_completed=False)
    pane.show_channel(ch)

    emitted: list[tuple] = []
    pane.watched_toggled.connect(lambda cid, w: emitted.append((cid, w)))

    pane._action_bar.watched_button.click()       # unwatched → watched
    assert emitted == [(ch.id, True)], (
        f"watched_toggled must carry the new state True; got {emitted}"
    )

    pane._action_bar.watched_button.click()       # watched → unwatched
    assert emitted[-1] == (ch.id, False)


def test_host_routes_watched_toggle_through_mark_chokepoint(qapp):
    """The host handler reuses _mark_channel_watched / _mark_channel_unwatched."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _FavoritesMixin.__new__(_FavoritesMixin)
    calls: list[tuple[str, str]] = []
    host._mark_channel_watched = lambda cid: calls.append(("watched", cid))
    host._mark_channel_unwatched = lambda cid: calls.append(("unwatched", cid))

    host._on_details_watched_toggled("c1", True)
    host._on_details_watched_toggled("c1", False)

    assert calls == [("watched", "c1"), ("unwatched", "c1")], (
        "Watched toggle must route through the existing mark/unmark chokepoint"
    )


def test_show_channel_live_routes_logo_to_poster(qapp):
    """A live channel with a logo_url routes it to the poster via load_live_logo."""
    pane = _make_details_pane(qapp)
    ch = _fake_channel("live", logo_url="http://logo/live.png")

    pane.show_channel(ch)

    assert pane._poster._is_live_logo is True, "live logo must populate the poster area"
    assert pane._poster._poster_url == "http://logo/live.png"
    # Watched toggle is a VOD affordance — hidden for live.
    assert pane._action_bar.watched_button.isHidden()


def test_show_channel_live_no_logo_keeps_poster_hidden(qapp):
    """A live channel with no logo falls back to the live header (poster hidden)."""
    pane = _make_details_pane(qapp)
    ch = _fake_channel("live", logo_url=None)

    pane.show_channel(ch)

    assert pane._poster._is_live_logo is False
    assert pane._poster._poster_frame.isHidden(), (
        "no logo → poster frame stays hidden (live header fallback)"
    )
