"""The details pane draws ratings as five stars and favourites as a coloured heart.

Owner, 2026-10-19. Asserts what is PAINTED: the star glyph codepoints in the
rating label, and the heart's pixels in the favourite colour.
"""
import qtawesome as qta
from PyQt6.QtGui import QColor

from metatv.gui import theme as _theme
from metatv.gui.details_title import rating_stars, _rating_rich_text
from tests.conftest import destroy_widget


def test_half_steps_map_each_point_to_half_a_star():
    assert rating_stars(7.4) == ["rating_star"] * 3 + ["rating_half"] + ["rating_empty"]
    assert rating_stars(0.2) == ["rating_empty"] * 5
    assert rating_stars(9.8) == ["rating_star"] * 5
    assert rating_stars(6.5) == ["rating_star"] * 3 + ["rating_empty"] * 2  # banker's round: 6
    assert len(rating_stars(12)) == 5


def test_the_rating_label_paints_five_star_glyphs(qapp):
    html = _rating_rich_text(7.4)
    want = [qta.charmap(k) for k in ("mdi6.star",) * 3 + ("mdi6.star-half-full", "mdi6.star-outline")]
    got = [chr(int(h, 16)) for h in __import__("re").findall(r"&#x([0-9a-f]+);", html)]
    assert got == want
    assert _theme.COLOR_GOLD in html


def test_a_favourite_is_a_heart_in_the_favourite_colour(qapp):
    from metatv.gui.details_actions import _ActionBar
    from tests.test_details_rail_layout_polish import _make_config
    bar = _ActionBar(_make_config())
    try:
        bar.update_favorite(True)
        img = bar.favorite_button.icon().pixmap(18, 18).toImage()
        want = QColor(_theme.COLOR_FAVORITE)
        painted = [img.pixelColor(x, y) for x in range(img.width()) for y in range(img.height())
                   if img.pixelColor(x, y).alpha() > 200]
        assert painted, "the favourite icon painted nothing"
        assert all(abs(c.red() - want.red()) < 8 and abs(c.blue() - want.blue()) < 8 for c in painted)
        bar.update_favorite(False)
        img = bar.favorite_button.icon().pixmap(18, 18).toImage()
        assert not any(abs(img.pixelColor(x, y).red() - want.red()) < 8
                       and abs(img.pixelColor(x, y).blue() - want.blue()) < 8
                       and img.pixelColor(x, y).alpha() > 200
                       for x in range(18) for y in range(18)), "unfavourited must not be pink"
    finally:
        destroy_widget(bar)
