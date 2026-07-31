"""Shared "Similar-titles" badge renderer — one builder for every surface.

A single source of truth for the compact badge cluster shown on a title card /
row: a meta line (language/region + ★rating, with the year on the right) above a
state-glyph line that shows only the ACTIVE engagement states — liked (👍), in
Watch Later (📋), favorited (★), watched (green ✓).

Introduced by the Explore trail-map (#0176): the lightbox similar-strip cards
(``similar_lightbox_card.py``) and the trail-map rows (``trail_map_view.py``) both
render badges from the same ``{lang, rating, year, user_rating, in_queue,
is_favorite, watched}`` dict, so state reads identically wherever it appears
(reuse-before-reinvent — this replaces the per-surface copy the mockup exhibited).

Every glyph pairs a distinct SHAPE with a tooltip, so state is never conveyed by
colour alone (a11y: colour-not-alone).
"""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from metatv.gui import icons as _icons
from metatv.gui import theme as _theme


def make_sim_badges(item: dict, width: int | None = None, show_year: bool = True) -> QWidget:
    """Build a badge cluster from the fields a card/row threads in.

    Args:
        item: A dict carrying the display + state fields — ``lang`` (language/region
            string), ``rating`` (metadata ★ score), ``year``, ``user_rating`` (+1
            liked), ``in_queue``, ``is_favorite``, ``watched``. Any absent key is
            treated as unset.
        width: Optional fixed width for the cluster (the lightbox strip cards pass
            the poster width so the badges align under the poster). ``None`` lets it
            size to its content (the trail-map rows want that).
        show_year: Whether to render the year on the right of the meta line. The
            lightbox strip cards keep it (their only year); trail-map rows pass
            ``False`` because they show the year on their own title line (else it
            would appear twice).

    Returns:
        A ``QWidget`` holding the meta line above the state-glyph line.
    """
    wrap = QWidget()
    if width is not None:
        wrap.setFixedWidth(width)
    box = QVBoxLayout(wrap)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(1)

    # Meta line: language/region + rating (left), year (right).
    meta = QHBoxLayout()
    meta.setContentsMargins(0, 0, 0, 0)
    meta.setSpacing(6)
    lang = (item.get("lang") or "").strip()
    if lang:
        lang_lbl = QLabel(lang)
        # The ONE canonical bordered language/region chip — shared with the
        # trail-map detail strip (single source of truth), so the lang badge reads
        # identically on the lightbox strip AND the trail-map rows.
        lang_lbl.setStyleSheet(_theme.LANG_CHIP)
        lang_lbl.setToolTip(f"Language / region: {lang}")
        meta.addWidget(lang_lbl)
    rating = item.get("rating")
    if rating:
        star = QLabel(f"{_icons.rating_star_icon}{rating}")
        star.setStyleSheet(_theme.LIGHTBOX_SIM_RATING)
        star.setToolTip(f"Rating: {rating}")
        meta.addWidget(star)
    meta.addStretch()
    year = item.get("year")
    if show_year:
        year_lbl = QLabel(str(year) if year else "")
        year_lbl.setStyleSheet(_theme.LIGHTBOX_SIM_YEAR)
        meta.addWidget(year_lbl)
    box.addLayout(meta)

    # State-glyph line: only the active states (distinct shape + tooltip each).
    glyphs = QHBoxLayout()
    glyphs.setContentsMargins(0, 0, 0, 0)
    glyphs.setSpacing(5)
    for present, glyph, style, tip in (
        (item.get("user_rating") == 1, _icons.like_icon,
         _theme.LIGHTBOX_SIM_GLYPH_LIKE, "You liked this"),
        (bool(item.get("in_queue")), _icons.queue_icon,
         _theme.LIGHTBOX_SIM_GLYPH_QUEUE, "In Watch Later"),
        (bool(item.get("is_favorite")), _icons.favorite_icon,
         _theme.LIGHTBOX_SIM_GLYPH_FAV, "In Favorites"),
        (bool(item.get("watched")), _icons.watched_icon,
         _theme.LIGHTBOX_SIM_GLYPH_WATCHED, "Watched"),
    ):
        if present:
            g = QLabel(glyph)
            g.setStyleSheet(style)
            g.setToolTip(tip)
            glyphs.addWidget(g)
    glyphs.addStretch()
    box.addLayout(glyphs)

    return wrap
