"""Behavioral tests for the poster Watched badge + live-logo poster.

Covers (feat/details-action-hierarchy supersedes the original rail-watched PR):

1. Clickable two-state Watched badge on the poster (VOD only):
   - Watched → persistent SOLID badge (visible); click → emits new state False.
   - Unwatched → FAINT badge revealed on poster (or badge) hover; click → emits True.
   - Hidden for live channels (set_mode gating).
   - clear() resets the badge so a reused pane shows no stale state.
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
# 1. Clickable two-state Watched badge on _PosterSection
# ---------------------------------------------------------------------------

def test_watched_badge_solid_and_visible_when_watched(qapp):
    """A watched VOD title shows the SOLID badge persistently (no hover needed)."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui import theme as _theme

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=False)

    poster.set_watched(True)
    assert not poster._watched_badge.isHidden(), "watched badge must be visible"
    assert poster._watched_badge.styleSheet() == _theme.POSTER_WATCHED_BADGE, (
        "watched badge must use the SOLID style"
    )
    assert "unwatched" in poster._watched_badge.toolTip().lower(), (
        "watched badge tooltip must offer to mark UNwatched"
    )


def test_watched_badge_faint_and_hover_gated_when_unwatched(qapp):
    """An unwatched VOD title hides the badge until the poster is hovered (faint)."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui import theme as _theme

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=False)

    poster.set_watched(False)
    assert poster._watched_badge.isHidden(), (
        "unwatched badge must stay hidden until hover (uncluttered poster)"
    )

    poster._on_poster_hover(True)   # simulate mouse entering the poster
    assert not poster._watched_badge.isHidden(), "hover must reveal the faint badge"
    assert poster._watched_badge.styleSheet() == _theme.POSTER_UNWATCHED_BADGE, (
        "unwatched badge must use the FAINT style"
    )
    assert poster._watched_badge.toolTip() == "Mark as watched"

    poster._on_poster_hover(False)
    assert poster._watched_badge.isHidden(), "leaving the poster hides the faint badge"


def test_watched_badge_stays_visible_while_hovering_badge_itself(qapp):
    """Moving from poster onto the badge keeps it shown (no leave/enter flicker)."""
    from metatv.gui.details_sections import _PosterSection

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=False)
    poster.set_watched(False)

    poster._on_poster_hover(True)        # over the poster
    poster._on_poster_hover(False)       # poster-leave as cursor crosses onto badge
    poster._on_badge_hover(True)         # badge-enter
    assert not poster._watched_badge.isHidden(), (
        "badge must remain visible while the cursor is over the badge itself"
    )


def test_watched_badge_hidden_for_live(qapp):
    """Live channels have no watched state — the badge never shows."""
    from metatv.gui.details_sections import _PosterSection

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=True)

    poster.set_watched(True)             # even if asked, live must not show it
    assert poster._watched_badge.isHidden(), "watched badge must hide for live channels"
    poster._on_poster_hover(True)
    assert poster._watched_badge.isHidden(), "hover must not reveal the badge for live"


def test_watched_badge_click_toggles_and_emits_new_state(qapp):
    """Clicking the badge flips the optimistic state and emits the NEW state."""
    from metatv.gui.details_sections import _PosterSection

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=False)
    poster.set_watched(False)

    emitted: list[bool] = []
    poster.watched_toggled.connect(lambda w: emitted.append(w))

    poster._watched_badge.click()        # unwatched → watched
    assert poster._watched is True
    assert emitted == [True], f"badge click must emit new state True; got {emitted}"

    poster._watched_badge.click()        # watched → unwatched
    assert poster._watched is False
    assert emitted[-1] is False


def test_clear_resets_watched_badge(qapp):
    """clear() resets the badge so a reused pane doesn't show stale watch state."""
    from metatv.gui.details_sections import _PosterSection

    poster = _PosterSection(_make_config(), MagicMock())
    poster.set_mode(is_live=False)
    poster.set_watched(True)
    assert not poster._watched_badge.isHidden()

    poster.clear()
    assert poster._watched is False
    assert poster._watched_badge.isHidden(), "clear() must reset the badge to unwatched/hidden"


# ---------------------------------------------------------------------------
# 2. Live channel LOGO shown in the poster space (_PosterSection)
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
# 3. DetailsPaneWidget integration: badge state init, signal emit, live routing
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


def test_show_channel_initializes_watched_badge_from_flag(qapp):
    """show_channel sets the poster badge from the channel's watch_completed flag."""
    pane = _make_details_pane(qapp)

    pane.show_channel(_fake_channel("movie", watch_completed=True))
    assert pane._poster._watched is True, "badge must reflect a completed movie"
    assert not pane._poster._watched_badge.isHidden(), (
        "watched badge must be visible for a completed movie"
    )

    # Reuse the pane for an unwatched title — state must reset, not linger.
    pane.show_channel(_fake_channel("movie", watch_completed=False))
    assert pane._poster._watched is False, "badge must reset for an unwatched title"
    assert pane._poster._watched_badge.isHidden(), (
        "unwatched badge must be hidden (faint, hover-only) on a reused pane"
    )


def test_details_watched_badge_emits_new_state(qapp):
    """Clicking the poster badge emits watched_toggled(channel_id, new_state)."""
    pane = _make_details_pane(qapp)
    ch = _fake_channel("movie", watch_completed=False)
    pane.show_channel(ch)

    emitted: list[tuple] = []
    pane.watched_toggled.connect(lambda cid, w: emitted.append((cid, w)))

    pane._poster._watched_badge.click()       # unwatched → watched
    assert emitted == [(ch.id, True)], (
        f"watched_toggled must carry the new state True; got {emitted}"
    )

    pane._poster._watched_badge.click()       # watched → unwatched
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
    # Watched badge is a VOD affordance — hidden for live.
    assert pane._poster._watched_badge.isHidden()


def test_show_channel_live_no_logo_keeps_poster_hidden(qapp):
    """A live channel with no logo falls back to the live header (poster hidden)."""
    pane = _make_details_pane(qapp)
    ch = _fake_channel("live", logo_url=None)

    pane.show_channel(ch)

    assert pane._poster._is_live_logo is False
    assert pane._poster._poster_frame.isHidden(), (
        "no logo → poster frame stays hidden (live header fallback)"
    )
