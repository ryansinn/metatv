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

#: Roles whose radius is within ~2px of half their rendered height. Measured,
#: not guessed. All but LANG_CHIP are sized by ``font-size`` alone, so the type
#: scale is what threatens them — which is exactly why the test renders rather
#: than reasoning about padding.
PILL_ROLES = [
    "POSTER_WATCHED_BADGE",
    "POSTER_UNWATCHED_BADGE",
    "TRAILMAP_WBADGE",
    "TRAILMAP_WBADGE_DONE",
    "TRAILMAP_WBADGE_PARTIAL",
    "LANG_CHIP",
]


@pytest.mark.parametrize("name", PILL_ROLES)
def test_a_pill_badge_still_has_a_cut_corner(qapp, name):
    """Rendered, not computed. The corner must not be painted at all.

    Compared against the HOST background rather than the fill: a role with a
    border paints its corner in the BORDER colour, so "corner != centre" reports
    rounded for a square box. That false positive nearly had me 'fix' a
    correctly-round chevron.
    """
    sheet = getattr(_theme, name)
    host = QWidget()
    host.setStyleSheet("background:#000000;")
    widget_cls = QPushButton if "QPushButton" in sheet else QLabel
    widget = widget_cls("Comedy", host)
    widget.setStyleSheet(sheet)
    widget.adjustSize()
    height = widget.sizeHint().height()
    widget.setFixedSize(max(widget.sizeHint().width(), 40), height)
    widget.move(0, 0)
    host.setFixedSize(widget.width(), height)
    host.show()
    qapp.processEvents()
    image = host.grab().toImage()
    assert QColor(image.pixel(0, 0)).name() == "#000000", (
        f"{name} paints its top-left corner — it has squared. Its radius now "
        f"exceeds half its {height}px height."
    )


@pytest.mark.parametrize("name", PILL_ROLES)
def test_a_pill_badge_has_no_headroom_to_spare(qapp, name):
    """Documents WHY these are fragile, so the number is in the suite rather
    than in a commit message: each of these is within a pixel of squaring."""
    sheet = getattr(_theme, name)
    radius = int(re.search(r"border-radius:\s*(\d+)px", sheet).group(1))
    host = QWidget()
    widget_cls = QPushButton if "QPushButton" in sheet else QLabel
    widget = widget_cls("Comedy", host)
    widget.setStyleSheet(sheet)
    widget.adjustSize()
    height = widget.sizeHint().height()
    assert radius <= height / 2, f"{name} already squares: {radius}px on {height}px"
    assert height / 2 - radius <= 2.5, (
        f"{name} has {height / 2 - radius:.1f}px of headroom — it is no longer "
        f"a pill-by-arithmetic, so this list should be re-measured"
    )
