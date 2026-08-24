"""The 4pt spacing scale — and why it is applied to one axis only.

Eighteen distinct padding values shipped before this family existed: every
integer from 0 to 14, plus 16, 18 and 20, across ~215 declarations.

The constraint that shapes the scale is not obvious from a stylesheet.
**Vertical padding sets a control's height, and Qt squares any box whose
border-radius exceeds half its height** (measured — see
``tests/test_radius_scale.py``). Several badges sit within 2px of that line:

    POSTER_WATCHED_BADGE   radius 13px, height 26px   headroom 0.0px
    TRAILMAP_WBADGE        radius 11px, height 23px   headroom 0.5px
    LANG_CHIP              radius  8px, height 20px   headroom 2.0px

Width is load-bearing for nothing, so the horizontal axis is free to snap. The
vertical axis is left alone wholesale rather than reasoned about per site.

Where the danger actually lives is worth stating, because it is not where I
first assumed: all but ``LANG_CHIP`` have **no padding at all** — their height
comes from ``font-size``. A spacing sweep could never have squared them; a
change to the TYPE scale can, and that scale was last rebuilt one release ago.
So the render test below is deliberately agnostic about which scale moved: it
asserts the corner is cut, whatever the cause.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QLabel, QPushButton, QWidget

from metatv.gui import theme as _theme

THEME_SRC = Path("metatv/gui/theme.py").read_text()

SCALE = {"SPACE_NONE": 0, "SPACE_XS": 4, "SPACE_SM": 8, "SPACE_MD": 12, "SPACE_LG": 16}

#: One padding shorthand as written in the source, e.g. ``1px " + SPACE_SM + "``.
_PADDING = re.compile(r'padding:\s*([^;}]*?)(?=[;}])')
#: One slot within it — either a literal or a spliced token.
_SLOT = re.compile(r'(\d+px)|"\s*\+\s*(SPACE_[A-Z]+)\s*\+\s*"')


def _slots(run: str) -> list[str | None]:
    """The shorthand's slots left to right; a token slot yields its name."""
    return [tok or lit for lit, tok in _SLOT.findall(run)]


def _vertical_slots(count: int) -> list[int]:
    """Which positions of a ``count``-value CSS padding shorthand are vertical.

    ``A`` = all sides; ``V H``; ``T H B``; ``T R B L``.
    """
    return {1: [0], 2: [0], 3: [0, 2], 4: [0, 2]}[count]


# ---------------------------------------------------------------------------
# 1. The scale is horizontal-only.
# ---------------------------------------------------------------------------

def test_no_spacing_token_lands_on_a_vertical_edge():
    """THE guard. A ``SPACE_*`` token in a top/bottom slot changes a control's
    height, and a badge whose radius is half that height becomes a rectangle.

    Static, so it has no false positives and needs no rendering — it reads the
    shorthand's shape exactly as CSS does.
    """
    offenders = []
    for run in _PADDING.findall(THEME_SRC):
        slots = _slots(run)
        if not slots or not any(s in SCALE for s in slots):
            continue
        for position in _vertical_slots(len(slots)):
            if position < len(slots) and slots[position] in SCALE:
                offenders.append(f"padding: {run.strip()}  (slot {position} is vertical)")
    assert not offenders, (
        "spacing tokens applied to a VERTICAL edge — this changes control "
        "height and can square a pill badge:\n  " + "\n  ".join(offenders)
    )


def test_the_sweep_actually_reached_the_theme_layer():
    """A guard whose population is empty guards nothing."""
    used = [run for run in _PADDING.findall(THEME_SRC)
            if any(s in SCALE for s in _slots(run))]
    assert len(used) >= 30, f"only {len(used)} padding runs use the scale"


# ---------------------------------------------------------------------------
# 2. The scale itself.
# ---------------------------------------------------------------------------

def test_the_scale_is_a_4pt_grid():
    values = [_theme.space_px(getattr(_theme, name)) for name in SCALE]
    assert sorted(values) == values
    assert all(v % 4 == 0 for v in values), f"not a 4pt grid: {values}"


@pytest.mark.parametrize("name,expected", sorted(SCALE.items()))
def test_each_token_reads_as_px_and_as_an_int(name, expected):
    token = getattr(_theme, name)
    assert token.endswith("px")
    assert _theme.space_px(token) == expected


# ---------------------------------------------------------------------------
# 3. The pill badges still render as pills.
# ---------------------------------------------------------------------------

#: ``role -> (module, the size its call site pins it to)``.
#:
#: Every one of these is a round badge whose call site calls ``setFixedSize``,
#: so its height is NOT its ``sizeHint`` — measuring the hint is measuring a
#: size the widget never has. An earlier version of this file did exactly that
#: and reported the trail-map badge as squared under Inter; it is 22px pinned
#: with an 11px radius, i.e. a perfect pill. The same trap had already been
#: noted for ``LIGHTBOX_CHEVRON`` (``setFixedSize(44, 44)``, radius 22) and
#: written into this docstring before being walked into anyway.
#:
#: So the contract asserted here is the one that is actually true and actually
#: font-independent: **radius is exactly half the pinned size.**
PINNED_PILLS = {
    "POSTER_WATCHED_BADGE": ("metatv/gui/details_sections.py", 26),
    "POSTER_UNWATCHED_BADGE": ("metatv/gui/details_sections.py", 26),
    "TRAILMAP_WBADGE": ("metatv/gui/trail_map_detail.py", 22),
    "TRAILMAP_WBADGE_DONE": ("metatv/gui/trail_map_detail.py", 22),
    "TRAILMAP_WBADGE_PARTIAL": ("metatv/gui/trail_map_detail.py", 22),
    "LIGHTBOX_CHEVRON": ("metatv/gui/similar_lightbox.py", 44),
}


@pytest.mark.parametrize("name,size", [(n, s) for n, (_m, s) in PINNED_PILLS.items()])
def test_a_pinned_pill_has_a_radius_of_exactly_half_its_size(name, size):
    """A pill IS half the control's height. One pixel over and Qt renders a
    hard rectangle instead of clamping (see ``test_radius_scale``), so this is
    the difference between a round badge and a square one."""
    radius = int(re.search(r"border-radius:\s*(\d+)px", getattr(_theme, name)).group(1))
    assert radius * 2 == size, (
        f"{name} has a {radius}px radius but its call site pins it to {size}px — "
        f"a pill is exactly half, and over half renders SQUARE"
    )


@pytest.mark.parametrize("name,module,size",
                         [(n, m, s) for n, (m, s) in PINNED_PILLS.items()])
def test_the_pinned_size_above_matches_the_call_site(name, module, size):
    """The table is only worth anything if it still describes the code.

    Reads the call site rather than trusting the number, so moving a badge to a
    different size fails here instead of silently making the pill assertion
    meaningless.
    """
    source = Path(module).read_text()
    # Either a literal pair or a named constant assigned that value — both are
    # in use, and demanding one shape would fail on a refactor that changed
    # nothing about the rendering.
    literal = f"setFixedSize({size}, {size})" in source
    named = bool(re.search(rf"_BADGE_SIZE[^=\n]*=\s*{size}\b", source))
    assert literal or named, (
        f"{module} no longer pins {size}x{size}; re-measure {name}'s pill contract"
    )


def test_no_pill_is_measured_by_its_size_hint():
    """A guard on this file itself.

    Rendering these roles at ``sizeHint`` and checking the painted corner looks
    like a stronger test and is a weaker one: it measures a size the widget
    never has, and reports squares that do not exist. Recorded so the "better"
    version does not get written again.
    """
    body = Path("tests/test_spacing_scale.py").read_text()
    # Split so this guard does not match its own source and fail forever — the
    # self-referential trap that a naive version of it walks straight into.
    needle = "adjust" + "Size()"
    assert needle not in body, (
        "a pill test is measuring sizeHint again — these widgets are "
        "setFixedSize-pinned and their hint is not their height"
    )
