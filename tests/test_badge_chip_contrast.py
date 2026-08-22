"""The shared row badges, measured on the surface they land on.

Why this needs its own file
---------------------------
``test_stylesheet_contrast_conformance.py`` walks the role constants in
``theme.py``. These chips are composed in ``badge_utils.py`` instead, so no
contrast test could see them — and they were wrong: ``_chip_base()`` hardcoded
``color: white`` over fills that are translucent tints OF THE APP SURFACE, so
in Daylight the region, platform and audio chips rendered white-on-near-white
at 1.59-1.75:1. On the main results rows, in the light theme, invisible.

That is the general hole: **a stylesheet built in a widget module is unmeasured
today.** This file closes it for the badge family specifically, because these
are shared renderers used on every row — the highest-traffic surface in the
app. The remaining inline-composed sheets are tracked as a shrinking budget by
``test_theme_style_registry.py``; measuring all of them needs the surface each
one lands on, which is a per-site question.

Why ``COLOR_TEXT_HI`` and not ``on_fill()``
-------------------------------------------
``theme.on_fill()`` is for text on a SOLID fill, where the fill carries the
palette. These fills are translucent tints of the app surface, so the surface's
own text ramp is the correct answer and inverts with the theme for free.
Measured: ``COLOR_ON_ACCENT`` here would be 1.55-1.79:1 — the right token for
the wrong kind of background.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import badge_utils as _badges
from metatv.gui import theme as _theme

PALETTES = ["Midnight", "Graphite", "Daylight"]
FLOOR = 4.5

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_RGBA = re.compile(
    r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)"
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _restore_theme():
    previous = _theme.current_theme()
    yield
    _theme.apply_theme(previous)


def _rgba(value: str) -> tuple[float, float, float, float]:
    """Parse ``#rgb``/``#rrggbb``/``rgb()``/``rgba()`` into (r, g, b, alpha)."""
    value = value.strip()
    m = _RGBA.match(value)
    if m:
        alpha = float(m.group(4)) if m.group(4) else 1.0
        return (float(m.group(1)), float(m.group(2)), float(m.group(3)), alpha)
    h = value.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(float(int(h[i:i + 2], 16)) for i in (0, 2, 4)) + (1.0,)


def _composite(fg, bg):
    """Alpha-composite *fg* over opaque *bg*.

    A translucent fill is composited onto the surface BEFORE the text lands on
    it. Treating ``rgba(...,0.12)`` as opaque is precisely how a 1.6:1 chip
    reads as fine.
    """
    r, g, b, a = fg
    br, bg_, bb, _ = bg
    return (r * a + br * (1 - a), g * a + bg_ * (1 - a), b * a + bb * (1 - a), 1.0)


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(colour) -> float:
    r, g, b, _ = colour
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(fg, bg) -> float:
    lf, lb = _lum(fg), _lum(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def _declared(sheet: str, prop: str) -> str | None:
    for m in re.finditer(rf"(?<![a-z-]){prop}:\s*([^;]+);", sheet):
        value = m.group(1).strip()
        if _HEX.search(value) or _RGBA.match(value):
            return value
    return None


def _chip_styles() -> dict[str, str]:
    """The three chip stylesheets ``badge_utils`` composes."""
    return {
        "region": _badges._region_style(),
        "platform": _badges._platform_style(),
        "audio": _badges._audio_style(),
    }


@pytest.mark.parametrize("palette", PALETTES)
def test_every_row_badge_chip_is_legible_in_every_palette(qapp, palette):
    """FAILS pre-fix in Daylight — all three chips between 1.59 and 1.75:1."""
    _theme.apply_theme(palette)
    surface = _rgba(_theme.COLOR_BG_CARD)

    failures = []
    for name, sheet in _chip_styles().items():
        fg = _declared(sheet, "color")
        bg = _declared(sheet, "background")
        assert fg and bg, f"{name} chip declares no colour pair: {sheet}"
        ratio = _contrast(_rgba(fg), _composite(_rgba(bg), surface))
        if ratio < FLOOR:
            failures.append(f"{name}: {fg} on {bg} over {_theme.COLOR_BG_CARD} "
                            f"= {ratio:.2f}:1")

    assert not failures, (
        f"{palette}: row badge chip(s) below {FLOOR}:1 —\n  " + "\n  ".join(failures)
    )


def test_the_chip_foreground_is_not_a_fixed_colour(qapp):
    """The text must MOVE between palettes; a fixed one is the bug returning.

    A chip whose fill tracks the theme but whose text does not is legible in
    whichever palette it was eyeballed in and wrong in the other.
    """
    seen = set()
    for palette in PALETTES:
        _theme.apply_theme(palette)
        seen.add(_declared(_badges._region_style(), "color"))
    assert len(seen) > 1, (
        f"the chip text is the same colour in every palette ({seen}) — it "
        f"cannot be correct on both a light and a dark surface"
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_on_fill_beats_the_floor_for_every_solid_status_fill(qapp, palette):
    """``theme.on_fill`` must actually deliver on the fills callers pass it.

    These are the fills that carried hardcoded white before: white on Midnight's
    mint ``COLOR_OK`` measured 1.88:1 and on the orange PPV accent 2.51:1.
    """
    _theme.apply_theme(palette)
    fills = [
        "COLOR_OK", "COLOR_ACCENT", "COLOR_PPV_ACCENT", "COLOR_ACCENT_GREEN",
    ]
    failures = []
    for name in fills:
        fill = getattr(_theme, name)
        ratio = _contrast(_rgba(_theme.on_fill(fill)), _rgba(fill))
        if ratio < FLOOR:
            failures.append(f"{name} ({fill}) = {ratio:.2f}:1")
    assert not failures, (
        f"{palette}: on_fill() below {FLOOR}:1 —\n  " + "\n  ".join(failures)
    )


def test_on_fill_flips_with_the_fill_not_the_palette(qapp):
    """The whole point: the answer follows the background, not the theme."""
    _theme.apply_theme("Midnight")
    assert _theme.on_fill("#ffffff") == _theme.COLOR_ON_FILL_DARK
    assert _theme.on_fill("#000000") == _theme.COLOR_ON_FILL_LIGHT
    _theme.apply_theme("Daylight")
    assert _theme.on_fill("#ffffff") == _theme.COLOR_ON_FILL_DARK
    assert _theme.on_fill("#000000") == _theme.COLOR_ON_FILL_LIGHT


def test_on_fill_handles_a_runtime_colour(qapp):
    """Callers pass provider colours and quality hues, not only tokens."""
    _theme.apply_theme("Midnight")
    assert _theme.on_fill("#f0e68c") == _theme.COLOR_ON_FILL_DARK   # light khaki
    assert _theme.on_fill("#2b1a4d") == _theme.COLOR_ON_FILL_LIGHT  # deep violet
    assert _theme.on_fill("#fff") == _theme.COLOR_ON_FILL_DARK      # short hex
