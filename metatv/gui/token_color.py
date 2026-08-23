"""Theme token → ``QColor``: the one conversion every painted colour goes through.

Its own module because it is a chokepoint, not a helper: any painter drawing
with ``QPainter`` (rather than a stylesheet) has to convert a theme token by
hand, and doing it with a bare ``QColor(token)`` is a silent bug — see
:func:`to_qcolor` for what that costs.

Exported from ``channel_list_delegate`` as ``_to_qcolor`` as well, which is
where it lived before and where its callers still look for it.
"""

from __future__ import annotations

import re
from typing import Union

from PyQt6.QtGui import QColor


# ---------------------------------------------------------------------------
# Colour conversion — the ONE chokepoint every colour this delegate paints
# must go through. Never construct a bare QColor(token) at a paint call site.
# ---------------------------------------------------------------------------

# CSS rgba(r,g,b,a) / rgb(r,g,b) — the format theme_palettes.py's OVERLAY_*
# tokens use. Whitespace-tolerant; the alpha group is optional (rgb() form).
_RGBA_RE = re.compile(
    r'^\s*rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)\s*$'
)


def to_qcolor(token: Union[str, QColor, None]) -> QColor:
    """Convert a theme token value into a valid, correctly-coloured QColor —
    the single conversion chokepoint every colour this delegate paints must
    route through instead of a bare ``QColor(token)`` call.

    ``QColor``'s own string constructor parses ``#RRGGBB``/``#RGB`` hex and
    Qt/SVG colour NAMES ("gold", "white", ...) — but NOT the CSS
    CSS functional-notation colour syntax
    ``theme_palettes.py``'s ``OVERLAY_*`` tokens use. Feeding one of those
    straight to ``QColor(...)`` silently returns an INVALID colour that
    paints as OPAQUE BLACK, alpha 255 — a real bug this chokepoint fixes:
    every chip whose background read an ``OVERLAY_*`` token (language/
    region/genre/collection, and the outline quality chip's own subtle tint)
    was painting a solid black box instead of the intended translucent tint.
    Those ``rgba()`` strings are legitimate CSS for QSS stylesheets; they are
    simply not valid ``QColor`` constructor input on a raw ``QPainter``
    surface like this delegate.

    Args:
        token: A theme token value — ``#RRGGBB``/``#RGB`` hex, an SVG colour
            name, a CSS functional-notation colour string, an
            already-constructed ``QColor`` (passed through unchanged — some
            callers, e.g. ``_resolve_default_color``, already hand this a
            real ``QColor``), or ``None``/``""``.

    Returns:
        A ``QColor``. ``rgba()``/``rgb()`` strings are parsed component-wise
        (alpha via ``setAlphaF``, clamped to ``[0, 1]``); everything else is
        handed to ``QColor()`` directly (hex/named colours parse correctly
        there). An empty/unparseable token falls back to ``QColor()`` (Qt's
        own invalid-black) rather than raising — paint code must never crash
        the row.
    """
    if isinstance(token, QColor):
        return token
    if not token:
        return QColor()
    match = _RGBA_RE.match(token)
    if match:
        r, g, b = int(match.group(1)), int(match.group(2)), int(match.group(3))
        color = QColor(r, g, b)
        if match.group(4) is not None:
            color.setAlphaF(max(0.0, min(1.0, float(match.group(4)))))
        return color
    return QColor(token)
