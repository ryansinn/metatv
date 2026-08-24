"""Behavioral tests for the details-pane rail/primary-zone layout polish (PR #263).

Covers the meticulously-designed rail/layout pass on _PosterSection:

1. Rail button order (top→bottom): Favorite · Alert/Monitor (Watchlist shares the
   slot) · Hide.  Queue is NOT in the rail (it is the Watch Later button); Watched is
   NOT in the rail (it is the poster badge); the sentiment trio is NOT in the rail —
   it graduated to the labelled "Rate:" row (see tests/test_details_rating_row.py).
2. Rail spacing: G = Monitor↔Hide gap; Favorite↔Monitor = G/2 (tight top pair).
3. Rail group bracketed by a leading + trailing STRETCH (not top-anchored).
4. Play + Watch Later rows live in the OUTER column (full-width, title-aligned), NOT
   indented under the poster (i.e. not parented to _content_col).
5. Watched poster badge pinned to the LOWER-right corner.
6. Play stays anchored below the live logo footprint for live channels.

All QPixmaps are built on the main thread (these tests run in the Qt thread).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from PyQt6.QtCore import Qt


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def test_favorite_button_is_gold_when_favorited(qapp):
    """Favorited state must be an unmistakable GOLD star, not gray-on-gray.

    The favorite rail button is not ``:checkable`` (state = icon-swap ☆→★), so the
    accent ``:checked`` rule can't reach it — ``update_favorite`` swaps in the gold
    ``DETAIL_RAIL_BTN_FAV`` style and reverts to the plain rail style when cleared.
    """
    from metatv.gui.details_actions import _ActionBar
    from metatv.gui import theme as _theme

    bar = _ActionBar(_make_config())

    bar.update_favorite(True)
    on = bar.favorite_button.styleSheet()
    assert on == _theme.DETAIL_RAIL_BTN_FAV, "favorited → gold rail style"
    # The gold TOKEN, not the CSS keyword. COLOR_GOLD was literally the string
    # "gold" until the palette became derived; asserting the keyword pinned an
    # implementation detail, not the requirement (that favorited reads as gold).
    assert _theme.COLOR_GOLD.lower() in on.lower(), (
        "favorited style must use the gold colour token"
    )
    assert on != _theme.DETAIL_RAIL_BTN, "favorited must look different from unfavorited"

    bar.update_favorite(False)
    assert bar.favorite_button.styleSheet() == _theme.DETAIL_RAIL_BTN, \
        "un-favorited reverts to the plain rail style"


def _build(qapp):
    """Return (poster, action_bar) with the buttons wired into their tiered slots."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    poster = _PosterSection(cfg, MagicMock())
    action_bar = _ActionBar(cfg)
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
        clear_epg_link=action_bar.clear_epg_link_button,
        hide=action_bar.hide_button,
    )
    return poster, action_bar


def _rail_widgets(layout):
    """Ordered list of the WIDGETS in the rail (skipping stretches/spacers)."""
    return [
        layout.itemAt(i).widget()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
    ]


def _is_stretch(item) -> bool:
    """True for an addStretch() item (a vertically-expanding spacer)."""
    sp = item.spacerItem()
    if sp is None:
        return False
    return bool(sp.expandingDirections() & Qt.Orientation.Vertical)


def _gap_after(layout, widget):
    """Fixed-spacer height immediately after `widget` (None if next item isn't one)."""
    for i in range(layout.count()):
        if layout.itemAt(i).widget() is widget:
            nxt = layout.itemAt(i + 1) if i + 1 < layout.count() else None
            sp = nxt.spacerItem() if nxt is not None else None
            if sp is not None and not (sp.expandingDirections() & Qt.Orientation.Vertical):
                return sp.sizeHint().height()
            return None
    return None


# ---------------------------------------------------------------------------
# 1. Rail button order
# ---------------------------------------------------------------------------

def test_rail_button_order_top_to_bottom(qapp):
    """Rail order must be Favorite · Monitor · Watchlist · Clear-EPG-link · Hide
    (sentiment moved out; Clear EPG link is the Wave 3 Slice 3B admin action)."""
    poster, ab = _build(qapp)

    assert _rail_widgets(poster._action_rail_layout) == [
        ab.favorite_button,
        ab.monitor_button,
        ab.watchlist_button,
        ab.clear_epg_link_button,
        ab.hide_button,
    ], "rail order must match the designed top→bottom sequence"


def test_watchlist_adjacent_to_monitor(qapp):
    """Watchlist shares Monitor's slot — it must sit immediately after Monitor."""
    poster, ab = _build(qapp)
    order = _rail_widgets(poster._action_rail_layout)
    assert order.index(ab.watchlist_button) == order.index(ab.monitor_button) + 1, (
        "Watchlist must be adjacent to (right after) Alert/Monitor"
    )


def test_queue_and_watched_not_in_rail(qapp):
    """Queue (Watch Later) and the play/resume buttons must not be rail icons."""
    poster, ab = _build(qapp)
    widgets = _rail_widgets(poster._action_rail_layout)
    for btn in (ab.queue_button, ab.play_button, ab.resume_button):
        assert btn not in widgets, f"{btn.text()!r} must not be in the rail"


def test_sentiment_trio_not_in_rail(qapp):
    """The rating controls graduated to the labelled "Rate:" row — not the rail.

    Regression guard for the fix: they must live in exactly ONE place, so finding
    them back in the rail means they were duplicated rather than moved.
    """
    poster, ab = _build(qapp)
    widgets = _rail_widgets(poster._action_rail_layout)
    for btn in (ab.like_button, ab.not_interested_button, ab.dislike_button):
        assert btn not in widgets, f"{btn.text()!r} must not be in the rail"


# ---------------------------------------------------------------------------
# 2. Rail spacing (G geometry, Hide as the pivot)
# ---------------------------------------------------------------------------

def test_rail_spacing_geometry(qapp):
    """The rail group is tight: Favorite↔Monitor = G/2, Monitor/Watchlist↔Clear-EPG-
    link = G/2, Clear-EPG-link↔Hide = G.

    Hide is now the LAST rail button (the sentiment trio moved to its own row), so
    nothing follows it — the trailing stretch does.
    """
    poster, ab = _build(qapp)
    lay = poster._action_rail_layout
    G = poster._RAIL_GAP

    fav_gap = _gap_after(lay, ab.favorite_button)               # Favorite ↔ Monitor
    slot_gap = _gap_after(lay, ab.watchlist_button)             # Monitor/Watchlist ↔ Clear-EPG-link
    clear_gap = _gap_after(lay, ab.clear_epg_link_button)       # Clear-EPG-link ↔ Hide
    hide_gap = _gap_after(lay, ab.hide_button)                  # Hide ↔ (trailing stretch)

    # Top group unchanged: tight pair + a single G before Hide.
    assert fav_gap == G // 2, "Favorite↔Monitor must be the tight G/2 top pair"
    assert slot_gap == G // 2, "Monitor/Watchlist↔Clear-EPG-link must be the tight G/2"
    assert clear_gap == G, "Clear-EPG-link↔Hide must be G"
    # Hide is last: _gap_after returns None when the next item is the stretch.
    assert hide_gap is None, "Hide must be the last rail button (stretch follows)"


# ---------------------------------------------------------------------------
# 3. Rail group centered on the poster's vertical midline
# ---------------------------------------------------------------------------

def test_rail_group_is_vertically_centered(qapp):
    """A leading AND trailing stretch must bracket the buttons (not top-anchored)."""
    poster, _ = _build(qapp)
    lay = poster._action_rail_layout
    assert lay.count() >= 2

    first = lay.itemAt(0)
    last = lay.itemAt(lay.count() - 1)
    assert first.widget() is None and _is_stretch(first), (
        "rail must START with a stretch so the group is centered, not top-anchored"
    )
    assert last.widget() is None and _is_stretch(last), (
        "rail must END with a stretch so the group is centered, not top-anchored"
    )


# ---------------------------------------------------------------------------
# 4. Play + Watch Later are full-width / title-aligned (not indented under poster)
# ---------------------------------------------------------------------------

def test_play_and_watch_later_not_indented_under_poster(qapp):
    """The Play/Resume and Watch Later rows live in the OUTER column (parented to the
    _PosterSection itself), NOT inside _content_col (which is indented past the rail)."""
    poster, _ = _build(qapp)

    # Sanity: the poster image IS in the indented content column.
    assert poster._poster_frame.parent() is poster._content_col

    # The action rows are in the outer column → left-aligned with the title below.
    assert poster._primary_action_row.parent() is poster, (
        "primary Play/Resume row must be in the outer column (full-width), not _content_col"
    )
    assert poster._secondary_action_row.parent() is poster, (
        "Watch Later row must be in the outer column (full-width), not _content_col"
    )
    assert poster._primary_action_row.parent() is not poster._content_col
    assert poster._secondary_action_row.parent() is not poster._content_col


def test_action_rows_ordered_below_poster_block(qapp):
    """In the outer layout, the Play/Watch-Later rows come AFTER the poster+rail block."""
    poster, _ = _build(qapp)
    outer = poster.layout()
    widgets = [outer.itemAt(i).widget() for i in range(outer.count())]
    # First widget is the poster+rail wrapper; the two action rows follow it.
    p_idx = widgets.index(poster._primary_action_row)
    s_idx = widgets.index(poster._secondary_action_row)
    assert p_idx > 0, "Play row must be below the poster+rail block"
    assert s_idx > p_idx, "Watch Later row must be below the Play row"


# ---------------------------------------------------------------------------
# 5. Watched badge pinned to the LOWER-right corner
# ---------------------------------------------------------------------------

def test_watched_badge_pinned_upper_right(qapp):
    """The Watched badge sits in the poster's UPPER-right corner.

    This reverses a deliberate earlier move to the lower-right, and is worth
    stating plainly rather than quietly flipping: the V3 design pass settled on
    the top-right, and the reason holds up against real posters — the BOTTOM of
    a poster is where its title artwork almost always is, so a badge pinned
    there lands on the one part of the image that carries information. The top
    corner is the part posters keep clear.
    """
    poster, _ = _build(qapp)
    poster.set_mode(is_live=False)
    poster.poster_label.resize(300, 450)  # width applies; height is the fixed box

    poster.set_watched(True)          # solid badge → visible + repositioned
    poster._reposition_watched_badge()

    margin = poster._BADGE_MARGIN
    bw = poster._watched_badge.width()
    lw = poster.poster_label.width()
    lh = poster.poster_label.height()

    assert poster._watched_badge.x() == lw - bw - margin, "badge must hug the right edge"
    assert poster._watched_badge.y() == margin, "badge must hug the TOP edge"
    # Unambiguously in the upper half, so the assertion above cannot be
    # satisfied by a margin that happens to equal some other offset.
    assert poster._watched_badge.y() < lh // 2, "badge must be in the poster's upper half"


def test_watched_badge_lands_on_the_art_not_the_card_margin(qapp):
    """With centred art the label's right edge is out in the card.

    A badge pinned to the LABEL floats beside the poster rather than on it, so
    it anchors to the pixmap's rect instead.
    """
    from PyQt6.QtGui import QColor, QPixmap

    poster, _ = _build(qapp)
    poster.set_mode(is_live=False)
    poster.poster_label.resize(300, 450)

    art = QPixmap(140, 210)           # portrait, much narrower than the card
    art.fill(QColor("#ff00ff"))
    poster.poster_label.setPixmap(art)
    poster.set_watched(True)
    poster._reposition_watched_badge()

    label = poster.poster_label
    art_left = (label.width() - art.width()) // 2
    art_right = art_left + art.width()
    badge = poster._watched_badge

    assert badge.x() + badge.width() <= art_right, (
        f"badge right edge {badge.x() + badge.width()} is past the art's "
        f"{art_right} — it is floating in the card margin"
    )
    assert badge.x() >= art_left, "badge is left of the art"


# ---------------------------------------------------------------------------
# 6. Play anchored below the live logo footprint
# ---------------------------------------------------------------------------

def test_play_anchored_below_live_logo_footprint(qapp):
    """For a live channel with a logo, the poster keeps its full footprint (#261) and
    the Play row stays below it in the outer column (doesn't collapse up)."""
    from metatv.gui.details_sections import _PosterSection
    from metatv.gui.details_actions import _ActionBar

    cfg = _make_config()
    cache = MagicMock()
    cache.get_image_sync.return_value = None
    poster = _PosterSection(cfg, cache)
    ab = _ActionBar(cfg)
    poster.set_action_buttons(
        favorite=ab.favorite_button, play=ab.play_button, resume=ab.resume_button,
        queue=ab.queue_button, like=ab.like_button,
        not_interested=ab.not_interested_button, dislike=ab.dislike_button,
        watchlist=ab.watchlist_button, monitor=ab.monitor_button,
        clear_epg_link=ab.clear_epg_link_button, hide=ab.hide_button,
    )
    poster.set_mode(is_live=True)
    poster.load_live_logo("http://logo/x.png")

    # #261 footprint preserved: the live logo fills the full poster box.
    assert poster.poster_label.minimumHeight() == poster._POSTER_FIXED_H
    assert poster.poster_label.maximumHeight() == poster._POSTER_FIXED_H
    # Play row shows and is anchored below the poster+rail block (outer column).
    assert not poster._primary_action_row.isHidden(), "Play row must be shown for live"
    assert poster._primary_action_row.parent() is poster
    outer = poster.layout()
    widgets = [outer.itemAt(i).widget() for i in range(outer.count())]
    assert widgets.index(poster._primary_action_row) > 0, (
        "Play row must remain below the poster+rail block for live channels"
    )
