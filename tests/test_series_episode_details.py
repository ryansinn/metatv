"""Behavioral tests for the series 'Browse' button + episode single-click details.

Covers the three user-visible changes (What's New #137):

1. A SERIES root's primary button reads '🗂 Browse' (not '▶ Play'); a movie keeps
   '▶ Play'.  The "currently playing" indicator must NOT override a Browse caption
   (a series never plays directly).
2. ``DetailsPaneWidget.show_episode(dto, series)`` fills the pane with an episode:
   a wrapping byline carrying the episode title, a '▶ Play Episode' button, the
   series title/poster kept intact, and the episode DTO stored on the pane.  The
   byline is width-subordinate so a long title can't clip / widen the column.
   Clicking Play Episode emits the bare ``play_episode_requested`` signal.
3. Reverting via ``show_channel(series)`` drops episode mode and restores Browse.

Plus the host wiring: ``_SeriesMixin._on_series_tree_selection`` routes episode →
``show_episode`` / season → ``show_channel``, and ``_on_details_play_episode``
plays the stored DTO through the existing ``play_episode`` chokepoint.

All QTimers/QPixmaps are touched on the main (test) thread.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.repositories.dtos import EpisodeDTO
from metatv.gui import icons as _icons


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _fake_channel(media_type="series", *, name="Test Show"):
    ch = MagicMock()
    ch.id = str(uuid.uuid4())
    ch.name = name
    ch.media_type = media_type
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = name
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


def _episode(title="Pilot", *, episode_num=1, season_num=1):
    return EpisodeDTO(
        id=str(uuid.uuid4()),
        episode_num=episode_num,
        season_num=season_num,
        title=title,
        series_name="Test Show",
        stream_url="http://stream/ep",
        duration="45:00",
        is_watched=False,
        rating=None,
    )


# ---------------------------------------------------------------------------
# 1. Browse vs Play caption
# ---------------------------------------------------------------------------

def test_series_channel_shows_browse_button(qapp):
    """A SERIES root's primary button reads '🗂 Browse' with the browse tooltip."""
    pane = _make_details_pane(qapp)
    pane.show_channel(_fake_channel("series"))

    btn = pane._action_bar.play_button
    assert btn.text() == f"{_icons.browse_icon} Browse", (
        f"series primary button must read Browse; got {btn.text()!r}"
    )
    assert "browse" in btn.toolTip().lower()


def test_movie_channel_keeps_play_button(qapp):
    """A movie keeps the '▶ Play' caption — never Browse."""
    pane = _make_details_pane(qapp)
    pane.show_channel(_fake_channel("movie"))

    btn = pane._action_bar.play_button
    assert _icons.browse_icon not in btn.text(), "a movie must not read Browse"
    assert btn.text() == f"{_icons.play_icon} Play"


def test_playing_indicator_does_not_override_browse(qapp):
    """A series is never 'playing' — set_playing must not repaint the Browse caption."""
    pane = _make_details_pane(qapp)
    series = _fake_channel("series")
    pane.show_channel(series)

    # Report the series itself as the actively-playing title (ids match).
    pane.set_playing(series.id, 123.0)

    btn = pane._action_bar.play_button
    assert btn.text() == f"{_icons.browse_icon} Browse", (
        f"playing indicator must not overwrite the Browse label; got {btn.text()!r}"
    )
    assert pane._action_bar._is_playing is False


# ---------------------------------------------------------------------------
# 2. show_episode
# ---------------------------------------------------------------------------

def test_show_episode_sets_byline_and_play_episode_button(qapp):
    """show_episode shows the episode title in the byline + a 'Play Episode' button,
    stores the DTO, and leaves the series title untouched."""
    pane = _make_details_pane(qapp)
    series = _fake_channel("series", name="Cowboy Bebop")
    pane.show_channel(series)

    ep = _episode("Asteroid Blues")
    pane.show_episode(ep, series)

    assert pane._byline.text() == "Asteroid Blues", "byline must carry the episode title"
    assert not pane._byline.isHidden(), "byline must be visible in episode mode"
    assert pane._meta.title_label.text() == "Cowboy Bebop", (
        "the series title must NOT be overwritten by the episode title"
    )
    assert pane._action_bar.play_button.text() == f"{_icons.play_icon} Play Episode"
    assert "this episode" in pane._action_bar.play_button.toolTip().lower()
    assert pane.current_episode is ep, "the episode DTO must be stored on the pane"
    assert pane._in_episode_mode is True


def test_show_episode_establishes_series_context_when_pane_empty(qapp):
    """Calling show_episode directly (no prior show_channel) still renders — it
    establishes the series context itself, so the series becomes current_channel."""
    pane = _make_details_pane(qapp)
    series = _fake_channel("series")
    ep = _episode("Stray Dog Strut")

    pane.show_episode(ep, series)

    assert pane.current_channel is series, "series must become the pane's current_channel"
    assert pane.current_episode is ep
    assert pane._byline.text() == "Stray Dog Strut"


def test_episode_byline_wraps_and_is_width_subordinate(qapp):
    """A long episode title must wrap and never floor the column width (width discipline)."""
    from PyQt6.QtWidgets import QSizePolicy

    pane = _make_details_pane(qapp)
    series = _fake_channel("series")
    long_title = (
        "The Episode With A Very Long Title That Would Otherwise Force The "
        "Details Column Wider Than The Pane And Clip Everything Off The Right Edge"
    )
    pane.show_episode(_episode(long_title), series)

    assert pane._byline.wordWrap() is True, "byline must word-wrap"
    assert (
        pane._byline.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    ), "byline must opt out of driving the column width (via _no_width_force)"
    assert pane._byline.text() == long_title


def test_play_episode_button_emits_bare_signal(qapp):
    """In episode mode, clicking the primary button emits play_episode_requested
    (bare) — NOT play_requested(channel_id)."""
    pane = _make_details_pane(qapp)
    series = _fake_channel("series")
    ep = _episode("Honky Tonk Women")
    pane.show_episode(ep, series)

    episode_fired: list = []
    channel_fired: list = []
    pane.play_episode_requested.connect(lambda: episode_fired.append(True))
    pane.play_requested.connect(lambda cid: channel_fired.append(cid))

    pane._action_bar.play_button.click()

    assert episode_fired == [True], "episode-mode Play must emit play_episode_requested"
    assert channel_fired == [], "episode-mode Play must NOT emit the channel play signal"


# ---------------------------------------------------------------------------
# 3. Revert to series details
# ---------------------------------------------------------------------------

def test_reverting_to_series_clears_episode_mode(qapp):
    """show_channel(series) after an episode drops the byline + episode state and
    restores the Browse caption."""
    pane = _make_details_pane(qapp)
    series = _fake_channel("series")
    pane.show_episode(_episode("Ballad of Fallen Angels"), series)
    assert pane._in_episode_mode is True

    pane.show_channel(series)  # user selected the season / series row

    assert pane._in_episode_mode is False
    assert pane.current_episode is None
    assert pane._byline.isHidden(), "byline must hide when reverting to series details"
    assert pane._action_bar.play_button.text() == f"{_icons.browse_icon} Browse"


# ---------------------------------------------------------------------------
# 4. Host wiring (_SeriesMixin) — no full MainWindow needed
# ---------------------------------------------------------------------------

def test_host_tree_selection_routes_episode_and_season(qapp):
    """_on_series_tree_selection: episode → show_episode; season → show_channel."""
    from PyQt6.QtCore import Qt
    from metatv.gui.main_window_series import _SeriesMixin

    host = _SeriesMixin.__new__(_SeriesMixin)
    series = SimpleNamespace(id="series-1", name="Show")
    host.current_series = series

    recorded: list = []
    host.details_pane = SimpleNamespace(
        show_episode=lambda ep, s: recorded.append(("episode", ep, s)),
        show_channel=lambda s: recorded.append(("channel", s)),
        current_episode=object(),   # "drifted" so a season click reverts
        current_channel=None,
    )

    ep = _episode("Sympathy for the Devil")
    ep_item = MagicMock()
    ep_item.data.return_value = {"type": "episode", "data": ep}
    host._on_series_tree_selection(ep_item)
    assert recorded[-1] == ("episode", ep, series)

    season_item = MagicMock()
    season_item.data.return_value = {"type": "season", "data": SimpleNamespace()}
    host._on_series_tree_selection(season_item)
    assert recorded[-1] == ("channel", series)

    # A header/gap row (no dict UserRole) must not crash — treated like a revert.
    gap_item = MagicMock()
    gap_item.data.return_value = None
    recorded.clear()
    host._on_series_tree_selection(gap_item)
    assert recorded == [("channel", series)]


def test_host_play_episode_reads_stored_dto(qapp):
    """_on_details_play_episode plays the pane's stored episode via play_episode."""
    from metatv.gui.main_window_series import _SeriesMixin

    host = _SeriesMixin.__new__(_SeriesMixin)
    ep = _episode("Jupiter Jazz")
    host.details_pane = SimpleNamespace(current_episode=ep)

    played: list = []
    host.play_episode = lambda episode: played.append(episode)
    host._on_details_play_episode()
    assert played == [ep]

    # No stored episode → no-op (defensive).
    host.details_pane = SimpleNamespace(current_episode=None)
    played.clear()
    host._on_details_play_episode()
    assert played == []
