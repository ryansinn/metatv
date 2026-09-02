"""One row's CELLS: building them, measuring them, painting one.

Lifted out of ``channel_list_delegate`` as a mixin. Ledger D31 recorded that
file sitting exactly on the 1000-line code-health floor with "every row kind
pushes it over" — and two row features in one day proved it, each having to
claw lines back from comments to fit. The ledger's own prescription was this
lift, "cohesive and with no dependency on the label paths", as a slice of its
own rather than riding along with a feature.

The concern is one question — *what does a single chip or text run look like,
and how wide is it* — and it is answered in four steps that only make sense
together: which cells a row has (:meth:`_cells_by_slot`), what colour a cell
falls back to (:meth:`_resolve_default_color`), how wide it paints
(:meth:`_cell_width` / :meth:`_group_width`), and the painting itself
(:meth:`_paint_cell`). The row's LAYOUT — where those cells go — stays in
``channel_row_layout``, and what each cell SAYS stays in ``channel_row_cells``.

**What this mixin needs from the delegate it is mixed into**, stated here
because a mixin's dependencies are otherwise discovered by crashing:
``_density`` and ``_platform_name_style`` (settings), ``_chip_radius`` (density
geometry), and ``_hit_regions`` / ``_painting_row`` — the per-paint state
``paint()`` sets so a delegate-painted chip, which has no widget and therefore
no ``setToolTip``, can still be hit-tested for hover and clicks.
"""

from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QBrush, QColor, QFontMetrics
from PyQt6.QtWidgets import QStyleOptionViewItem

from metatv.gui import theme as _theme
from metatv.gui.token_color import to_qcolor as _to_qcolor
from metatv.core.channel_name_utils import PLATFORM_CODES
from metatv.gui.channel_row_cells import (
    CHIP_SLOT_COLLECTION,
    CHIP_SLOT_GENRE,
    CHIP_SLOT_LANGUAGE,
    CHIP_SLOT_LANGUAGE_2,
    CHIP_SLOT_LEAGUE,
    CHIP_SLOT_QUALITY,
    CHIP_SLOT_REGION,
    CHIP_SLOT_SPORT,
    CHIP_SLOT_STATE,
    CHIP_SLOT_SUBTITLE,
    CHIP_SLOT_VARIANTS,
    CHIP_SLOT_YEAR,
    _Cell,
    _category_cell,
    _genre_cells,
    _language_cell,
    _league_cell,
    _quality_cell,
    _region_or_platform_cell,
    _sport_cell,
    _state_cell,
    _variant_badge_cell,
    _year_cell,
)
from metatv.core.epg_utils import now_utc as _now_utc
from metatv.gui.channel_list_roles import (
    CATEGORY_ROLE,
    COLLECTION_ROLE,
    EVENT_WINDOW_ROLE,
    GENRE_ROLE,
    GENRES_ROLE,
    LANGUAGE_ROLE,
    LEAGUE_ROLE,
    PRIMARY_LANGUAGE_ROLE,
    QUALITY_TOKEN_ROLE,
    SECONDARY_LANGUAGE_ROLE,
    SPORT_ROLE,
    SUBTITLE_MARKER_ROLE,
    VARIANT_COUNT_ROLE,
    YEAR_ROLE,
)



# Cell-level spacing — these belong to the CHIPS, not to the row, so they stay.
_CELL_GAP = 6         # horizontal gap between adjacent cells

_CHIP_H_PAD = 7       # chip internal horizontal padding — matches theme.LANG_CHIP
                      # radius as the row fill it sits inside, so the artwork
                      # reads as part of the row rather than as a card on it.
_OUTLINE_RADIUS = 3   # TIER 3 corner radius. Deliberately NOT the pill radius
                      # below: a filled pill and an outlined pill of the same
                      # shape read as two colours of one thing, when the whole
                      # point of the tiers is that they are different KINDS of
                      # thing. A tight rounded rect also stops a short outlined
                      # chip ("2024") from rendering as a squashed lozenge.
_OUTLINE_V_INSET = 1  # px inset top+bottom on a tier-3 box. The stroke is drawn


class RowCellPaintMixin:
    """Cell construction, measurement and painting for ``ChannelRowDelegate``."""


    def _resolve_default_color(self, opt: QStyleOptionViewItem, index) -> QColor:
        """Default colour for non-chip text.

        Selection is NOT a case here any more. It used to return
        ``HighlightedText``, because a selected row was a saturated accent fill
        and nothing else was legible on it — which meant the row the user was
        actually looking at was the one row that lost its facet hues. V3's
        selection is a TINT (``primary.4``), so the normal ramp holds and the
        selected row reads exactly like its neighbours plus a marker bar.

        The ForegroundRole override still wins: a row the model dimmed
        (watched, degraded) stays dimmed.
        """
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            return fg.color()
        return _to_qcolor(_theme.COLOR_ROW_META)

    def _cell_width(self, fm: QFontMetrics, cell: _Cell) -> int:
        w = fm.horizontalAdvance(cell.text)
        return w + 2 * _CHIP_H_PAD if cell.is_chip else w

    def _paint_cell(self, painter, rect: QRect, cell: _Cell, font) -> None:
        # Record before painting so every drawn cell is hit-testable, including
        # ones that return early below.
        if cell.tip or cell.facet:
            row = self._painting_row
            if row is not None:
                self._hit_regions.setdefault(row, []).append((QRect(rect), cell))
        painter.setFont(font)
        if cell.is_chip and cell.outline:
            # TIER 3 — border-only. The interior is painted only if ``bg`` is
            # set, which for the row's own outline cells it never is: a resting
            # alpha tint is a hover effect in the wrong place. The stroke is
            # ``border`` when the cell wants a box quieter than its text (the
            # year), else ``fg`` (quality, whose box IS its tier hue).
            box = rect.adjusted(0, _OUTLINE_V_INSET, 0, -_OUTLINE_V_INSET)
            if cell.bg:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_to_qcolor(cell.bg))
                painter.drawRoundedRect(box, _OUTLINE_RADIUS, _OUTLINE_RADIUS)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_to_qcolor(cell.border or cell.fg))
            painter.drawRoundedRect(box, _OUTLINE_RADIUS, _OUTLINE_RADIUS)
            painter.setPen(_to_qcolor(cell.fg))
            # Text centres on the FULL rect, not the inset box: the inset is a
            # stroke-clipping fix, and shifting the baseline with it would take
            # the year off the line its neighbours sit on.
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, cell.text)
        elif cell.is_chip:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_to_qcolor(cell.bg))
            _r = self._chip_radius(rect)
            painter.drawRoundedRect(rect, _r, _r)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if cell.border:
                # A tier-1 chip normally needs no stroke — its fill is the
                # signal. It gets one when the fill it is sitting ON is the same
                # colour as its own (see ``_edged_on_selection``).
                painter.setPen(_to_qcolor(cell.border))
                painter.drawRoundedRect(rect, _r, _r)
            painter.setPen(_to_qcolor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, cell.text)
        else:
            painter.setPen(_to_qcolor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cell.text)

    # ── Shared row-building seam ─────────────────────────────────────────────

    def _cells_by_slot(self, index) -> dict[str, list[_Cell]]:
        """Build EVERY cell this row can paint, keyed by its slot id.

        The one place a role is turned into a ``_Cell``. The meta line and the
        rail then each ask :func:`_ordered` for the subset they show, which is
        what keeps them from drifting apart — the two used to build their own
        tuples and had already ended up with the same facts in different orders.

        Takes no selection argument: V3's selected row is a tint, so no cell has
        to be re-coloured for it (see ``_resolve_default_color``).
        """
        region_code = index.data(LANGUAGE_ROLE) or ""
        platform_code = region_code if region_code in PLATFORM_CODES else ""

        def one(cell: Optional[_Cell]) -> list[_Cell]:
            return [cell] if cell is not None else []

        return {
            CHIP_SLOT_QUALITY: one(_quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")),
            CHIP_SLOT_VARIANTS: one(_variant_badge_cell(index.data(VARIANT_COUNT_ROLE) or 1)),
            CHIP_SLOT_GENRE: _genre_cells(
                index.data(GENRES_ROLE), index.data(GENRE_ROLE) or ""
            ),
            CHIP_SLOT_STATE: one(_state_cell(index.data(EVENT_WINDOW_ROLE), _now_utc())),
            CHIP_SLOT_SPORT: one(_sport_cell(index.data(SPORT_ROLE) or "")),
            CHIP_SLOT_LEAGUE: one(_league_cell(index.data(LEAGUE_ROLE) or "")),
            CHIP_SLOT_COLLECTION: one(_category_cell(
                index.data(COLLECTION_ROLE) or "", platform_code,
                filter_category=index.data(CATEGORY_ROLE) or "",
            )),
            CHIP_SLOT_YEAR: one(_year_cell(index.data(YEAR_ROLE) or "")),
            CHIP_SLOT_REGION: one(_region_or_platform_cell(
                region_code, self._effective_platform_style()
            )),
            # Sub/dub marker ("AR-SUB"), the category's disagreeing language,
            # and the channel's OWN honest language — one hue, one tier.
            CHIP_SLOT_SUBTITLE: one(_language_cell(
                index.data(SUBTITLE_MARKER_ROLE) or "", filterable=False
            )),
            CHIP_SLOT_LANGUAGE_2: one(_language_cell(index.data(SECONDARY_LANGUAGE_ROLE) or "")),
            CHIP_SLOT_LANGUAGE: one(_language_cell(index.data(PRIMARY_LANGUAGE_ROLE) or "")),
        }

    def _group_width(self, fm: QFontMetrics, cells: list[_Cell]) -> int:
        """Total painted width of *cells* laid out with ``_CELL_GAP`` between
        them — what ``row_layout`` needs to reserve the rail."""
        if not cells:
            return 0
        return sum(self._cell_width(fm, c) for c in cells) + _CELL_GAP * (len(cells) - 1)
