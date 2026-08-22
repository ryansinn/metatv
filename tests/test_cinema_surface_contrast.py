"""Every role on the fixed-dark "cinema" shell, measured against that shell.

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

Coverage now includes the ``TRAILMAP_*`` and ``EXPLORE_*`` families, which paint
on the same fixed-dark shell (``TRAILMAP_SHELL`` / ``EXPLORE_VIEW_BG`` are both
``COLOR_LIGHTBOX_BG``). They were left out of the first pass because the view
looked mixed-surface; measuring settled it — of the 21 trail-map roles that
declare no background of their own, 17 were legible on the dark shell and
illegible on the app background, which is only consistent with the shell being
their surface. Their Daylight numbers were as bad as the lightbox's: the "here"
tag on the current trail stop was white-on-white at 1.03:1, the watched badges
1.33/1.44:1, the header link 1.24:1, and the thumbnail and detail-poster wells
were near-white fills on the dark shell.

This matters as one surface rather than two: the lightbox's Explore button opens
straight into the trail map, so fixing one and not the other just moves where
the user meets the bug.
"""

from __future__ import annotations

import re

import pytest

from metatv.gui import theme as _theme

PALETTES = ["Midnight", "Graphite", "Daylight"]

# The role families that paint on the fixed-dark cinema shell. Anything added to
# theme.py with one of these prefixes is measured by this module automatically —
# no enumeration to forget to extend.
CINEMA_PREFIXES = ("LIGHTBOX_", "TRAILMAP_", "EXPLORE_")

# WCAG 2.1 AA for normal text. Every role here is text or an icon glyph.
FLOOR = 4.5

_HEX = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")

# Roles whose foreground is a runtime/structural value rather than a colour the
# theme owns, or which set no foreground at all. Each is a bare surface.
_NO_FOREGROUND = {
    "LIGHTBOX_CARD", "LIGHTBOX_HEADER_BAR", "LIGHTBOX_FOOTER_BAR",
    "LIGHTBOX_POSTER_SLOT", "LIGHTBOX_NOTICE_BAR",
    "TRAILMAP_SHELL", "TRAILMAP_HEADER_BAR", "TRAILMAP_COLUMN",
    "TRAILMAP_TRAIL_COLUMN", "TRAILMAP_COLHEAD", "TRAILMAP_ROW",
    "TRAILMAP_ROW_SELECTED", "TRAILMAP_DETAIL", "EXPLORE_VIEW_BG",
}

# Roles that render on the header bar rather than the card body. Everything
# else in the family sits on the card.
_ON_HEADER = {
    "LIGHTBOX_BACK_BTN", "LIGHTBOX_TITLE", "LIGHTBOX_COUNTER",
    "LIGHTBOX_CLOSE_BTN", "LIGHTBOX_ACTION_BTN", "LIGHTBOX_FOOTER_HINT",
    "LIGHTBOX_BREADCRUMB_CRUMB", "LIGHTBOX_BREADCRUMB_SEP",
    "LIGHTBOX_BREADCRUMB_CURRENT", "LIGHTBOX_LENS_LINK",
    "TRAILMAP_TITLE", "TRAILMAP_SUBTITLE", "TRAILMAP_CLOSE_BTN",
    "TRAILMAP_LINK_BTN",
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


def _cinema_roles() -> list[str]:
    return sorted(
        name for name in dir(_theme)
        if name.startswith(CINEMA_PREFIXES) and isinstance(getattr(_theme, name), str)
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
def test_every_cinema_role_is_legible_on_its_own_surface(palette):
    """No role on the fixed-dark shell falls below 4.5:1 where it renders.

    FAILS against the pre-fix tree in Daylight — 17 lightbox roles below the
    floor before the first pass, and 6 trail-map roles before this one, the
    worst of them at 1.03:1 (invisible, not merely dim).
    """
    _theme.apply_theme(palette)

    failures = []
    for role in _cinema_roles():
        if role in _NO_FOREGROUND:
            continue
        measured = _measure(role)
        if measured is None:
            continue
        fg, bg, ratio = measured
        if ratio < FLOOR:
            failures.append(f"{role}: {fg} on {bg} = {ratio:.2f}:1")

    assert not failures, (
        f"{palette}: {len(failures)} cinema role(s) below {FLOOR}:1 on the "
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
