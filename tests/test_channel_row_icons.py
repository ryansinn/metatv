"""Channel rows draw their leading marks as mdi6 icons (one icon set, 2026-10-19).

The favourite is a heart — pink when favourited, muted outline otherwise — and
the playback state is an icon, with the not-started dot left as typography.
Asserts what the delegate PAINTS, on a real image.
"""
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont, QImage, QPainter

from metatv.gui import theme as _theme
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from metatv.gui.channel_list_roles import (
    FAV_GLYPH_ROLE, MATCH_MARKER_ROLE, PLAYBACK_GLYPH_COLOR_ROLE, PLAYBACK_GLYPH_ROLE,
)


class _Index:
    def __init__(self, data):
        self._data = data

    def data(self, role):
        return self._data.get(role)


def _paint(index):
    img = QImage(200, 24, QImage.Format.Format_ARGB32)
    img.fill(QColor("#000000"))
    p = QPainter(img)
    x = ChannelRowDelegate()._paint_leading_glyphs(p, QRect(0, 0, 200, 24), index, QFont())
    p.end()
    return img, x


def _has(img, color, x0=0, x1=200):
    want = QColor(color)
    return any(abs(img.pixelColor(x, y).red() - want.red()) < 10
               and abs(img.pixelColor(x, y).green() - want.green()) < 10
               and abs(img.pixelColor(x, y).blue() - want.blue()) < 10
               for x in range(x0, x1) for y in range(24))


def test_a_favourite_row_paints_a_pink_heart(qapp):
    img, _ = _paint(_Index({FAV_GLYPH_ROLE: "favorite", PLAYBACK_GLYPH_ROLE: "·"}))
    assert _has(img, _theme.COLOR_FAVORITE, 0, 20)


def test_a_plain_row_paints_no_pink(qapp):
    img, _ = _paint(_Index({FAV_GLYPH_ROLE: "unfavorite", PLAYBACK_GLYPH_ROLE: "·"}))
    assert not _has(img, _theme.COLOR_FAVORITE)


def test_in_progress_is_an_icon_in_the_resume_colour(qapp):
    color = _theme.COLOR_PLAYBACK_IN_PROGRESS
    img, _ = _paint(_Index({FAV_GLYPH_ROLE: "unfavorite",
                              PLAYBACK_GLYPH_ROLE: "playback_in_progress",
                              PLAYBACK_GLYPH_COLOR_ROLE: color}))
    assert _has(img, color, 16, 60)


def test_a_new_match_adds_a_mark_and_moves_the_title(qapp):
    _, without = _paint(_Index({FAV_GLYPH_ROLE: "unfavorite", PLAYBACK_GLYPH_ROLE: "·"}))
    _, with_mark = _paint(_Index({FAV_GLYPH_ROLE: "unfavorite", PLAYBACK_GLYPH_ROLE: "·",
                                    MATCH_MARKER_ROLE: "new_match"}))
    assert with_mark > without
