"""Behavioral tests for the details-pane rating controls (👍 / 🙅 / 👎).

The user report was "the rating controls have gone missing".  Nothing had been
deleted — the trio was three unlabelled 48×24 emoji chips at the BOTTOM of the
slim rail, floating over the poster's left edge and separated from the rest of the
rail by an 80px gap.  Present, but not findable.

The fix promotes them out of the rail into a labelled "Rate:" row directly under
"Watch Later", so what these tests pin is:

1. The controls exist, are labelled, and are visible for VOD.
2. They live in exactly ONE place — moved, not duplicated (rail guard lives in
   tests/test_details_rail_layout_polish.py).
3. Clicking them emits the pane's ``rating_requested(channel_id, rating)`` signal
   with the shown channel's id — the wire into the real rating state.
4. That signal, applied through the app's own toggle chokepoint, round-trips to
   ``UserRatingDB`` on a REAL database: set → read back → toggle-off clears.
5. Re-reading state (``apply_action_state``) drives the checked state, so an
   already-rated title shows as rated.
6. The new row cannot widen the details pane (width trap).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _wired_poster(cfg):
    """A _PosterSection with a real _ActionBar's buttons reparented into it."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

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
        hide=ab.hide_button,
    )
    return poster, ab


def _stub_channel(**kw):
    ch = MagicMock()
    ch.id = kw.get("id", "chan-1")
    ch.name = kw.get("name", "Test Title")
    ch.media_type = kw.get("media_type", "movie")
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = kw.get("detected_title", "Test Title")
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    return ch


# ---------------------------------------------------------------------------
# 1. The controls are present, labelled, and in the main column
# ---------------------------------------------------------------------------

def test_rating_row_exists_with_all_three_controls(qapp):
    poster, ab = _wired_poster(_make_config())

    row_widgets = [
        poster._sentiment_row_layout.itemAt(i).widget()
        for i in range(poster._sentiment_row_layout.count())
    ]
    for btn in (ab.like_button, ab.not_interested_button, ab.dislike_button):
        assert btn in row_widgets, f"{btn.text()!r} must be in the rating row"


def test_rating_row_is_labelled(qapp):
    """The fix for "missing": the trio is no longer an unlabelled emoji cluster."""
    poster, _ = _wired_poster(_make_config())
    assert poster._sentiment_label.text() == "Rate:"
    assert poster._sentiment_label.toolTip(), "the caption must carry a tooltip"

    # Caption comes FIRST, before the buttons
    first = poster._sentiment_row_layout.itemAt(0).widget()
    assert first is poster._sentiment_label


def test_every_rating_control_has_a_tooltip(qapp):
    """Icon-only controls must each explain themselves (project UI rule)."""
    _, ab = _wired_poster(_make_config())
    for btn in (ab.like_button, ab.not_interested_button, ab.dislike_button):
        assert btn.toolTip().strip(), f"{btn.text()!r} needs a tooltip"


def test_rating_row_visible_for_vod_and_hidden_for_live(qapp):
    poster, ab = _wired_poster(_make_config())

    poster.set_mode(is_live=False)
    ab.set_mode(is_live=False)
    assert poster._sentiment_row.isVisibleTo(poster), "rating row must show for VOD"
    assert not ab.like_button.isHidden()
    assert not ab.dislike_button.isHidden()

    poster.set_mode(is_live=True)
    ab.set_mode(is_live=True)
    assert not poster._sentiment_row.isVisibleTo(poster), (
        "rating row (caption included) must hide for live channels"
    )


def test_rating_row_hidden_until_a_channel_is_shown(qapp):
    """No action controls in the empty/no-selection state."""
    poster, _ = _wired_poster(_make_config())
    assert poster._sentiment_row.isHidden()


# ---------------------------------------------------------------------------
# 2. Clicking wires through to the pane's rating_requested signal
# ---------------------------------------------------------------------------

def _details_pane(cfg):
    from metatv.gui.details_pane import DetailsPaneWidget
    return DetailsPaneWidget(cfg, image_cache=MagicMock(), db=None)


def test_clicking_like_emits_rating_requested_with_channel_id(qapp):
    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)

    seen: list[tuple] = []
    pane.rating_requested.connect(lambda cid, r: seen.append((cid, r)))

    pane._action_bar.like_button.click()
    assert seen == [("chan-42", 1)]


def test_clicking_dislike_emits_negative_rating(qapp):
    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)

    seen: list[tuple] = []
    pane.rating_requested.connect(lambda cid, r: seen.append((cid, r)))

    pane._action_bar.dislike_button.click()
    assert seen == [("chan-42", -1)]


def test_apply_action_state_reflects_an_existing_rating(qapp):
    """A title already rated in the DB must render as rated (read path)."""
    from metatv.gui.details_actions import ChannelActionState

    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)

    pane.apply_action_state(ChannelActionState(channel_id="chan-42", rating=1))
    assert pane._action_bar.like_button.isChecked()
    assert not pane._action_bar.dislike_button.isChecked()

    pane.apply_action_state(ChannelActionState(channel_id="chan-42", rating=-1))
    assert pane._action_bar.dislike_button.isChecked()
    assert not pane._action_bar.like_button.isChecked()


# ---------------------------------------------------------------------------
# 3. Full round-trip against a REAL database
# ---------------------------------------------------------------------------

def _real_db(tmp_path):
    """A REAL sqlite Database on a tmp_path FILE (never :memory: — project rule)."""
    from metatv.core.database import Database
    db = Database(f"sqlite:///{tmp_path / 'ratings.db'}")
    db.create_tables()
    return db


def _toggle_host(db):
    """Minimal host exposing the app's real _toggle_rating chokepoint."""
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = SimpleNamespace()
    host.db = db
    host.view_mode = "list"
    host._refresh_recommended_section = lambda: None
    host._toggle_rating = lambda cid, r: _FavoritesMixin._toggle_rating(host, cid, r)
    return host


def test_rating_click_round_trips_to_the_database(qapp, tmp_path):
    """Click 👍 → the pane's signal → the app's toggle → UserRatingDB holds +1."""
    from metatv.core.database import UserRatingDB

    db = _real_db(tmp_path)
    host = _toggle_host(db)

    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)
    pane.rating_requested.connect(host._toggle_rating)

    pane._action_bar.like_button.click()

    with db.session_scope(commit=False) as session:
        row = session.get(UserRatingDB, "chan-42")
        assert row is not None, "clicking 👍 must persist a rating"
        assert row.rating == 1


def test_clicking_the_active_rating_again_clears_it(qapp, tmp_path):
    """Toggle semantics: 👍 then 👍 removes the rating rather than re-writing it."""
    from metatv.core.database import UserRatingDB

    db = _real_db(tmp_path)
    host = _toggle_host(db)

    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)
    pane.rating_requested.connect(host._toggle_rating)

    pane._action_bar.like_button.click()
    pane._action_bar.like_button.click()

    with db.session_scope(commit=False) as session:
        assert session.get(UserRatingDB, "chan-42") is None


def test_dislike_replaces_a_like(qapp, tmp_path):
    from metatv.core.database import UserRatingDB

    db = _real_db(tmp_path)
    host = _toggle_host(db)

    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)
    pane.rating_requested.connect(host._toggle_rating)

    pane._action_bar.like_button.click()
    pane._action_bar.dislike_button.click()

    with db.session_scope(commit=False) as session:
        row = session.get(UserRatingDB, "chan-42")
        assert row is not None and row.rating == -1


def test_stored_rating_reads_back_into_the_controls(qapp, tmp_path):
    """The read half: a rating written to the DB drives the button state."""
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.details_actions import ChannelActionState

    db = _real_db(tmp_path)
    with db.session_scope() as session:
        RepositoryFactory(session).ratings.set("chan-42", -1)

    with db.session_scope(commit=False) as session:
        stored = RepositoryFactory(session).ratings.get("chan-42")

    pane = _details_pane(_make_config())
    pane.show_channel(_stub_channel(id="chan-42"), None)
    pane.apply_action_state(
        ChannelActionState(channel_id="chan-42", rating=stored or 0)
    )

    assert pane._action_bar.dislike_button.isChecked()


# ---------------------------------------------------------------------------
# 4. Width trap
# ---------------------------------------------------------------------------

def test_rating_row_does_not_force_the_pane_wider(qapp):
    """The row must shrink to the 300px pane minimum (docs/DETAILS_PANE_DESIGN.md)."""
    poster, _ = _wired_poster(_make_config())
    width = poster._sentiment_row.minimumSizeHint().width()
    assert width <= 300, f"the rating row floors the pane at {width}px (max 300)"
