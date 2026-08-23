"""The design scales that are NOT palette properties, and their accessors.

``theme_palettes.py`` holds everything a palette has an opinion about — every
colour, and the type scale's px values. A corner radius and the zoom transform
do not vary by palette: a shape is a shape in Midnight, Graphite and Daylight
alike. Keeping them here rather than in ``theme.py`` also keeps that file, which
is over 1000 lines on a shrink-only ratchet, from growing to hold them.

Everything below is re-exported from ``theme`` (``theme.RADIUS_SM``,
``theme.zoomed_font``), which is where callers already look for a design token.
"""

from __future__ import annotations

from PyQt6.QtGui import QFont


def zoomed_font(token: str, zoom: float, *, bold: bool = False) -> QFont:
    """Return a QFont whose pixel size is the token's px value scaled by *zoom*.

    The token must be one of the ``FONT_*`` constants defined below (e.g.
    ``FONT_MD = "11px"``).  This is the sanctioned way to scale fonts by the
    Discover zoom level without violating the "no inline px literals" rule —
    the token remains the base/source-of-truth; zoom is a user transform
    applied via QFont (not a stray stylesheet literal).

    Args:
        token: A ``FONT_*`` constant string, e.g. ``FONT_MD``.
        zoom:  Zoom multiplier (will be clamped to the card-zoom range 0.6–1.8
               by the caller; no clamping here).
        bold:  When True, the returned font is bold.

    Returns:
        A ``QFont`` with ``pixelSize`` set to ``max(6, round(px * zoom))``.
    """
    px = int(token.replace("px", ""))
    f = QFont()
    f.setPixelSize(max(6, round(px * zoom)))
    if bold:
        f.setBold(True)
    return f


# Palette-INVARIANT, so unlike COLOR_*/FONT_* these are defined here rather than
# in theme_palettes.py: a corner is a shape, and none of the three neutrals has
# an opinion about it. 165 literals across 15 distinct values shipped before
# this family existed, with 3px and 4px — 108 of the 165 between them — visually
# identical at every size the interface uses.
#
# THE ENGINE RULE, measured rather than recalled (Qt 6.11, PyQt6 6.11.1):
#
#     Qt honours a border-radius only while it is <= HALF the box's height.
#     One pixel over, it does not clamp — it silently renders a SQUARE.
#
# Verified on a white-on-black box at five heights; the cutoff is exact every
# time (16px box rounds to 8 and squares at 9; 20px rounds to 10, squares at 11;
# 40px rounds to 20, squares at 21). ``border-radius: 999px`` and ``50%``, the
# two idioms that produce a pill on the web, both render a hard rectangle here.
#
# Two consequences worth stating, because both are easy to get wrong:
#
#   1. A PILL CANNOT BE A TOKEN. It is exactly half the control's height, so it
#      depends on the control. Sites that want one keep their own value and are
#      annotated; do not "tidy" them onto this scale.
#   2. A fixed step is safe only on a control at least TWICE its height. Putting
#      RADIUS_LG on a 20px chip does not give a rounder chip, it gives a square
#      one — the failure is invisible in the stylesheet and obvious on screen.
#
# ``tests/test_radius_scale.py`` renders every role constant that carries a
# radius and fails on any that has silently squared.
RADIUS_NONE = "0px"   # deliberate square — a segmented cell, a flush edge
RADIUS_SM = "4px"     # chips, inputs, small buttons        (safe >= 8px tall)
RADIUS_MD = "8px"     # cards, panels, dialog sections      (safe >= 16px tall)
RADIUS_LG = "12px"    # overlays, sheets, the lightbox card (safe >= 24px tall)


# ── Spacing ─────────────────────────────────────────────────────────────────
#
# A 4pt grid. 18 distinct padding values shipped before this family existed —
# every integer from 0 to 14, plus 16, 18 and 20 — across ~215 declarations.
#
# APPLIED TO HORIZONTAL PADDING ONLY, and the reason is the radius rule above.
# Vertical padding sets a control's HEIGHT, and Qt squares any box whose radius
# exceeds half its height. Several badges sit within 2px of that line:
#
#     POSTER_WATCHED_BADGE   radius 13px, height 26px   headroom 0.0px
#     TRAILMAP_WBADGE        radius 11px, height 23px   headroom 0.5px
#     LANG_CHIP              radius  8px, height 20px   headroom 2.0px
#
# Width is load-bearing for nothing, so the horizontal axis is free. The
# vertical axis is left exactly as it is rather than reasoned about per site.
#
# Worth knowing, because it is where the danger actually lives: all but
# LANG_CHIP have NO padding at all — their height comes from ``font-size``.
# So the thing most likely to square them is a change to the TYPE scale, not to
# this one. ``tests/test_spacing_scale.py`` renders them and is deliberately
# agnostic about which scale moved.
SPACE_NONE = "0px"
SPACE_XS = "4px"
SPACE_SM = "8px"
SPACE_MD = "12px"
SPACE_LG = "16px"


def space_px(token: str) -> int:
    """The integer px of a ``SPACE_*`` token, for layout-margin call sites."""
    return int(token.replace("px", ""))


def radius_px(token: str) -> int:
    """The integer px of a ``RADIUS_*`` token, for ``QPainter`` call sites.

    A delegate paints with ``drawRoundedRect``, which wants a number, while a
    stylesheet wants ``"8px"``. One definition, two readings — the same split
    ``zoomed_font`` makes for the type scale.
    """
    return int(token.replace("px", ""))
