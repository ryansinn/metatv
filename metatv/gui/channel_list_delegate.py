"""Item delegate for the virtualized channel list.

Two responsibilities:

1. **Header rows** (grouped "Group by type" mode) keep the original single-line
   rich-text render — a ``CHANNEL_HTML_ROLE`` string painted through a
   single-line ``QTextDocument`` (``_paint_html_row``), unchanged from before
   this file grew density awareness.

2. **Channel rows** paint one of two densities set via :meth:`set_density`
   (persisted at ``Config.channel_list_density``, wired from Settings →
   Interface → Channel List):

   - ``"compact"`` — one line: ``[media icon][fav][title][quality chip]``
     left-aligned, then ``[year][language chip][rating chip]`` right-aligned
     flush to the row's right edge.
   - ``"comfy"`` (default) — two lines: line 1 is
     ``[media icon][fav][title]`` + a right-aligned ``[year]``; line 2 is the
     muted badge row ``[language][quality][category]`` + a rating glyph.

   Chips are painted as rounded rects using the same colour logic as
   ``badge_utils`` (quality via the shared ``_QUALITY_COLORS`` map, region via
   the platform/geographic split) — all colours are theme tokens, never
   literals. The title is elided (``Qt.TextElideMode.ElideRight``) against a
   *fixed* box computed from the other cells' measured widths, so a long title
   can never push a chip out of the row.

Both densities read the structured per-field roles added to
``ChannelListModel`` (``TITLE_ROLE``, ``YEAR_ROLE``, ...) rather than the
composed ``DisplayRole``/``CHANNEL_HTML_ROLE`` strings — those two roles stay
available unchanged for header rows and any other reader (tests,
accessibility). The playback-state separator glyph (·/▶/✓) and the unviewed
watch-for marker (🚨) that ``CHANNEL_HTML_ROLE`` carries are NOT part of either
density's fixed field arrangement (owner-locked spec) — a later slice can add
them back to the comfy badge row if wanted.

The row-math is factored into pure functions (``right_aligned_rects``,
``stacked_line_rects``) that take/return plain ``QRect`` — no painter or style
dependency — so layout correctness is unit-testable without rendering pixels.
"""

from __future__ import annotations

from typing import NamedTuple, Optional

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFontMetrics,
    QPalette,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from metatv.core.channel_name_utils import PLATFORM_CODES, quality_display
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.badge_utils import _QUALITY_COLORS
from metatv.gui.channel_list_model import (
    CATEGORY_ROLE,
    CHANNEL_HTML_ROLE,
    FAV_GLYPH_ROLE,
    LANGUAGE_ROLE,
    MEDIA_ICON_ROLE,
    QUALITY_TOKEN_ROLE,
    RATING_ROLE,
    ROW_KIND_ROLE,
    TITLE_ROLE,
    YEAR_ROLE,
)

DENSITY_COMPACT = "compact"
DENSITY_COMFY = "comfy"
_VALID_DENSITIES = (DENSITY_COMPACT, DENSITY_COMFY)

# Structural spacing (not a colour/font-size — px literals are fine inline
# per CLAUDE.md's styles rule).
_ROW_V_PAD = 4       # vertical padding top+bottom of a single-line/compact row
_LINE_GAP = 2         # gap between comfy's two stacked text lines
_CELL_GAP = 6         # horizontal gap between adjacent cells
_CHIP_H_PAD = 5       # chip internal horizontal padding (mirrors badge_utils' "1px 5px")
_CHIP_RADIUS = 3      # chip corner radius (mirrors badge_utils' "border-radius: 3px")

# Rating chip/glyph colours — local to this delegate (not a channel-name lookup
# table, so it doesn't belong in channel_name_utils.py); values are theme tokens.
_RATING_CHIP_BG: dict[int, str] = {1: _theme.COLOR_OK, -1: _theme.COLOR_ERR}


class _Cell(NamedTuple):
    """One paintable unit: either a plain text run or a coloured chip."""

    text: str
    is_chip: bool
    fg: str        # QColor-constructible token/hex (theme.* or a QColor.name())
    bg: Optional[str] = None   # chip background token (chip only)


# ---------------------------------------------------------------------------
# Pure rect math — unit-testable without a painter/style.
# ---------------------------------------------------------------------------

def right_aligned_rects(container: QRect, widths: list[int], spacing: int) -> list[QRect]:
    """Lay out ``widths`` left-to-right so the LAST one sits flush on ``container``'s
    right edge (its ``.right()`` equals ``container.right()``).

    Used for the compact row's right-hand group (year/language/rating) and the
    comfy row's single right-aligned year cell. Returns ``[]`` for an empty
    ``widths`` list.
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


def stacked_line_rects(container: QRect, line_height: int, gap: int) -> tuple[QRect, QRect]:
    """Split ``container`` into two vertically-stacked line rects (line1 above
    line2), each ``line_height`` tall with ``gap`` between them, centred as a
    block within ``container``. Powers the comfy (two-line) layout.
    """
    total = 2 * line_height + gap
    top = container.top() + max(0, (container.height() - total) // 2)
    line1 = QRect(container.left(), top, container.width(), line_height)
    line2 = QRect(container.left(), top + line_height + gap, container.width(), line_height)
    return line1, line2


# ---------------------------------------------------------------------------
# Cell builders — map a raw role value to a paintable _Cell (or None to omit).
# ---------------------------------------------------------------------------

def _year_cell(year: str) -> Optional[_Cell]:
    if not year:
        return None
    return _Cell(year, False, _theme.COLOR_MUTED)


def _quality_cell(token: str) -> Optional[_Cell]:
    if not token:
        return None
    upper = token.upper()
    bg = _QUALITY_COLORS.get(upper, _theme.COLOR_FAINT)
    return _Cell(quality_display(upper), True, _theme.COLOR_TEXT_HI, bg)


def _language_cell(region: str) -> Optional[_Cell]:
    if not region:
        return None
    bg = _theme.OVERLAY_PLATFORM_BADGE if region in PLATFORM_CODES else _theme.OVERLAY_15
    return _Cell(region, True, _theme.COLOR_TEXT_HI, bg)


def _category_cell(category: str) -> Optional[_Cell]:
    if not category:
        return None
    return _Cell(category, True, _theme.COLOR_MUTED, _theme.OVERLAY_08)


def _rating_chip_cell(rating: int) -> Optional[_Cell]:
    """Compact-mode rating: a coloured chip (like=green, dislike=red)."""
    if not rating:
        return None
    glyph = _icons.like_icon if rating > 0 else _icons.dislike_icon
    bg = _RATING_CHIP_BG[1 if rating > 0 else -1]
    return _Cell(glyph, True, _theme.COLOR_TEXT_HI, bg)


def _rating_glyph_cell(rating: int) -> Optional[_Cell]:
    """Comfy line-2 rating: a plain glyph in the muted/secondary token."""
    if not rating:
        return None
    glyph = _icons.like_icon if rating > 0 else _icons.dislike_icon
    return _Cell(glyph, False, _theme.COLOR_MUTED)


class ChannelRowDelegate(QStyledItemDelegate):
    """Paints channel rows in one of two densities; header rows unchanged."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._density: str = DENSITY_COMFY

    def set_density(self, density: str) -> None:
        """Set the row density ("compact" or "comfy"); unknown values fall back to comfy."""
        self._density = density if density in _VALID_DENSITIES else DENSITY_COMFY

    @property
    def density(self) -> str:
        return self._density

    # ── QStyledItemDelegate overrides ───────────────────────────────────────

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fm = QFontMetrics(opt.font)
        line_h = fm.height()
        row_kind = index.data(ROW_KIND_ROLE)
        if row_kind == "header" or self._density != DENSITY_COMFY:
            height = line_h + 2 * _ROW_V_PAD
        else:
            height = 2 * line_h + _LINE_GAP + 2 * _ROW_V_PAD
        return QSize(option.rect.width(), height)

    def paint(self, painter, option, index) -> None:  # noqa: N802
        if index.data(ROW_KIND_ROLE) == "header":
            self._paint_html_row(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        default_color = self._resolve_default_color(opt, index)

        # Draw the row chrome (background, selection, hover, focus) with NO
        # text — the fields are painted by hand below.
        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)
        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget
        )

        painter.save()
        painter.setClipRect(text_rect)
        if self._density == DENSITY_COMPACT:
            self._paint_compact(painter, text_rect, index, default_color, opt.font)
        else:
            self._paint_comfy(painter, text_rect, index, default_color, opt.font)
        painter.restore()

    # ── Header-row rendering (unchanged behaviour) ──────────────────────────

    def _paint_html_row(self, painter, option, index) -> None:
        """Original single-line CHANNEL_HTML_ROLE render — used for header rows."""
        html = index.data(CHANNEL_HTML_ROLE)
        if not html:
            super().paint(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget is not None else QApplication.style()
        default_color = self._resolve_default_color(opt, index)

        doc = QTextDocument()
        doc.setDocumentMargin(0)
        doc.setDefaultFont(opt.font)
        text_option = QTextOption()
        text_option.setWrapMode(QTextOption.WrapMode.NoWrap)
        doc.setDefaultTextOption(text_option)
        doc.setHtml(f'<span style="color:{default_color.name()}">{html}</span>')

        opt.text = ""
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        text_rect = style.subElementRect(
            QStyle.SubElement.SE_ItemViewItemText, opt, opt.widget
        )
        painter.save()
        painter.setClipRect(text_rect)
        y = text_rect.y() + max(0.0, (text_rect.height() - doc.size().height()) / 2)
        painter.translate(text_rect.x(), y)
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette = opt.palette
        doc.documentLayout().draw(painter, ctx)
        painter.restore()

    # ── Shared helpers ───────────────────────────────────────────────────────

    def _resolve_default_color(self, opt: QStyleOptionViewItem, index) -> QColor:
        """Default colour for non-chip text: highlight when selected, else the
        row's ForegroundRole brush (dimmed for degraded/watched rows) or palette text.
        """
        if opt.state & QStyle.StateFlag.State_Selected:
            return opt.palette.color(QPalette.ColorRole.HighlightedText)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            return fg.color()
        return opt.palette.color(QPalette.ColorRole.Text)

    def _draw_text(self, painter, rect: QRect, text: str, color, font) -> None:
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def _cell_width(self, fm: QFontMetrics, cell: _Cell) -> int:
        w = fm.horizontalAdvance(cell.text)
        return w + 2 * _CHIP_H_PAD if cell.is_chip else w

    def _paint_cell(self, painter, rect: QRect, cell: _Cell, font) -> None:
        painter.setFont(font)
        if cell.is_chip:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(cell.bg))
            painter.drawRoundedRect(rect, _CHIP_RADIUS, _CHIP_RADIUS)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QColor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, cell.text)
        else:
            painter.setPen(QColor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cell.text)

    # ── Compact (one line) ───────────────────────────────────────────────────

    def _paint_compact(self, painter, rect: QRect, index, default_color, font) -> None:
        fm = QFontMetrics(font)
        media_icon = index.data(MEDIA_ICON_ROLE) or ""
        fav_glyph = index.data(FAV_GLYPH_ROLE) or ""
        title = index.data(TITLE_ROLE) or ""
        quality_cell = _quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")

        right_cells = [c for c in (
            _year_cell(index.data(YEAR_ROLE) or ""),
            _language_cell(index.data(LANGUAGE_ROLE) or ""),
            _rating_chip_cell(index.data(RATING_ROLE) or 0),
        ) if c is not None]
        right_widths = [self._cell_width(fm, c) for c in right_cells]
        right_rects = right_aligned_rects(rect, right_widths, _CELL_GAP)
        right_group_left = (
            right_rects[0].left() - _CELL_GAP if right_rects
            else rect.left() + rect.width()
        )

        x = rect.left()
        for glyph in (media_icon, fav_glyph):
            if not glyph:
                continue
            w = fm.horizontalAdvance(glyph)
            self._draw_text(painter, QRect(x, rect.top(), w, rect.height()), glyph, default_color, font)
            x += w + _CELL_GAP

        quality_w = self._cell_width(fm, quality_cell) if quality_cell else 0
        title_box_w = max(
            0, right_group_left - x - (quality_w + _CELL_GAP if quality_cell else 0)
        )
        title_box = QRect(x, rect.top(), title_box_w, rect.height())
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, title_box_w)
        self._draw_text(painter, title_box, elided, default_color, font)

        if quality_cell:
            q_rect = QRect(x + title_box_w + _CELL_GAP, rect.top(), quality_w, rect.height())
            self._paint_cell(painter, q_rect, quality_cell, font)

        for cell, r in zip(right_cells, right_rects):
            self._paint_cell(painter, r, cell, font)

    # ── Comfy (two lines) ────────────────────────────────────────────────────

    def _paint_comfy(self, painter, rect: QRect, index, default_color, font) -> None:
        fm = QFontMetrics(font)
        line1, line2 = stacked_line_rects(rect, fm.height(), _LINE_GAP)

        media_icon = index.data(MEDIA_ICON_ROLE) or ""
        fav_glyph = index.data(FAV_GLYPH_ROLE) or ""
        title = index.data(TITLE_ROLE) or ""
        year_cell = _year_cell(index.data(YEAR_ROLE) or "")

        # Line 1: media icon + fav + title (elided) left, year right-aligned.
        year_w = self._cell_width(fm, year_cell) if year_cell else 0
        year_rects = right_aligned_rects(line1, [year_w], _CELL_GAP) if year_cell else []

        x = line1.left()
        for glyph in (media_icon, fav_glyph):
            if not glyph:
                continue
            w = fm.horizontalAdvance(glyph)
            self._draw_text(painter, QRect(x, line1.top(), w, line1.height()), glyph, default_color, font)
            x += w + _CELL_GAP

        title_right = year_rects[0].left() - _CELL_GAP if year_rects else line1.left() + line1.width()
        title_box_w = max(0, title_right - x)
        title_box = QRect(x, line1.top(), title_box_w, line1.height())
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, title_box_w)
        self._draw_text(painter, title_box, elided, default_color, font)

        if year_cell:
            self._paint_cell(painter, year_rects[0], year_cell, font)

        # Line 2: badge row — language, quality, category chips + rating glyph,
        # all in the muted/secondary token family.
        cells = [c for c in (
            _language_cell(index.data(LANGUAGE_ROLE) or ""),
            _quality_cell(index.data(QUALITY_TOKEN_ROLE) or ""),
            _category_cell(index.data(CATEGORY_ROLE) or ""),
            _rating_glyph_cell(index.data(RATING_ROLE) or 0),
        ) if c is not None]
        lx = line2.left()
        for cell in cells:
            w = self._cell_width(fm, cell)
            c_rect = QRect(lx, line2.top(), w, line2.height())
            self._paint_cell(painter, c_rect, cell, font)
            lx += w + _CELL_GAP
