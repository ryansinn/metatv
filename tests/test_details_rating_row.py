"""Behavioral tests for the details-pane rating controls (👍 / 🙅 / 👎).

The user report was "the rating controls have gone missing".  Nothing had been
deleted — the trio was three unlabelled 48×24 emoji chips at the BOTTOM of the
slim rail, floating over the poster's left edge and separated from the rest of the
rail by an 80px gap.  Present, but not findable.

The fix promotes them out of the rail onto the SAME line as "Watch Later",
right-aligned::

    [ 📋 Watch Later ..................... ] [👍] [🙅] [👎]

Position does the separating — collection action left, judgment cluster right — so
neither side carries a caption.  What these tests pin:

1. The controls exist on that one line, right of Watch Later, and are visible for VOD.
2. They live in exactly ONE place — moved, not duplicated (rail guard lives in
   tests/test_details_rail_layout_polish.py).
3. Clicking them emits the pane's ``rating_requested(channel_id, rating)`` signal
   with the shown channel's id — the wire into the real rating state.
4. That signal, applied through the app's own toggle chokepoint, round-trips to
   ``UserRatingDB`` on a REAL database: set → read back → toggle-off clears.
5. Re-reading state (``apply_action_state``) drives the checked state, so an
   already-rated title shows as rated.
6. The shared line cannot widen the details pane (width trap): a QHBoxLayout's
   minimum is the SUM of its children, so Watch Later opts out of driving width and
   yields space first — verified at the real 300px pane minimum, not just in theory.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.conftest import wire_details_action_buttons


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
    wire_details_action_buttons(poster, ab)
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
# 1. The controls share the Watch Later line, right-aligned
# ---------------------------------------------------------------------------

def _row_widgets(poster):
    lay = poster._secondary_row_layout
    return [lay.itemAt(i).widget() for i in range(lay.count())]


def test_rating_controls_share_the_watch_later_line(qapp):
    poster, ab = _wired_poster(_make_config())

    widgets = _row_widgets(poster)
    for btn in (ab.like_button, ab.not_interested_button, ab.dislike_button):
        assert btn in widgets, f"{btn.text()!r} must be on the Watch Later line"
    assert ab.queue_button in widgets, "Watch Later must share that line"


def test_row_order_is_watch_later_then_the_rating_trio(qapp):
    """Collection action LEFT, judgment cluster RIGHT — position is the separator.

    Trailer lives in its own row now (fix/trailer-own-row, owner-reported
    2026-09-03) — it must NOT be on this line at all.
    """
    poster, ab = _wired_poster(_make_config())

    assert _row_widgets(poster) == [
        ab.queue_button,
        ab.like_button,
        ab.not_interested_button,
        ab.dislike_button,
    ], "the secondary row must read [Watch Later] → 👍 → 🙅 → 👎"


def test_rating_controls_are_right_aligned_by_the_queue_stretch(qapp):
    """Only Watch Later stretches, so the trio is pinned to the right edge."""
    poster, ab = _wired_poster(_make_config())
    lay = poster._secondary_row_layout

    assert lay.stretch(0) == 1, "Watch Later must absorb the spare width"
    for idx in (1, 2, 3):
        assert lay.stretch(idx) == 0, "the rating chips must not stretch"


def test_no_caption_label_on_the_row(qapp):
    """The steer: position separates the two halves — no 'Rate:' text."""
    from PyQt6.QtWidgets import QLabel

    poster, _ = _wired_poster(_make_config())
    labels = poster._secondary_action_row.findChildren(QLabel)
    assert labels == [], f"the row must carry no caption label; found {labels}"
    assert not hasattr(poster, "_sentiment_label")


def test_every_rating_control_has_a_tooltip(qapp):
    """Icon-only controls must each explain themselves (project UI rule).

    Load-bearing here: with no caption, the tooltips are the ONLY text explaining
    what the three glyphs do.
    """
    _, ab = _wired_poster(_make_config())
    for btn in (ab.like_button, ab.not_interested_button, ab.dislike_button):
        assert btn.toolTip().strip(), f"{btn.text()!r} needs a tooltip"


def test_rating_controls_visible_for_vod_and_hidden_for_live(qapp):
    """Live hides the chips only — Watch Later keeps the line to itself."""
    poster, ab = _wired_poster(_make_config())

    poster.set_mode(is_live=False)
    ab.set_mode(is_live=False)
    assert poster._secondary_action_row.isVisibleTo(poster)
    assert not ab.like_button.isHidden()
    assert not ab.dislike_button.isHidden()

    poster.set_mode(is_live=True)
    ab.set_mode(is_live=True)
    assert ab.like_button.isHidden(), "ratings are VOD-only"
    assert ab.not_interested_button.isHidden()
    assert ab.dislike_button.isHidden()
    assert poster._secondary_action_row.isVisibleTo(poster), (
        "the row itself stays — Watch Later still applies to live channels"
    )
    assert not ab.queue_button.isHidden()


def test_rating_row_hidden_until_a_channel_is_shown(qapp):
    """No action controls in the empty/no-selection state."""
    poster, _ = _wired_poster(_make_config())
    assert poster._secondary_action_row.isHidden()


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
    # _toggle_rating publishes to the bus; wire one from the shared factory.
    from tests.conftest import attach_channel_state_bus
    attach_channel_state_bus(host)
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

def test_shared_row_does_not_force_the_pane_wider(qapp):
    """The row must shrink to the 300px pane minimum (docs/DETAILS_PANE_DESIGN.md).

    A QHBoxLayout's minimum width is the SUM of its children's minimums, so putting
    Watch Later and three chips on one line is exactly the shape that floors a pane.
    Watch Later opts out of driving width, leaving the row's minimum at 3 chips +
    spacing.
    """
    poster, _ = _wired_poster(_make_config())
    width = poster._secondary_action_row.minimumSizeHint().width()
    assert width <= 300, f"the Watch Later row floors the pane at {width}px (max 300)"


def test_watch_later_does_not_drive_the_row_minimum(qapp):
    """The button's TEXT width must not become the row's floor.

    Regression guard: drop the Ignored horizontal policy and this row's minimum
    jumps by the width of "📋 Watch Later", which is how the pane gets floored.
    """
    from PyQt6.QtWidgets import QSizePolicy

    poster, ab = _wired_poster(_make_config())
    assert (
        ab.queue_button.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
    ), "Watch Later must opt out of driving the row width"

    row_min = poster._secondary_action_row.minimumSizeHint().width()
    chips_only = 3 * poster._SENTIMENT_BTN_W + 3 * poster._SECONDARY_ROW_SPACING
    assert row_min <= chips_only + 8, (
        f"row minimum {row_min}px should be ~the three chips ({chips_only}px), "
        f"not the button's text width"
    )


def test_row_is_not_the_panes_width_forcer(qapp):
    """Composition-level check: some OTHER section must still set the content floor.

    docs/DETAILS_PANE_DESIGN.md's debugging recipe — measure every section, the
    forcer is the widest minimum.  This row must not be it.
    """
    from metatv.gui.details_pane import DetailsPaneWidget

    pane = DetailsPaneWidget(_make_config(), image_cache=MagicMock(), db=None)
    row_min = pane._poster._secondary_action_row.minimumSizeHint().width()
    content_min = pane._content.minimumSizeHint().width()
    assert row_min <= content_min, (
        f"the Watch Later/rating row ({row_min}px) must not be the widest-minimum "
        f"child (content floor is {content_min}px)"
    )


def test_chips_stay_inside_the_row_at_the_pane_minimum(qapp):
    """Real geometry at 300px: nothing spills past the right edge.

    The width trap's symptom is content laid out past the edge with the horizontal
    scrollbar off, so assert against actual laid-out geometry, not just hints.
    """
    from PyQt6.QtWidgets import QWidget, QVBoxLayout
    from metatv.gui.details_pane import DetailsPaneWidget
    from metatv.gui.details_actions import ChannelActionState

    host = QWidget()
    host.resize(300, 900)
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    pane = DetailsPaneWidget(_make_config(), image_cache=MagicMock(), db=None)
    lay.addWidget(pane)
    host.show()
    qapp.processEvents()

    pane.show_channel(_stub_channel(), None)
    pane.apply_action_state(ChannelActionState(channel_id="chan-1"))
    qapp.processEvents()
    host.resize(300, 900)
    qapp.processEvents()

    row = pane._poster._secondary_action_row
    dislike = pane._action_bar.dislike_button
    queue = pane._action_bar.queue_button

    assert dislike.geometry().right() <= row.width(), (
        f"the last rating chip (right edge {dislike.geometry().right()}) spills past "
        f"the {row.width()}px row"
    )
    assert queue.width() > 0, "Watch Later must still be visible, just narrower"
    assert queue.geometry().right() <= pane._action_bar.like_button.geometry().left(), (
        "Watch Later must not overlap the rating chips"
    )
    host.close()
