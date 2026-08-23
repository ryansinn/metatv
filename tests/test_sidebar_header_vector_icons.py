"""Sidebar section headers draw a themed vector glyph, not a fixed-colour emoji.

The headers carried their icon as an emoji inside the title text. An emoji
ignores CSS ``color``, so those glyphs were the last part of the sidebar that
could not follow the palette, and they rasterise differently on every platform.

These assert the DECODED PIXELS of the embedded image, not the presence of an
``<img>`` tag. A tag can be present and painted in last palette's colour — that
is precisely the bug this converts away from, and a tag-presence check passes on
it. Each test decodes the base64 PNG and reads the colour off the glyph.
"""
from __future__ import annotations

import base64
import re
from collections import Counter

import pytest

pytest.importorskip("PyQt6")
pytest.importorskip("qtawesome")

from PyQt6.QtGui import QColor, QImage  # noqa: E402

_SECTIONS = ["history", "favorites", "recommended"]


def _section(kind, config, db):
    from metatv.gui.sidebar.favorites import FavoritesSection
    from metatv.gui.sidebar.history import HistorySection
    from metatv.gui.sidebar.recommended import RecommendedSection
    return {"history": HistorySection, "favorites": FavoritesSection,
            "recommended": RecommendedSection}[kind](config, db)


@pytest.fixture
def build(qtbot, tmp_path):
    """Real section objects — the header HTML is built in their constructor."""
    from unittest.mock import MagicMock
    from metatv.core.config import Config

    def _build(kind):
        section = _section(kind, Config(config_dir=tmp_path), MagicMock())
        qtbot.addWidget(section)
        return section
    return _build


#: Alpha floor for "this pixel is glyph body, not a feathered edge". A 13px
#: outline glyph never reaches full opacity — mdi6.star-check-outline peaks at
#: 232 — so a 250 floor finds nothing at all and the measurement silently has
#: no pixels to look at.
_BODY_ALPHA = 128

#: Antialiasing rounds a channel by a unit or two either way. The dominant
#: value is exact; its neighbours are ±1.
_CHANNEL_TOLERANCE = 2


def _glyph_pixels(html: str) -> list[QColor]:
    """Every glyph-body pixel of the icon embedded in *html*."""
    match = re.search(r'src="data:image/png;base64,([^"]+)"', html)
    assert match, f"no embedded icon in the header HTML: {html[:120]!r}"
    image = QImage()
    assert image.loadFromData(base64.b64decode(match.group(1)), "PNG"), \
        "the embedded payload is not a decodable PNG"
    # Non-premultiplied, so a partly-transparent pixel still carries its true
    # RGB rather than one scaled by its own alpha.
    image = image.convertToFormat(QImage.Format.Format_ARGB32)

    return [
        QColor(image.pixelColor(x, y))
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() >= _BODY_ALPHA
    ]


def _dominant(html: str) -> tuple[int, int, int]:
    pixels = _glyph_pixels(html)
    assert pixels, "the icon decoded to nothing opaque — it painted no glyph"
    counts = Counter((p.red(), p.green(), p.blue()) for p in pixels)
    return counts.most_common(1)[0][0]


def _matches(got: tuple[int, int, int], want: QColor) -> bool:
    return all(abs(g - w) <= _CHANNEL_TOLERANCE for g, w in
               zip(got, (want.red(), want.green(), want.blue())))


@pytest.mark.parametrize("kind", _SECTIONS)
def test_the_header_icon_is_an_image_not_an_emoji(build, kind):
    from metatv.gui.sidebar import base as sidebar_base

    section = build(kind)
    html = section._title_html()
    assert "<img" in html, f"{kind} header still renders a text glyph"
    # The emoji it replaced must be gone, not merely joined by an image.
    assert section.icon not in html, (
        f"{kind} header carries BOTH the vector icon and the {section.icon!r} "
        "emoji"
    )
    assert sidebar_base  # imported for the failure message's sake


@pytest.mark.parametrize("kind", _SECTIONS)
def test_the_glyph_is_painted_in_the_sections_own_colour(build, kind):
    """The pixels must match what header_tint() asks for.

    Favourites is the section that makes this worth measuring: it is the only
    one with a tint, and the gold used to be applied by wrapping the emoji in a
    <span style="color:…"> — which an emoji ignores, so the "gold" star was
    never actually gold.
    """
    from metatv.gui import theme as _theme

    section = build(kind)
    expected = QColor(section.header_tint() or _theme.COLOR_TEXT)
    got = _dominant(section._title_html())

    assert _matches(got, expected), (
        f"{kind} header glyph painted rgb{got}, expected "
        f"rgb({expected.red()}, {expected.green()}, {expected.blue()}) "
        f"from {'header_tint()' if section.header_tint() else 'COLOR_TEXT'}"
    )


def test_favorites_is_actually_gold_and_the_others_are_not(build):
    """The one section with a tint must differ from the untinted ones.

    Guards the failure where header_tint() is ignored and every header comes
    out the same colour — each test above would still pass if COLOR_GOLD and
    COLOR_TEXT happened to be compared against the wrong baseline.
    """
    from metatv.gui import theme as _theme

    gold = _dominant(build("favorites")._title_html())
    plain = _dominant(build("history")._title_html())
    assert gold != plain, "the Favourites star is not tinted differently"
    assert _matches(gold, QColor(_theme.COLOR_GOLD))


@pytest.mark.parametrize("kind", _SECTIONS)
def test_the_glyph_repaints_when_the_palette_changes(build, kind):
    """A rasterised PNG cannot recolour itself — the builder must re-run.

    This is the assertion that makes style_fn registration load-bearing rather
    than decorative: without it the header keeps the PNG it baked at
    construction, in the colour of whatever palette was active back then.
    """
    from metatv.gui import theme as _theme
    from metatv.gui import theme_palettes as _palettes

    section = build(kind)
    before_theme = _theme.CURRENT_PALETTE_NAME if hasattr(
        _theme, "CURRENT_PALETTE_NAME") else None

    others = [n for n in _palettes.PALETTES if n != "Midnight"]

    def _expected() -> QColor:
        return QColor(section.header_tint() or _theme.COLOR_TEXT)

    try:
        _theme.apply_theme("Midnight")
        want_midnight = _expected()
        midnight = _dominant(section.title_label.text())
        assert _matches(midnight, want_midnight), (
            f"{kind} header glyph is rgb{midnight} under Midnight, expected "
            f"{want_midnight.name()}"
        )

        for other in others:
            _theme.apply_theme(other)
            want = _expected()
            got = _dominant(section.title_label.text())
            assert _matches(got, want), (
                f"{kind} header glyph is rgb{got} under {other}, expected "
                f"{want.name()} — the icon was rasterised once and never "
                "re-rendered"
            )
            # Only demand a visible CHANGE where the token actually moved:
            # COLOR_GOLD is #ffc53d in Midnight and Daylight alike, so a
            # blanket "it must differ" would fail on correct behaviour.
            if want.name() != want_midnight.name():
                assert got != midnight, (
                    f"{kind} header glyph stayed rgb{midnight} moving to "
                    f"{other}, where the colour should be {want.name()}"
                )
    finally:
        _theme.apply_theme(before_theme or "Midnight")
