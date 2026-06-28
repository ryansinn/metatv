"""Behavioral tests for details-pane layout changes (PR #232).

Change A — Rating on the media-type line:
  * rating_label lives on the same row as _media_type_lbl (not a separate row).
  * Shows when raw_data / metadata provide a rating; hidden + no gap when absent.
  * Content-rating badge (PG-13) also on the media-type row.

Change B — actions tiered by frequency (feat/details-action-hierarchy):
  * Play + Resume graduate to a full-size primary row below the poster; the
    infrequent set (favorite/queue/sentiment/alert/watchlist/hide) stays in the
    slim icon rail left of the poster.
  * Play is full-width when there's no saved position; Play + Resume split 50/50
    when partially-watched, with Resume the dominant filled-orange button.
  * The rail is visible for ALL channel types (VOD and live).
  * like_clicked / dislike_clicked / not_interested_clicked signals still fire.
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


def _stub_channel(**kwargs):
    """Return a minimal MagicMock that passes load_basic() cleanly."""
    ch = MagicMock()
    ch.name = kwargs.get("name", "Test Title")
    ch.media_type = kwargs.get("media_type", "movie")
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = kwargs.get("detected_title", "Test Title")
    ch.detected_year = kwargs.get("detected_year", None)
    ch.detected_prefix = kwargs.get("detected_prefix", None)
    ch.detected_quality = kwargs.get("detected_quality", None)
    ch.detected_region = kwargs.get("detected_region", None)
    ch.raw_data = kwargs.get("raw_data", None)
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    return ch


# ── Change A: rating on the media-type row ───────────────────────────────────

def test_rating_label_is_sibling_of_media_type_label(qapp):
    """After construction, rating_label and _media_type_lbl must share the same
    parent widget (_media_row), proving rating is on the type line (not its own row)."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    # Both must be children of the same _media_row widget
    assert section.rating_label.parent() is section._media_row, (
        "rating_label.parent() must be _media_row — it belongs on the type line"
    )
    assert section._media_type_lbl.parent() is section._media_row, (
        "_media_type_lbl.parent() must also be _media_row"
    )


def test_rating_shown_when_raw_data_has_rating(qapp):
    """load_basic() with a raw_data rating must show rating_label on the type row."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    ch = _stub_channel(raw_data={"rating": "7.5"})
    section.load_basic(ch)

    assert not section.rating_label.isHidden(), (
        "rating_label must be visible after load_basic with a numeric raw_data rating"
    )
    assert "7.5" in section.rating_label.text(), (
        f"rating_label text should contain '7.5'; got '{section.rating_label.text()}'"
    )


def test_rating_hidden_when_no_raw_data(qapp):
    """load_basic() with no raw_data must leave rating_label hidden (no empty gap)."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    ch = _stub_channel(raw_data=None)
    section.load_basic(ch)

    assert section.rating_label.isHidden(), (
        "rating_label must be hidden when raw_data is None — no empty gap on the type line"
    )


def test_rating_hidden_when_raw_data_has_no_rating_key(qapp):
    """load_basic() with raw_data that lacks 'rating' must leave rating_label hidden."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    ch = _stub_channel(raw_data={"stream_type": "movie"})
    section.load_basic(ch)

    assert section.rating_label.isHidden(), (
        "rating_label must stay hidden when raw_data exists but has no 'rating' key"
    )


@pytest.mark.parametrize("zero_rating", ["0", "0.0", 0, 0.0])
def test_rating_hidden_when_raw_rating_is_zero(qapp, zero_rating):
    """A rating of 0 / '0' / '0.0' means unrated — must hide (not show '0.0 of 10')."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    ch = _stub_channel(raw_data={"rating": zero_rating})
    section.load_basic(ch)

    assert section.rating_label.isHidden(), (
        f"rating_label must be hidden for a zero rating ({zero_rating!r}) — "
        "no '0.0 of 10' on unrated content"
    )


def test_rating_shown_via_load_metadata(qapp):
    """load_metadata() with a numeric rating must show rating_label."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(rating=8.2, rating_count=5000))

    assert not section.rating_label.isHidden(), (
        "rating_label must be visible after load_metadata with a rating"
    )
    assert "8.2" in section.rating_label.text()


def test_content_rating_badge_on_media_row(qapp):
    """_content_rating_lbl must share the same parent as _media_type_lbl."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    assert section._content_rating_lbl.parent() is section._media_row, (
        "_content_rating_lbl must be on _media_row (the type line)"
    )


def test_content_rating_badge_shown_via_load_metadata(qapp):
    """load_metadata() with content_rating must show the badge."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(content_rating="PG-13"))

    assert not section._content_rating_lbl.isHidden(), (
        "_content_rating_lbl must be visible after load_metadata with content_rating"
    )
    assert section._content_rating_lbl.text() == "PG-13"


def test_rating_cleared_after_clear(qapp):
    """After clear(), rating_label must be hidden and empty."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(rating=7.0))
    assert not section.rating_label.isHidden()

    section.clear()
    assert section.rating_label.isHidden(), "rating_label must be hidden after clear()"
    assert section.rating_label.text() == "", "rating_label must be empty after clear()"
    assert section._content_rating_lbl.isHidden(), (
        "_content_rating_lbl must be hidden after clear()"
    )


def test_rating_hidden_for_live_via_media_row(qapp):
    """For a live channel, set_mode(is_live=True) hides _media_row which contains the rating."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.metadata_providers.base import MetadataResult

    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(rating=6.5))
    assert not section.rating_label.isHidden()

    section.set_mode(is_live=True)
    # The _media_row (parent) is hidden for live, making rating effectively invisible.
    assert section._media_row.isHidden(), (
        "_media_row (which contains rating_label) must be hidden in live mode"
    )


# ── Change B: ALL action buttons in the vertical rail left of the poster ─────

def _wire_rail(poster, action_bar):
    """Reparent action buttons into their tiered slots (play/resume → primary row)."""
    poster.set_action_buttons(
        favorite=action_bar.favorite_button,
        play=action_bar.play_button,
        resume=action_bar.resume_button,
        queue=action_bar.queue_button,
        like=action_bar.like_button,
        not_interested=action_bar.not_interested_button,
        dislike=action_bar.dislike_button,
        watchlist=action_bar.watchlist_button,
        monitor=action_bar.monitor_button,
        hide=action_bar.hide_button,
    )


def test_infrequent_buttons_reparented_to_rail(qapp):
    """After set_action_buttons(), the infrequent action buttons live in _action_rail.

    Play and Resume are NOT in the rail any more — they graduate to the primary
    action row below the poster (see test_play_resume_in_primary_row).
    """
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)

    _wire_rail(poster, action_bar)

    for btn in (
        action_bar.favorite_button, action_bar.queue_button,
        action_bar.like_button, action_bar.not_interested_button, action_bar.dislike_button,
        action_bar.watchlist_button, action_bar.monitor_button, action_bar.hide_button,
    ):
        assert btn.parent() is poster._action_rail, (
            f"{btn!r} must be reparented to _action_rail after set_action_buttons()"
        )

    # Play/Resume must NOT be in the rail.
    rail_widgets = [
        poster._action_rail_layout.itemAt(i).widget()
        for i in range(poster._action_rail_layout.count())
    ]
    assert action_bar.play_button not in rail_widgets, "Play must NOT be in the rail"
    assert action_bar.resume_button not in rail_widgets, "Resume must NOT be in the rail"


def test_play_resume_in_primary_row(qapp):
    """Play and Resume graduate to the full-size primary action row below the poster."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)

    _wire_rail(poster, action_bar)

    assert action_bar.play_button.parent() is poster._primary_action_row, (
        "Play must live in the primary action row below the poster"
    )
    assert action_bar.resume_button.parent() is poster._primary_action_row, (
        "Resume must live in the primary action row below the poster"
    )


def test_primary_row_play_full_width_when_no_resume(qapp):
    """VOD with no saved position → only Play is shown in the primary row (full-width)."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)
    _wire_rail(poster, action_bar)
    poster.set_mode(is_live=False)

    action_bar.set_resume(False)
    assert not action_bar.play_button.isHidden(), "Play must show"
    assert action_bar.resume_button.isHidden(), (
        "Resume must be hidden when there's no saved position → Play fills the row"
    )


def test_primary_row_resume_dominant_when_partially_watched(qapp):
    """Partially-watched → Play + Resume side-by-side; Resume is the dominant one.

    Both share the primary row (50/50 via equal stretch).  Resume carries the
    filled-orange dominant style + the M:SS label; Play carries the secondary
    outline style.
    """
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar
    from metatv.gui import theme as _theme

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)
    _wire_rail(poster, action_bar)
    poster.set_mode(is_live=False)

    action_bar.set_resume(True, position_s=125)
    assert not action_bar.play_button.isHidden(), "Play must show alongside Resume"
    assert not action_bar.resume_button.isHidden(), "Resume must show when partially watched"
    # Resume label shows the saved position; it is the dominant filled-orange button.
    assert "2:05" in action_bar.resume_button.text(), (
        f"Resume label must show M:SS; got {action_bar.resume_button.text()!r}"
    )
    assert action_bar.resume_button.styleSheet() == _theme.DETAIL_RESUME_BTN, (
        "Resume must use the dominant filled-orange style"
    )
    assert action_bar.play_button.styleSheet() == _theme.DETAIL_PLAY_BTN, (
        "Play must use the secondary outline style"
    )
    # Equal stretch → 50/50 split in the primary row.
    prow = poster._primary_row_layout
    assert prow.stretch(prow.indexOf(action_bar.play_button)) == 1
    assert prow.stretch(prow.indexOf(action_bar.resume_button)) == 1


def test_action_rail_hidden_until_channel_shown(qapp):
    """Regression: in the empty/no-selection state the rail must be hidden, so
    favorite/play/queue/hide icons don't appear with nothing selected.  set_mode()
    (called only when a channel is shown) reveals it."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)

    _wire_rail(poster, action_bar)

    assert poster._action_rail.isHidden(), (
        "_action_rail must stay hidden after wiring buttons but before a channel is "
        "shown — no action icons in the empty state"
    )

    poster.set_mode(is_live=False)
    assert not poster._action_rail.isHidden(), (
        "_action_rail must become visible once a channel is shown (set_mode)"
    )


def test_action_rail_visible_for_vod(qapp):
    """The action rail must be visible for VOD (is_live=False)."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)

    _wire_rail(poster, action_bar)
    poster.set_mode(is_live=False)

    assert not poster._action_rail.isHidden(), (
        "_action_rail must be visible for VOD (is_live=False)"
    )


def test_action_rail_visible_for_live(qapp):
    """The action rail stays visible for live channels (regression: 'icons left of
    poster aren't there').  Only the poster swaps to the live header; the rail stays."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)

    _wire_rail(poster, action_bar)
    poster.set_mode(is_live=False)
    assert not poster._action_rail.isHidden()

    poster.set_mode(is_live=True)
    assert not poster._action_rail.isHidden(), (
        "_action_rail must stay visible for live channels (rail is shown for all types)"
    )
    # The poster frame hides for live; the live header takes its place.
    assert poster._poster_frame.isHidden(), "poster frame must hide in live mode"
    assert not poster._live_header.isHidden(), "live header must show in live mode"


def test_action_bar_set_mode_hides_sentiment_buttons_for_live(qapp):
    """_ActionBar.set_mode(is_live=True) must set the buttons invisible."""
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    action_bar = _ActionBar(cfg)

    # Show them first (VOD mode)
    action_bar.set_mode(is_live=False)
    assert not action_bar.like_button.isHidden()
    assert not action_bar.not_interested_button.isHidden()
    assert not action_bar.dislike_button.isHidden()

    # Switch to live
    action_bar.set_mode(is_live=True)
    assert action_bar.like_button.isHidden(), (
        "like_button must be hidden after set_mode(is_live=True)"
    )
    assert action_bar.not_interested_button.isHidden()
    assert action_bar.dislike_button.isHidden()


def test_like_clicked_signal_fires(qapp):
    """Clicking the like button must emit like_clicked."""
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    action_bar = _ActionBar(cfg)
    action_bar.set_mode(is_live=False)  # make buttons visible

    fired: list[bool] = []
    action_bar.like_clicked.connect(lambda: fired.append(True))

    action_bar.like_button.click()

    assert fired == [True], "like_clicked must emit once on button click"


def test_dislike_clicked_signal_fires(qapp):
    """Clicking the dislike button must emit dislike_clicked."""
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    action_bar = _ActionBar(cfg)
    action_bar.set_mode(is_live=False)

    fired: list[bool] = []
    action_bar.dislike_clicked.connect(lambda: fired.append(True))

    action_bar.dislike_button.click()

    assert fired == [True], "dislike_clicked must emit once on button click"


def test_not_interested_clicked_signal_fires(qapp):
    """Clicking the not_interested button must emit not_interested_clicked."""
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    action_bar = _ActionBar(cfg)
    action_bar.set_mode(is_live=False)

    fired: list[bool] = []
    action_bar.not_interested_clicked.connect(lambda: fired.append(True))

    action_bar.not_interested_button.click()

    assert fired == [True], "not_interested_clicked must emit once on button click"


def test_like_dislike_mutually_exclusive_optimistic_state(qapp):
    """Checking like then dislike must leave only dislike checked (optimistic state)."""
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    action_bar = _ActionBar(cfg)
    action_bar.set_mode(is_live=False)

    action_bar.like_button.click()          # rating → +1
    assert action_bar._rating == 1

    action_bar.dislike_button.click()       # rating → -1, like unchecked
    assert action_bar._rating == -1
    assert not action_bar.like_button.isChecked(), (
        "like_button must not be checked after dislike is clicked"
    )
    assert action_bar.dislike_button.isChecked(), (
        "dislike_button must be checked after clicking dislike"
    )


def test_not_interested_clears_like_and_dislike(qapp):
    """Activating Not Interested must clear an active like/dislike (exclusive group)."""
    from metatv.gui.details_actions import _ActionBar

    action_bar = _ActionBar(_make_config())
    action_bar.set_mode(is_live=False)

    action_bar.like_button.click()            # rating → +1
    assert action_bar.like_button.isChecked()

    action_bar.not_interested_button.click()  # suppress ON → must clear rating
    assert action_bar._suppressed is True
    assert action_bar._rating == 0, "Not Interested must clear the rating"
    assert not action_bar.like_button.isChecked(), "like must be unchecked by Not Interested"
    assert not action_bar.dislike_button.isChecked()
    assert action_bar.not_interested_button.isChecked()


def test_like_clears_not_interested(qapp):
    """Activating like/dislike must clear an active Not Interested (exclusive group)."""
    from metatv.gui.details_actions import _ActionBar

    action_bar = _ActionBar(_make_config())
    action_bar.set_mode(is_live=False)

    action_bar.not_interested_button.click()  # suppress ON
    assert action_bar._suppressed is True

    action_bar.like_button.click()            # like ON → must clear suppression
    assert action_bar._rating == 1
    assert action_bar._suppressed is False, "like must clear Not Interested"
    assert not action_bar.not_interested_button.isChecked()


def test_resume_button_hidden_until_set(qapp):
    """The resume button is hidden by default and shown only via set_resume()."""
    from metatv.gui.details_actions import _ActionBar

    action_bar = _ActionBar(_make_config())
    assert action_bar.resume_button.isHidden(), "resume button must start hidden"

    action_bar.set_resume(True, position_s=125)
    assert not action_bar.resume_button.isHidden(), "set_resume(True) must show it"
    assert "2:05" in action_bar.resume_button.toolTip(), (
        f"resume tooltip should show the M:SS position; got {action_bar.resume_button.toolTip()!r}"
    )

    action_bar.set_resume(False)
    assert action_bar.resume_button.isHidden(), "set_resume(False) must hide it"
