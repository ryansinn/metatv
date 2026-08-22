"""Every lightbox role, measured against the surface it ACTUALLY paints on.

The gap this closes
-------------------
``test_stylesheet_contrast_conformance.py`` measures roles against the *app*
background, and its own allowlist says so::

    **The lightbox / trail-map family (20 entries).** These sit on the
    deliberately fixed-dark "cinema" backdrop, not on the app surface this test
    assumes. Their numbers here are measured against the wrong thing and should
    not be acted on until the test can be told which surface a role lands on.

That exemption was read as "these are fine, we just can't measure them". They
were not fine. Measured against the card they actually land on, Daylight was
broken outright:

===============================  =======  ================================
role                             ratio    what the user saw
===============================  =======  ================================
``LIGHTBOX_BACK_BTN``            1.06:1   Back button invisible
``LIGHTBOX_KBD``                 1.57:1   keyboard hints as white boxes
``LIGHTBOX_SIM_POSTER``          1.57:1   poster wells as white boxes
``LIGHTBOX_SIM_GLYPH_LIKE``      1.24:1   state glyphs invisible
``LIGHTBOX_BREADCRUMB_CURRENT``  2.36:1   trail unreadable
===============================  =======  ================================

Root cause, and what the fix has to preserve
--------------------------------------------
The preview overlay is a **fixed-dark surface in every palette** — its
``COLOR_LIGHTBOX_BG``/``_HEADER``/``_TEXT``/``_TEXT_HI`` tokens are deliberately
identical across all three. But its *other* colours were drawn from
palette-tuned tokens (``COLOR_MUTED``, ``COLOR_BG_DEEP``, ``COLOR_ACCENT_*``),
which Daylight tunes for a LIGHT background. A dark navy accent on a dark card
is invisible, and a near-white "deep" fill on a dark card is a white box.

So the rule this test enforces is simple: **a colour painted on the cinema
surface comes from the cinema family** (the fixed ``COLOR_LIGHTBOX_*`` tokens).
It checks the rendered outcome (contrast), not the token names, so a role that
finds some other way to be legible still passes.

Not covered here: the ``TRAILMAP_*`` family. The Explore trail-map is an
embedded view that mixes the dark shell with genuine app-surface regions
(``COLOR_BG``/``COLOR_BG_SECTION``/``COLOR_BG_BAR`` all appear in it), so which
surface a given role lands on is a real per-role question and not something to
guess at in a sweep. It needs its own pass — see the module docstring note in
``theme_palettes.py``.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme as _theme

PALETTES = ["Midnight", "Graphite", "Daylight"]

# WCAG 2.1 AA for normal text. Every role here is text or an icon glyph.
FLOOR = 4.5

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# Roles whose foreground is a runtime/structural value rather than a colour the
# theme owns, or which set no foreground at all. Each is a bare surface.
_NO_FOREGROUND = {
    "LIGHTBOX_CARD", "LIGHTBOX_HEADER_BAR", "LIGHTBOX_FOOTER_BAR",
    "LIGHTBOX_POSTER_SLOT", "LIGHTBOX_NOTICE_BAR",
}

# Roles that render on the header bar rather than the card body. Everything
# else in the family sits on the card.
_ON_HEADER = {
    "LIGHTBOX_BACK_BTN", "LIGHTBOX_TITLE", "LIGHTBOX_COUNTER",
    "LIGHTBOX_CLOSE_BTN", "LIGHTBOX_ACTION_BTN", "LIGHTBOX_FOOTER_HINT",
    "LIGHTBOX_BREADCRUMB_CRUMB", "LIGHTBOX_BREADCRUMB_SEP",
    "LIGHTBOX_BREADCRUMB_CURRENT", "LIGHTBOX_LENS_LINK",
}


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _lum(value: str) -> float:
    h = value.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def _contrast(fg: str, bg: str) -> float:
    lf, lb = _lum(fg), _lum(bg)
    hi, lo = max(lf, lb), min(lf, lb)
    return (hi + 0.05) / (lo + 0.05)


def _base_block(sheet: str) -> str:
    """The non-hover part of a role — hover states are a separate concern."""
    return sheet.split(":hover")[0]


def _declared(block: str, prop: str) -> str | None:
    """Last hex value declared for *prop*, or None.

    ``border-color`` must not be read as ``color`` — without that guard the last
    match wins and a role's BORDER gets measured as its TEXT, which produces
    confident, wrong numbers for roles that are fine.
    """
    found = None
    for m in re.finditer(rf"(?<![a-z-]){prop}:\s*([^;]+);", block):
        hit = _HEX.search(m.group(1))
        if hit:
            found = hit.group(0)
    return found


def _lightbox_roles() -> list[str]:
    return sorted(
        name for name in dir(_theme)
        if name.startswith("LIGHTBOX_") and isinstance(getattr(_theme, name), str)
    )


def _measure(role: str) -> tuple[str, str, float] | None:
    """(fg, bg, ratio) for *role*, or None when it declares no foreground."""
    block = _base_block(getattr(_theme, role))
    fg = _declared(block, "color")
    if fg is None:
        return None
    # A background declared by the role itself wins; otherwise the role lands on
    # the header bar or the card body.
    bg = _declared(block, "background") or _declared(block, "background-color")
    if bg is None:
        bg = (
            _theme.COLOR_LIGHTBOX_HEADER if role in _ON_HEADER
            else _theme.COLOR_LIGHTBOX_BG
        )
    return fg, bg, _contrast(fg, bg)


@pytest.fixture(autouse=True)
def _restore_theme():
    previous = _theme.current_theme()
    yield
    _theme.apply_theme(previous)


@pytest.mark.parametrize("palette", PALETTES)
def test_every_lightbox_role_is_legible_on_its_own_surface(palette):
    """No role in the preview overlay falls below 4.5:1 where it renders.

    FAILS against the pre-fix tree in Daylight with 17 roles below the floor,
    five of them under 2.4:1 (invisible, not merely dim).
    """
    _theme.apply_theme(palette)

    failures = []
    for role in _lightbox_roles():
        if role in _NO_FOREGROUND:
            continue
        measured = _measure(role)
        if measured is None:
            continue
        fg, bg, ratio = measured
        if ratio < FLOOR:
            failures.append(f"{role}: {fg} on {bg} = {ratio:.2f}:1")

    assert not failures, (
        f"{palette}: {len(failures)} lightbox role(s) below {FLOOR}:1 on the "
        f"surface they actually paint on —\n  " + "\n  ".join(failures)
    )


@pytest.mark.parametrize("palette", PALETTES)
def test_the_cinema_surface_is_identical_in_every_palette(palette):
    """The premise the rule above rests on: this surface does not follow the theme.

    If someone ever makes ``COLOR_LIGHTBOX_BG`` palette-tuned, the fixed
    foreground family stops being correct and this test says so directly,
    instead of the contrast test failing somewhere confusing.
    """
    _theme.apply_theme("Midnight")
    reference = (
        _theme.COLOR_LIGHTBOX_BG,
        _theme.COLOR_LIGHTBOX_HEADER,
        _theme.COLOR_LIGHTBOX_SUNKEN,
    )
    _theme.apply_theme(palette)
    assert (
        _theme.COLOR_LIGHTBOX_BG,
        _theme.COLOR_LIGHTBOX_HEADER,
        _theme.COLOR_LIGHTBOX_SUNKEN,
    ) == reference, (
        f"{palette} changed the fixed cinema surface; the fixed foreground "
        f"family (COLOR_LIGHTBOX_MUTED/_FAINT/_LINK/…) assumes it never moves"
    )


def test_the_sunken_well_is_darker_than_the_card_in_every_palette():
    """The poster well / keyboard chip must read as recessed, never as a light box.

    This is the assertion that catches the specific Daylight defect by shape
    rather than by number: ``COLOR_BG_DEEP`` is "deeper than the app surface",
    which in a LIGHT palette means *near-white* — and painting that on the dark
    card produced white rectangles where the poster wells belong.
    """
    for palette in PALETTES:
        _theme.apply_theme(palette)
        assert _lum(_theme.COLOR_LIGHTBOX_SUNKEN) < _lum(_theme.COLOR_LIGHTBOX_BG), (
            f"{palette}: the lightbox sunken fill "
            f"({_theme.COLOR_LIGHTBOX_SUNKEN}) is lighter than the card "
            f"({_theme.COLOR_LIGHTBOX_BG}) — it will render as a white box"
        )
