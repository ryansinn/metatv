"""The two contrast failures the UI audit opened with (#297).

Owner: "these button backgrounds on the poster rail are shitty" and, after the
palette restructure shipped, "the rail buttons still look like shit."

Both true, and the second was mine: the Radix/DTCG work changed where token
VALUES come from and never touched the ROLE definitions, so the defect survived
it — and briefly got worse, because the two tokens involved landed on
neighbouring neutrals.

    rail buttons        1.97:1  ->  1.13:1 after the restructure
    placeholder tiles   2.10:1  ->  1.21:1

against a 3:1 floor for UI chrome. The cause was never the palette: DETAIL_RAIL_BTN
used ``OVERLAY_40`` — a 40% white wash, i.e. a HOVER effect — as its RESTING
fill, so the button had no surface of its own and every state looked filled. The
placeholder tile likewise painted ``COLOR_FAINT``, making a MISSING image the
loudest object in its row.

Asserts the composited result in every palette, because an overlay's contrast
cannot be read off the token — you have to composite it onto the surface it
lands on, which is exactly the step that hid this for so long.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme_palettes as tp

CHROME_FLOOR = 3.0


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _rgb(value: str) -> tuple[int, int, int]:
    v = value.strip()
    if v.startswith("#"):
        h = v.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)", v)
    assert m, f"unparseable colour {value!r}"
    return tuple(int(m.group(i)) for i in (1, 2, 3))


def _alpha(value: str) -> float:
    m = re.match(r"rgba\([^,]+,[^,]+,[^,]+,\s*([\d.]+)\)", value.strip())
    return float(m.group(1)) if m else 1.0


def _composite(fg: str, bg: str) -> tuple[int, int, int]:
    """What an alpha fill ACTUALLY renders as over *bg*."""
    a = _alpha(fg)
    f, b = _rgb(fg), _rgb(bg)
    return tuple(round(a * f[i] + (1 - a) * b[i]) for i in range(3))


def _lum(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_lin(c / 255) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b) -> float:
    la, lb = _lum(a if isinstance(a, tuple) else _rgb(a)), _lum(b if isinstance(b, tuple) else _rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.mark.parametrize("palette", list(tp.PALETTES))
def test_rail_button_glyph_is_legible_at_rest(palette):
    """The owner's case. A rail button at rest must read as a button."""
    P = tp.PALETTES[palette]
    fill = _composite(P["COLOR_BG_CARD"], P["COLOR_BG_SECTION"])
    ratio = _contrast(P["COLOR_TEXT"], fill)
    assert ratio >= CHROME_FLOOR, (
        f"{palette}: rail glyph {P['COLOR_TEXT']} on its resting fill is "
        f"{ratio:.2f}:1 — below the {CHROME_FLOOR}:1 floor for UI chrome"
    )


@pytest.mark.parametrize("palette", list(tp.PALETTES))
def test_the_resting_fill_is_not_an_overlay_wash(palette):
    """The actual defect, guarded directly.

    An OVERLAY_* token is a transient hover effect. Used as a resting fill it
    composites to an off-palette grey that no palette author chose and none can
    change — which is how the rail ended up at half the legibility floor while
    every token in the file looked fine on its own.
    """
    from metatv.gui import theme

    assert "OVERLAY_" not in _role_source("DETAIL_RAIL_BTN"), (
        "DETAIL_RAIL_BTN uses an overlay wash as its resting background again"
    )
    assert theme.COLOR_BG_CARD in theme.DETAIL_RAIL_BTN


def _role_source(name: str) -> str:
    """The resting (non-pseudo-state) clause of a role constant."""
    from metatv.gui import theme
    sheet = getattr(theme, name)
    return sheet.split("QPushButton:")[0]


@pytest.mark.parametrize("palette", list(tp.PALETTES))
def test_placeholder_letter_is_legible_on_its_tile(palette):
    """A missing poster must still be readable — and must not shout."""
    P = tp.PALETTES[palette]
    ratio = _contrast(P["COLOR_TEXT"], P["COLOR_BG_CARD"])
    assert ratio >= CHROME_FLOOR, (
        f"{palette}: placeholder letter is {ratio:.2f}:1 on its tile"
    )


@pytest.mark.parametrize("palette", list(tp.PALETTES))
def test_the_placeholder_tile_recedes_rather_than_shouts(palette):
    """Absence should read as absence.

    The tile must sit CLOSER to the list background than the row's text does —
    a missing image has no business being the highest-contrast object in its
    row, which is what COLOR_FAINT made it.
    """
    P = tp.PALETTES[palette]
    tile_vs_bg = _contrast(P["COLOR_BG_CARD"], P["COLOR_BG_SECTION"])
    text_vs_bg = _contrast(P["COLOR_TEXT"], P["COLOR_BG_SECTION"])
    assert tile_vs_bg < text_vs_bg, (
        f"{palette}: the placeholder tile ({tile_vs_bg:.2f}:1) stands out more "
        f"than the title text ({text_vs_bg:.2f}:1) it sits beside"
    )


def test_the_accent_fill_still_means_active():
    """Fills were meaningless when every state had one. :checked must differ
    from the resting surface, or 'is this favourited?' is unanswerable."""
    from metatv.gui import theme

    resting = _role_source("DETAIL_RAIL_BTN")
    checked = theme.DETAIL_RAIL_BTN.split("QPushButton:checked {")[1].split("}")[0]
    assert theme.COLOR_BG_CARD not in checked
    assert theme.OVERLAY_ACCENT_35 in checked
    assert theme.COLOR_BG_CARD in resting
