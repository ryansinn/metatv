"""The leading discriminator slot: what still tells a list of rows apart.

One job, three parts that only make sense together — the RULE that picks a
discriminator, the RESOLUTION of one row's value for it, and the PAINT. They
live here rather than in ``channel_list_delegate`` because that file crossed
1,000 lines when they were added, and the ratchet's answer to that is cohesion
rather than arithmetic: this is a self-contained question with its own
vocabulary, not a fragment of "how a channel row is painted".

The settled rule, from *Sport Rundown*:

===================  ================================  =========================
filter state         the slot shows                    why
===================  ================================  =========================
unfiltered           the sport glyph                   the sport is what varies
one sport selected   the region CODE                   the glyph has gone
                                                       constant; region is
                                                       76-90% populated within
                                                       any single sport
nothing varies       nothing — the slot COLLAPSES      ~28px back to the title
===================  ================================  =========================

**Collapsing is not blanking**, and the difference is the whole feature. The
audit found sports rows clip long fixture names, so reserving the column and
painting nothing in it is the implementation that passes every order-based
check while being exactly wrong — it takes the width and gives nothing back.

Nothing here imports the delegate, and none of it needs a model index: the rule
takes value pairs and the resolver takes two strings, so both are testable
without constructing a row. The paint helper takes the delegate's own text
chokepoint as a callable rather than reaching for a painter method, so a
region code gets the same colour and font handling as every other string in the
row and is recorded by the same paint-capture harness.
"""

from __future__ import annotations

from typing import Callable, Iterable

from PyQt6.QtCore import QRect

from metatv.core.channel_name_utils import normalize_region_code
from metatv.gui import channel_row_layout as _layout
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme

#: What the slot may show. "" collapses it, and is the value on every row
#: outside Sports.
DISCRIMINATOR_SPORT = "sport"
DISCRIMINATOR_REGION = "region"
VALID_DISCRIMINATORS = (DISCRIMINATOR_SPORT, DISCRIMINATOR_REGION)


def discriminator_for(rows: Iterable[tuple[str, str]]) -> str:
    """Which discriminator still tells *rows* apart: sport, region, or none.

    The design states the rule as three filter states. This is that rule written
    as its actual CRITERION rather than as a case analysis of the filter, and it
    returns the same answer for all three.

    Writing it this way matters twice over. The third state is not reachable
    from ``SportsFilterBar`` today — it has sport, league and search, and no
    region facet — so a filter-shaped implementation would carry a branch
    nothing could execute. And the criterion catches cases the enumeration does
    not: a library that happens to hold one sport shows a constant glyph on
    every row while no filter is active at all.

    A value discriminates when the rows do not agree on it. Rows that have no
    value are ignored for that judgement — an absent region among varied ones
    does not make region useless — but a facet NO row carries cannot
    discriminate anything.

    Args:
        rows: ``(sport, region)`` pairs, in any order.

    Returns:
        :data:`DISCRIMINATOR_SPORT`, :data:`DISCRIMINATOR_REGION`, or ``""``.
    """
    sports: set[str] = set()
    regions: set[str] = set()
    for sport, region in rows:
        if sport:
            sports.add(sport)
        if region:
            regions.add(region)
    if len(sports) > 1:
        return DISCRIMINATOR_SPORT
    if len(regions) > 1:
        return DISCRIMINATOR_REGION
    return ""


def lead_slot(discriminator: str, sport: str, region: str) -> tuple[str, str]:
    """``(text, vector_role)`` for one row's slot — at most one is ever set.

    Returns ``("", "")`` when the slot collapses: every row outside Sports (the
    discriminator is ``""`` until a view sets one), and any row whose chosen
    discriminator is missing or unpaintable. A row with no value reserves no
    column, because the argument for this slot is that ~28px is better spent on
    a fixture name than on a blank.

    The sport glyph is looked up in the SAME ``VECTOR_KEYS["sport_*"]`` the
    filter strip uses — press the ball there and the rows still wearing it are
    what remain. The region is a CODE and never a flag: flags render
    inconsistently across platforms, several regions have none, and a flag
    encodes by colour alone, which this project does not do.
    """
    if discriminator == DISCRIMINATOR_SPORT:
        role = f"sport_{sport}" if sport else ""
        return ("", role if role in _icons.VECTOR_KEYS else "")
    if discriminator == DISCRIMINATOR_REGION:
        return (normalize_region_code(region) or "", "")
    return ("", "")


def slot_width(text: str, role: str) -> int:
    """``LEAD_W`` when there is something to paint, else 0 — the collapse."""
    return _layout.LEAD_W if (text or role) else 0


def paint_lead_slot(painter, rect: QRect, text: str, role: str, color,
                    font, draw_text: Callable[..., None]) -> None:
    """Paint the discriminator into *rect*.

    Args:
        draw_text: The delegate's own ``_draw_text``. Passed in rather than
            called through a painter method so the code goes through the one
            text chokepoint — same colour and font handling as every other
            string in the row, and recorded by the paint-capture harness, which
            is what makes this cell testable by the same means as the rest.
    """
    if rect.isEmpty():
        return
    if role:
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key(role), color, _layout.LEAD_ICON)
        if not pixmap.isNull():
            side = min(rect.height(), _layout.LEAD_ICON)
            painter.drawPixmap(
                QRect(rect.left() + max(0, (rect.width() - _layout.LEAD_ICON) // 2),
                      rect.top(), _layout.LEAD_ICON, side),
                pixmap)
        return
    if text:
        # The region code is TIER-2 meta, a fixed role rather than row state,
        # so the colour is decided here and not threaded from the caller.
        draw_text(painter, rect, text, _theme.COLOR_ROW_META, font)
