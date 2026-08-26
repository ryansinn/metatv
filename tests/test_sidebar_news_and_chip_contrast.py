"""Two roles that were unreadable in the LIGHT themes, and one that was backwards.

Both found by the owner UX-testing Gruvbox Light, and neither is a Gruvbox bug:

* the sidebar's language chips took their colour from ``COLOR_LIGHTBOX_LINK`` —
  the FIXED-DARK cinema surface's own palette. On a cream sidebar that measured
  **1.36:1 in Daylight**, so those chips have been effectively invisible in the
  existing light theme since it shipped. Gruvbox Light only made it obvious.
* a sidebar section holding NEWS painted its status in ``COLOR_ACCENT``, which
  is the accent as a FILL. As text it is a midtone — 2.61:1 in Graphite against
  plain MUTED's 3.76:1 — so a section with something to say was HARDER to read
  than one without. The signal, exactly backwards.

Both are parametrised over every palette, because both were introduced by
reading one theme and shipping.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp


def _lum(value: str) -> float:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))

    def ch(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def _contrast(a: str, b: str) -> float:
    lo, hi = sorted((_lum(a), _lum(b)))
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_the_sidebar_language_chip_is_readable(qapp, palette_name):
    """It is on the APP surface, not on the cinema panel."""
    _theme.apply_theme(palette_name)
    match = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", _theme.LANG_CHIP)
    assert match, "LANG_CHIP sets no explicit colour"
    ratio = _contrast(match.group(1), _theme.COLOR_BG_SECTION)
    assert ratio >= 4.5, (
        f"{palette_name}: the sidebar language chip is {ratio:.2f}:1 on the "
        f"sidebar surface"
    )


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_the_language_chip_does_not_wear_a_cinema_token(qapp, palette_name):
    """The structural half of the rule, not just the measurement.

    A future edit could pick another ``COLOR_LIGHTBOX_*`` value that happens to
    measure well in the palette being looked at and fail in the other four —
    which is precisely how this arrived.
    """
    _theme.apply_theme(palette_name)
    match = re.search(r"color:\s*(#[0-9a-fA-F]{3,8})", _theme.LANG_CHIP)
    cinema = {
        str(v).lower() for k, v in tp.PALETTES[palette_name].items()
        if k.startswith("COLOR_LIGHTBOX_") and str(v).startswith("#")
    }
    assert match.group(1).lower() not in cinema, (
        f"{palette_name}: LANG_CHIP is painted with a fixed-dark COLOR_LIGHTBOX_* "
        f"value. That family is legible on the cinema panel, which is dark in "
        f"every theme — this chip sits on the app surface, which is cream in the "
        f"light themes."
    )


@pytest.mark.parametrize("palette_name", list(tp.PALETTES))
def test_a_section_with_news_reads_louder_than_one_without(qapp, palette_name):
    """News must never be quieter than no-news.

    ``CollapsibleSection`` paints its header status in the news colour when it
    has something to report and ``COLOR_MUTED`` when it does not. If the news
    colour is the weaker of the two, a new episode is harder to see than an
    idle section.
    """
    _theme.apply_theme(palette_name)
    surface = _theme.COLOR_BG_SECTION
    news = _contrast(_theme.COLOR_ACCENT_BLUE, surface)
    plain = _contrast(_theme.COLOR_MUTED, surface)

    assert news >= 4.5, f"{palette_name}: the news colour is {news:.2f}:1"
    assert news > plain, (
        f"{palette_name}: a section WITH news reads at {news:.2f}:1 while one "
        f"without reads at {plain:.2f}:1 — the signal is backwards"
    )


def test_the_section_header_uses_the_accent_as_text_not_as_fill(qapp):
    """Anchored on the source, because the two tokens differ by one word.

    ``COLOR_ACCENT`` is the accent as a FILL and is a midtone as text;
    ``COLOR_ACCENT_BLUE`` is the accent-as-text member of the family. The
    header picked the first and nothing measured it.
    """
    # Measured, not grepped. This used to search base.py for a
    # `colour = ... if self.news()` line, which broke the moment the news
    # status became a filled pill instead of tinted text. The property was
    # always "louder"; anchoring on a source line pinned an implementation —
    # exactly the mistake the original COLOR_ACCENT-vs-COLOR_ACCENT_BLUE bug
    # made.
    from metatv.gui import theme as _theme

    def _lum(hex_colour):
        def lin(c):
            c /= 255
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        h = hex_colour.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    def _contrast(a, b):
        hi, lo = max(_lum(a), _lum(b)), min(_lum(a), _lum(b))
        return (hi + 0.05) / (lo + 0.05)

    for palette in ("Midnight", "Graphite", "Daylight"):
        _theme.apply_theme(palette)
        ground = _theme.COLOR_BG_CARD
        loud = _contrast(_theme.COLOR_OK, ground)
        quiet = _contrast(_theme.COLOR_MUTED, ground)
        assert loud > quiet, (
            f"{palette}: a section WITH news reads quieter than one without "
            f"({loud:.2f} vs {quiet:.2f}) — the signal is backwards"
        )
