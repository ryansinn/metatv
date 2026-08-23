"""Pure geometry for one V3 channel row — no painter, no state, no theme.

Why this is its own module, and why the signature looks the way it does
----------------------------------------------------------------------

The V3 row has one rule that outranks the rest: **nothing moves when a row is
selected.** The action affordance at the right is *always* reserved and only
*painted* on hover/current, so the columns a reader has learned stay where they
were. The cheapest way to keep that true forever is to make the alternative
unrepresentable — :func:`row_layout` takes no selection/hover/current argument,
so no future edit can accidentally make a column depend on row state. A test can
assert the invariant directly (the same rect for every state), because there is
no state to vary.

The column order, left to right::

    [pad][kind mark][art][gap][ title / meta stack ][rail][action gutter][pad]
     8     36        40    11   flexible             fit   44             8

``art`` is 2:3 for a movie/series poster and SQUARE for a live channel — a live
logo is a square asset and letterboxing it into a poster well wastes the row's
height for no information. ``rail`` is measured by the caller (it holds
font-metric-sized chips) and handed in as a width, which is what keeps this
module free of ``QFontMetrics`` and therefore free of a paint device.

Every value below is structural spacing in px, which CLAUDE.md's styles rule
allows inline — none of these is a colour or a font size.
"""

from __future__ import annotations

from typing import NamedTuple

from PyQt6.QtCore import QRect

#: Inset of the row FILL from the item rect, left and right. The fill is inset
#: rather than bled to the edge so a selected row reads as an object on the
#: surface instead of a full-bleed band, and so the right-hand cells clear the
#: vertical scrollbar.
ROW_PAD_H = 8
#: Inset of the fill from the item rect, top and bottom — the gap BETWEEN rows.
FILL_INSET_V = 3
#: Breathing room inside the fill above/below the tallest content. Small on
#: purpose: the fill is ALREADY inset from the item rect, so this is the second
#: of two paddings and the row would be a band of empty space with a generous
#: value here.
ROW_PAD_V = 2

#: The kind-mark column. Structural, never conditional: every row has a kind,
#: so the mark is reserved on every row including compact and including rows
#: with thumbnails turned off.
KIND_GUTTER_W = 36
KIND_ICON = 16

#: Poster well (movie/series) and the square tile a live channel gets instead.
ART_W = 40
ART_H = 58
ART_TILE = 40
ART_GAP = 11

#: The always-reserved action gutter, and the affordance painted inside it.
ACTION_W = 34
ACTION_H = 28
#: Gap between the affordance's right edge and the fill's. Larger than it looks
#: it needs to be, on purpose: this is the edge a vertical scrollbar paints over.
ACTION_INSET_R = 11
ACTION_GUTTER_W = ACTION_W + ACTION_INSET_R

#: Gap between the text stack and the right-hand rail, and between the rail and
#: the action gutter.
RAIL_GAP = 12

#: Height of a rail chip. FIXED, not the row's inner height: a chip that grows
#: with the row becomes a tall coloured slab down the right-hand side, which is
#: the loudest thing in a list of rows whose subject is the title. 16px is what
#: a 12px label plus its padding measures.
CHIP_H = 16

FILL_RADIUS = 6
#: The current/selected left edge bar, inside the fill's left edge.
MARKER_W = 3

#: Gap between stacked text lines.
LINE_GAP = 2


class RowLayout(NamedTuple):
    """Every rect one row paints into, computed from geometry alone.

    ``art`` is an empty ``QRect`` when the row shows no artwork (compact
    density, or thumbnails switched off) — the kind mark still gets its gutter,
    and the text stack simply starts earlier.
    """

    fill: QRect
    marker: QRect
    kind: QRect
    art: QRect
    text: QRect
    rail: QRect
    action: QRect


def art_size(art_square: bool) -> tuple[int, int]:
    """``(width, height)`` of the artwork well — square for live, 2:3 otherwise."""
    return (ART_TILE, ART_TILE) if art_square else (ART_W, ART_H)


def row_height(stack_h: int, *, has_art: bool) -> int:
    """Total row height for a text stack *stack_h* px tall.

    The row is the taller of its text stack and the ARTWORK WELL, plus padding
    on both sides of the fill — so turning thumbnails on grows a two-line row
    to fit the poster instead of cropping it, and a three-line comfy+ row that
    is already taller than the poster is left alone.

    The well is always the POSTER's height, even on a live channel whose tile
    is square. Sizing each row to its own artwork gave a mixed list two
    different row heights (68px for movies and series, 50px for live), so
    scrolling through one stepped between two rhythms. A live tile centres
    inside the taller row instead, which is what the approved design shows —
    and it is why this function takes no media-kind argument at all.

    Args:
        stack_h: Measured height of the row's text lines, gaps included. The
            caller measures it, because it depends on fonts and this module
            holds no paint device.
        has_art: Whether this row reserves an artwork well.
    """
    content = max(stack_h, ART_H if has_art else 0)
    return content + 2 * ROW_PAD_V + 2 * FILL_INSET_V


def stacked_lines(container: QRect, line_height: int, gap: int, count: int) -> list[QRect]:
    """Split *container* into *count* stacked line rects, centred as a block.

    Returns ``[]`` for ``count <= 0``.
    """
    if count <= 0:
        return []
    total = count * line_height + (count - 1) * gap
    top = container.top() + max(0, (container.height() - total) // 2)
    out = []
    y = top
    for _ in range(count):
        out.append(QRect(container.left(), y, container.width(), line_height))
        y += line_height + gap
    return out


def right_aligned_rects(container: QRect, widths: list[int], spacing: int) -> list[QRect]:
    """Lay *widths* out left-to-right so the LAST sits flush on *container*'s
    right edge (its ``.right()`` equals ``container.right()``).

    Returns ``[]`` for an empty *widths* list.
    """
    if not widths:
        return []
    total = sum(widths) + spacing * (len(widths) - 1)
    x = container.right() - total + 1  # QRect.right() is inclusive
    rects = []
    for w in widths:
        rects.append(QRect(x, container.top(), w, container.height()))
        x += w + spacing
    return rects


def row_layout(rect: QRect, *, has_art: bool, art_square: bool, rail_w: int) -> RowLayout:
    """Every rect for one row.

    Deliberately takes **no** selection/hover/current argument: the action
    gutter is reserved on every row and merely painted conditionally, so row
    geometry cannot depend on row state. See the module docstring.

    Args:
        rect: The item rect handed to the delegate.
        has_art: Whether this row reserves an artwork well.
        art_square: Live channels get a square tile; movies/series a 2:3 poster.
        rail_w: Measured width of the right-hand chip rail (0 when it is empty).
            Supplied by the caller because measuring it needs font metrics,
            which would drag a paint device into this module.
    """
    fill = QRect(
        rect.left() + ROW_PAD_H,
        rect.top() + FILL_INSET_V,
        max(0, rect.width() - 2 * ROW_PAD_H),
        max(0, rect.height() - 2 * FILL_INSET_V),
    )
    marker = QRect(fill.left(), fill.top(), MARKER_W, fill.height())

    inner = fill.adjusted(0, ROW_PAD_V, 0, -ROW_PAD_V)

    kind = QRect(
        fill.left() + (KIND_GUTTER_W - KIND_ICON) // 2,
        inner.top() + max(0, (inner.height() - KIND_ICON) // 2),
        KIND_ICON,
        KIND_ICON,
    )

    x = fill.left() + KIND_GUTTER_W
    if has_art:
        aw, ah = art_size(art_square)
        art = QRect(x, inner.top() + max(0, (inner.height() - ah) // 2), aw, ah)
        x += aw + ART_GAP
    else:
        art = QRect()

    # Both the affordance and the rail are clamped to the row they are in:
    # compact rows are shorter than the affordance's natural height, and a
    # control taller than its row paints outside the fill and gets clipped.
    action_h = min(ACTION_H, inner.height())
    action = QRect(
        fill.right() - ACTION_INSET_R - ACTION_W + 1,
        inner.top() + max(0, (inner.height() - action_h) // 2),
        ACTION_W,
        action_h,
    )

    rail_right = action.left() - RAIL_GAP
    chip_h = min(CHIP_H, inner.height())
    rail = QRect(
        max(x, rail_right - rail_w + 1),
        inner.top() + max(0, (inner.height() - chip_h) // 2),
        min(rail_w, max(0, rail_right - x + 1)),
        chip_h,
    )

    text_right = (rail.left() - RAIL_GAP) if rail_w > 0 else (rail_right + 1)
    text = QRect(x, inner.top(), max(0, text_right - x), inner.height())

    return RowLayout(fill=fill, marker=marker, kind=kind, art=art, text=text,
                     rail=rail, action=action)
