"""Rendered-appearance gate for the view chips and the surface ramp (#298).

Three owner-reported defects, each measured rather than described:

1. The primary view chips (Search / EPG / Recommended / Discover / Recipe) were
   unreadable in BOTH states, in every dark palette.
2. Daylight had no visible boundary between the app chrome and the lists.
3. Midnight and Graphite "seem nearly identical" — their surface ramps had
   converged to within 1.001:1 of each other.

Every threshold below fails against the pre-#298 palettes; the pre-change value
is recorded in each docstring.
"""

from __future__ import annotations

import re

import pytest
from PyQt6.QtGui import QColor

from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.filter_bar import ToggleChip

PALETTES = list(tp.PALETTES.keys())
DARK = [n for n, kind in tp.PALETTE_KIND.items() if kind == "dark"]

#: Two surfaces this close read as one undifferentiated field. Deliberately
#: loose — the point is that a boundary EXISTS, not that it shouts.
_MIN_SEPARATION = 1.05


def _luminance(value: str) -> float:
    text = QColor(str(value)).name().lstrip("#")
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(text[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(a, b) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _chip_colors(chip: ToggleChip) -> tuple[str, str]:
    """(background, foreground) actually set on the chip's QPushButton block.

    Read off the applied stylesheet rather than from the tokens the code MEANT
    to use — a hardcoded ``color: white`` is invisible to any test that checks
    tokens, and a hardcoded ``color: white`` is precisely what this defect was.
    """
    sheet = chip.styleSheet()
    block = sheet.split("QPushButton:hover")[0]
    bg = re.search(r"background-color:\s*([^;]+);", block)
    fg = re.search(r"[^-]color:\s*([^;]+);", block)
    assert bg and fg, f"could not read chip colours from {block!r}"
    return bg.group(1).strip(), fg.group(1).strip()


# ---------------------------------------------------------------------------
# 1. The view chips
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_selected_view_chip_text_is_readable(qapp, palette_name):
    """PRE-#298 THIS FAILED AT 1.31:1 in both dark palettes: the chip filled
    with ``COLOR_ACCENT_BLUE`` — which is ``indigo.12``, a NEAR-WHITE lavender
    in a dark palette — and wrote a hardcoded ``color: white`` on it.
    """
    _theme.apply_theme(palette_name)
    bg, fg = _chip_colors(ToggleChip("Search", enabled=True))
    ratio = _contrast(fg, bg)
    assert ratio >= 4.5, (
        f"{palette_name}: selected view chip is {ratio:.2f}:1 ({fg} on {bg})"
    )


@pytest.mark.parametrize("palette_name", PALETTES)
def test_unselected_view_chip_text_is_readable(qapp, palette_name):
    """PRE-#298 THIS FAILED AT 2.30:1: the resting chip filled with
    ``COLOR_SURFACE_LIGHT_2``, one of the deliberately-fixed-LIGHT "highlight
    chip" surfaces that stay light in EVERY palette by design — a pale slab in
    a dark app — with ``COLOR_MUTED_2`` written on it.
    """
    _theme.apply_theme(palette_name)
    bg, fg = _chip_colors(ToggleChip("EPG", enabled=False))
    ratio = _contrast(fg, bg)
    assert ratio >= 4.5, (
        f"{palette_name}: unselected view chip is {ratio:.2f}:1 ({fg} on {bg})"
    )


@pytest.mark.parametrize("palette_name", PALETTES)
def test_view_chip_carries_no_colour_literal(qapp, palette_name):
    """The literal was not incidental to the bug, it WAS the bug: a hardcoded
    colour cannot track a palette, so the chip kept writing white as the fill
    beneath it changed from a dark blue to a near-white lavender."""
    _theme.apply_theme(palette_name)
    for enabled in (True, False):
        sheet = ToggleChip("Search", enabled=enabled).styleSheet()
        assert "white" not in sheet.lower(), f"{palette_name}: colour literal in chip sheet"


def test_view_chip_follows_a_live_theme_switch(qapp):
    """Qt caches the RENDERED sheet, so a chip that called ``setStyleSheet``
    directly kept the old palette's colours after a switch. Registered through
    ``theme.style_fn``, it is re-invoked and re-reads the tokens."""
    _theme.apply_theme("Midnight")
    chip = ToggleChip("Search", enabled=True)
    midnight_bg, _fg = _chip_colors(chip)
    _theme.apply_theme("Daylight")
    daylight_bg, _fg = _chip_colors(chip)
    assert QColor(midnight_bg).name() != QColor(daylight_bg).name()
    assert QColor(daylight_bg).name() == QColor(str(_theme.COLOR_ACCENT)).name()


# ---------------------------------------------------------------------------
# 2. Chrome vs content
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_the_list_is_distinguishable_from_the_app_chrome(qapp, palette_name):
    """PRE-#298 DAYLIGHT FAILED AT 1.023:1 — the chrome (#f9f9fb) and the list
    (#fcfcfd) were one undifferentiated white field (owner report).

    A light theme has no step ABOVE ``{neutral.1}`` to give the list, so the
    separation has to come from moving the CHROME down, which is what
    ``surface.base`` moving to ``{neutral.3}`` does.
    """
    _theme.apply_theme(palette_name)
    ratio = _contrast(_theme.COLOR_BG_DEEP, _theme.COLOR_BG_SECTION)
    assert ratio >= _MIN_SEPARATION, (
        f"{palette_name}: list {_theme.COLOR_BG_DEEP} vs chrome "
        f"{_theme.COLOR_BG_SECTION} is only {ratio:.3f}:1"
    )


@pytest.mark.parametrize("palette_name", DARK)
def test_dark_palettes_recess_the_list_below_the_chrome(qapp, palette_name):
    """Direction, not just distance: content sits INTO the shell in a dark
    theme (and, conversely, stands out of it in a light one)."""
    _theme.apply_theme(palette_name)
    assert _luminance(_theme.COLOR_BG_DEEP) < _luminance(_theme.COLOR_BG_SECTION)


def test_light_palette_puts_content_above_the_chrome(qapp):
    _theme.apply_theme("Daylight")
    assert _luminance(_theme.COLOR_BG_DEEP) > _luminance(_theme.COLOR_BG_SECTION)


# ---------------------------------------------------------------------------
# 3. Two dark themes must actually be two themes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("token", ["COLOR_BG_DEEP", "COLOR_BG_SECTION", "COLOR_BG_CARD"])
def test_midnight_and_graphite_surfaces_are_distinguishable(qapp, token):
    """PRE-#298 THIS FAILED AT 1.001-1.003:1 — Graphite is documented as the
    "distinctly LIGHTER, fully neutral" dark theme, but its surfaces resolved
    to #111111/#191919 against Midnight's #111113/#18191b: a difference of two
    points, invisible on any display (owner report: "midnight and graphite seem
    nearly identical").

    This is the same failure #251 fixed once already, re-introduced by the
    scale restructure — Graphite differed only in the hues it picked, and the
    surfaces are what dominate the impression of a theme.
    """
    midnight = tp.PALETTES["Midnight"][token]
    graphite = tp.PALETTES["Graphite"][token]
    ratio = _contrast(midnight, graphite)
    assert ratio >= _MIN_SEPARATION, (
        f"{token}: Midnight {midnight} vs Graphite {graphite} is only {ratio:.3f}:1"
    )


@pytest.mark.parametrize("palette_name", PALETTES)
def test_the_surface_ramp_stays_ordered(qapp, palette_name):
    """dim -> base -> container must stay monotonic in the palette's own
    direction. Shifting a ramp is easy to get half-right, and a container that
    lands on the same step as its panel makes every resting control vanish."""
    _theme.apply_theme(palette_name)
    steps = [_luminance(_theme.COLOR_BG_DEEP), _luminance(_theme.COLOR_BG_SECTION),
             _luminance(_theme.COLOR_BG_CARD)]
    expected = sorted(steps, reverse=tp.PALETTE_KIND[palette_name] == "light")
    assert steps == expected, f"{palette_name}: surface ramp is not monotonic: {steps}"
    assert len(set(steps)) == 3, f"{palette_name}: two surfaces landed on one value"
