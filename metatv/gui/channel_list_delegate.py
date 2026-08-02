"""Item delegate for the virtualized channel list.

Two responsibilities:

1. **Header rows** (grouped "Group by type" mode) keep the original single-line
   rich-text render — a ``CHANNEL_HTML_ROLE`` string painted through a
   single-line ``QTextDocument`` (``_paint_html_row``), unchanged from before
   this file grew density awareness.

2. **Channel rows** paint one of three densities set via :meth:`set_density`
   (persisted at ``Config.channel_list_density``, wired from Settings →
   Interface → Channel List):

   - ``"compact"`` — one line: ``[media icon][fav][glyph][🚨][title][quality chip]``
     left-aligned, then ``[year][language chip][rating chip]`` right-aligned
     flush to the row's right edge.
   - ``"comfy"`` (default) — two lines: line 1 is
     ``[media icon][fav][glyph][🚨][title][quality chip]`` (the quality chip hugs
     the title — no stretch between them) left, then right-aligned flush to the
     row's right edge, in this order: ``[year][region chip][subtitle marker
     chip][secondary language chip][primary language chip]`` — the channel's
     OWN (honest) language always sits furthest right. Line 2 is the muted
     badge row: a rating glyph left, then the clean collection chip
     (``detected_collection`` — the category with its leading marker stripped)
     right-aligned.
   - ``"comfy_plus"`` — comfy's line 1, PLUS a middle line of the channel's plot
     text (elided to one line, muted token) when ``PLOT_ROLE`` is non-empty,
     PLUS comfy's badge-row line. A row with no plot renders IDENTICALLY to
     comfy (2 lines, not a 3-line row with an empty gap) — both ``sizeHint``
     and ``paint`` branch on whether ``PLOT_ROLE`` is populated.

   The playback-state separator glyph (·/▶/✓) appears immediately before the
   title; its colour is determined per the original logic (watched-green for
   completed, Resume-orange for in-progress, None/neutral for unwatched/live).
   The unviewed watch-for marker (🚨) appears immediately before the title text
   when the channel is an unviewed match. Both glyphs are painted from structured
   ``PLAYBACK_GLYPH_ROLE``/``PLAYBACK_GLYPH_COLOR_ROLE``/``MATCH_MARKER_ROLE``
   roles populated by the model.

   Chips are painted as rounded rects using the same colour logic as
   ``badge_utils`` (quality via the shared ``_quality_colors()`` map, region via
   the platform/geographic split) — all colours are theme tokens, never
   literals. The title is elided (``Qt.TextElideMode.ElideRight``) against a
   *fixed* box computed from the other cells' measured widths, so a long title
   can never push a chip out of the row.

Poster thumbnails (comfy/comfy_plus only, opt-out via ``set_thumbnails_enabled``
— never painted in compact) reserve a FIXED ``_THUMB_W``x``_THUMB_H`` (2:3) rect
flush to the row's left edge, before the media icon; the rest of the row's
content is laid out in the narrower remaining rect. ``paint`` fetches the pixmap
via ``ImageCache.get_image_sync`` — a cache-hit-only lookup that is safe to call
from the paint path (never downloads, never touches the network) — and falls
back to a placeholder tile (rounded rect in a muted token + the title's first
letter) when the cache misses. Actually fetching an uncached image is the
VIEWPORT-ONLY hydrator's job (``channel_list_thumbnails.py``), never the
delegate's — the delegate only ever reads what's already on disk.
``sizeHint`` grows a row to fit the reserved thumbnail height when it would
otherwise be shorter (e.g. a plain 2-line comfy row); comfy_plus rows already
tall enough from their own content are unaffected.

All three densities read the structured per-field roles added to
``ChannelListModel`` (``TITLE_ROLE``, ``YEAR_ROLE``, ``PLOT_ROLE``, ...) rather
than the composed ``DisplayRole``/``CHANNEL_HTML_ROLE`` strings — those two
roles stay available unchanged for header rows and any other reader (tests,
accessibility).

The row-math is factored into pure functions (``right_aligned_rects``,
``stacked_line_rects``, ``stacked_line_rects_n``) that take/return plain
``QRect`` — no painter or style dependency — so layout correctness is
unit-testable without rendering pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple, Optional

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
from metatv.gui.badge_utils import _quality_colors
from metatv.gui.channel_list_model import (
    CHANNEL_HTML_ROLE,
    COLLECTION_ROLE,
    FAV_GLYPH_ROLE,
    LANGUAGE_ROLE,
    MATCH_MARKER_ROLE,
    MEDIA_ICON_ROLE,
    PLAYBACK_GLYPH_COLOR_ROLE,
    PLAYBACK_GLYPH_ROLE,
    PLOT_ROLE,
    POSTER_URL_ROLE,
    PRIMARY_LANGUAGE_ROLE,
    QUALITY_TOKEN_ROLE,
    RATING_ROLE,
    ROW_KIND_ROLE,
    SECONDARY_LANGUAGE_ROLE,
    SUBTITLE_MARKER_ROLE,
    TITLE_ROLE,
    VARIANT_COUNT_ROLE,
    YEAR_ROLE,
)

if TYPE_CHECKING:
    from metatv.core.image_cache import ImageCache

DENSITY_COMPACT = "compact"
DENSITY_COMFY = "comfy"
DENSITY_COMFY_PLUS = "comfy_plus"
_VALID_DENSITIES = (DENSITY_COMPACT, DENSITY_COMFY, DENSITY_COMFY_PLUS)

# Structural spacing (not a colour/font-size — px literals are fine inline
# per CLAUDE.md's styles rule).
_ROW_V_PAD = 4       # vertical padding top+bottom of a single-line/compact row
_LINE_GAP = 2         # gap between comfy's two stacked text lines
_CELL_GAP = 6         # horizontal gap between adjacent cells
_CHIP_H_PAD = 5       # chip internal horizontal padding (mirrors badge_utils' "1px 5px")
_CHIP_RADIUS = 3      # chip corner radius (mirrors badge_utils' "border-radius: 3px")

# Poster-thumbnail geometry (comfy/comfy_plus only — never compact). Fixed 2:3
# aspect ratio, independent of font size, so the reserved rect never wobbles.
_THUMB_W = 32
_THUMB_H = 48         # 32 * 3/2 — 2:3 width:height
_THUMB_GAP = 8         # gap between the thumbnail and the rest of the row

def _rating_chip_bg() -> dict[int, str]:
    """Rating chip/glyph colours — local to this delegate (not a channel-name
    lookup table, so it doesn't belong in channel_name_utils.py); values are
    theme tokens, re-read fresh so a live theme switch applies."""
    return {1: _theme.COLOR_OK, -1: _theme.COLOR_ERR}


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


def stacked_line_rects_n(
    container: QRect, line_height: int, gap: int, count: int
) -> list[QRect]:
    """Split ``container`` into ``count`` vertically-stacked line rects, each
    ``line_height`` tall with ``gap`` between consecutive lines, centred as a
    block within ``container``. Generalizes :func:`stacked_line_rects` (the
    fixed 2-line convenience wrapper comfy uses) so comfy_plus can lay out its
    variable 2-or-3-line row (plot line collapses when a channel has no plot)
    with the same pure, painter-free math. Returns ``[]`` for ``count <= 0``.
    """
    if count <= 0:
        return []
    total = count * line_height + (count - 1) * gap
    top = container.top() + max(0, (container.height() - total) // 2)
    rects = []
    y = top
    for _ in range(count):
        rects.append(QRect(container.left(), y, container.width(), line_height))
        y += line_height + gap
    return rects


def stacked_line_rects(container: QRect, line_height: int, gap: int) -> tuple[QRect, QRect]:
    """Split ``container`` into two vertically-stacked line rects (line1 above
    line2), each ``line_height`` tall with ``gap`` between them, centred as a
    block within ``container``. Powers the comfy (two-line) layout.
    """
    line1, line2 = stacked_line_rects_n(container, line_height, gap, 2)
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
    bg = _quality_colors().get(upper, _theme.COLOR_FAINT)
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
    bg = _rating_chip_bg()[1 if rating > 0 else -1]
    return _Cell(glyph, True, _theme.COLOR_TEXT_HI, bg)


def _rating_glyph_cell(rating: int) -> Optional[_Cell]:
    """Comfy line-2 rating: a plain glyph in the muted/secondary token."""
    if not rating:
        return None
    glyph = _icons.like_icon if rating > 0 else _icons.dislike_icon
    return _Cell(glyph, False, _theme.COLOR_MUTED)


def _variant_badge_cell(count: int) -> Optional[_Cell]:
    """Collapsed-variant "×N" badge (Settings → Interface → "Collapse quality/
    language versions"). Omitted (None) for singleton/uncollapsed rows —
    ``ChannelListDTO.variant_count`` defaults to 1 whenever collapsing is off,
    so this is a no-op everywhere the setting is unused (same informational-chip
    styling as :func:`_category_cell` — muted, not a strong categorical color)."""
    if not count or count <= 1:
        return None
    return _Cell(f"×{count}", True, _theme.COLOR_MUTED, _theme.OVERLAY_08)


class ChannelRowDelegate(QStyledItemDelegate):
    """Paints channel rows in one of three densities; header rows unchanged."""

    def __init__(self, parent=None, image_cache: Optional["ImageCache"] = None) -> None:
        super().__init__(parent)
        self._density: str = DENSITY_COMFY
        self._image_cache = image_cache
        self._thumbnails_enabled: bool = False

    def set_density(self, density: str) -> None:
        """Set the row density ("compact"/"comfy"/"comfy_plus"); unknown values
        fall back to comfy."""
        self._density = density if density in _VALID_DENSITIES else DENSITY_COMFY

    @property
    def density(self) -> str:
        return self._density

    def set_thumbnails_enabled(self, enabled: bool) -> None:
        """Turn the comfy/comfy_plus poster thumbnail on/off (compact never
        shows one regardless of this flag)."""
        self._thumbnails_enabled = bool(enabled)

    @property
    def thumbnails_enabled(self) -> bool:
        return self._thumbnails_enabled

    def _comfy_plus_line_count(self, index) -> int:
        """comfy_plus is 3 lines when the row has plot text, else 2 (= comfy)."""
        return 3 if index.data(PLOT_ROLE) else 2

    def _shows_thumbnail(self, row_kind, index) -> bool:
        """Whether THIS row gets a reserved thumbnail rect: channel rows only,
        never header rows, never compact density, and only when enabled."""
        return (
            row_kind != "header"
            and self._density != DENSITY_COMPACT
            and self._thumbnails_enabled
        )

    # ── QStyledItemDelegate overrides ───────────────────────────────────────

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        fm = QFontMetrics(opt.font)
        line_h = fm.height()
        row_kind = index.data(ROW_KIND_ROLE)
        if row_kind == "header" or self._density == DENSITY_COMPACT:
            height = line_h + 2 * _ROW_V_PAD
        elif self._density == DENSITY_COMFY_PLUS:
            n = self._comfy_plus_line_count(index)
            height = n * line_h + (n - 1) * _LINE_GAP + 2 * _ROW_V_PAD
        else:  # DENSITY_COMFY
            height = 2 * line_h + _LINE_GAP + 2 * _ROW_V_PAD
        if self._shows_thumbnail(row_kind, index):
            height = max(height, _THUMB_H + 2 * _ROW_V_PAD)
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
        content_rect = text_rect
        if self._shows_thumbnail("channel", index):
            thumb_rect = self._thumbnail_rect(text_rect)
            self._paint_thumbnail(painter, thumb_rect, index)
            content_rect = QRect(
                text_rect.left() + _THUMB_W + _THUMB_GAP,
                text_rect.top(),
                max(0, text_rect.width() - (_THUMB_W + _THUMB_GAP)),
                text_rect.height(),
            )
        if self._density == DENSITY_COMPACT:
            self._paint_compact(painter, content_rect, index, default_color, opt.font)
        elif self._density == DENSITY_COMFY_PLUS:
            self._paint_comfy_plus(painter, content_rect, index, default_color, opt.font)
        else:
            self._paint_comfy(painter, content_rect, index, default_color, opt.font)
        painter.restore()

    # ── Poster thumbnail (comfy/comfy_plus only) ─────────────────────────────

    def _thumbnail_rect(self, row_rect: QRect) -> QRect:
        """Fixed ``_THUMB_W``x``_THUMB_H`` rect flush to ``row_rect``'s left
        edge, vertically centred within the row."""
        y = row_rect.top() + max(0, (row_rect.height() - _THUMB_H) // 2)
        return QRect(row_rect.left(), y, _THUMB_W, _THUMB_H)

    def _paint_thumbnail(self, painter, rect: QRect, index) -> None:
        """Paint the real poster (cache-hit only — never downloads from
        paint()) cropped to fill ``rect``, or a placeholder tile on a miss."""
        url = index.data(POSTER_URL_ROLE) or ""
        pixmap = None
        if url and self._image_cache is not None:
            pixmap = self._image_cache.get_image_sync(url)
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(
                rect.width(), rect.height(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = max(0, (scaled.width() - rect.width()) // 2)
            y = max(0, (scaled.height() - rect.height()) // 2)
            cropped = scaled.copy(x, y, rect.width(), rect.height())
            painter.drawPixmap(rect, cropped)
            return
        self._paint_thumbnail_placeholder(painter, rect, index)

    def _paint_thumbnail_placeholder(self, painter, rect: QRect, index) -> None:
        """Zero-network fallback: a muted rounded tile with the title's first
        letter centred — shown while an image is loading, on a load failure,
        or for a channel with no poster at all."""
        title = index.data(TITLE_ROLE) or ""
        letter = title.strip()[:1].upper() if title.strip() else "?"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(_theme.COLOR_FAINT))
        painter.drawRoundedRect(rect, _CHIP_RADIUS, _CHIP_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QColor(_theme.COLOR_MUTED))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, letter)

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
        playback_glyph = index.data(PLAYBACK_GLYPH_ROLE) or ""
        playback_color = index.data(PLAYBACK_GLYPH_COLOR_ROLE)
        match_marker = index.data(MATCH_MARKER_ROLE) or ""
        title = index.data(TITLE_ROLE) or ""
        quality_cell = _quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")

        right_cells = [c for c in (
            _variant_badge_cell(index.data(VARIANT_COUNT_ROLE) or 1),
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

        # Paint playback-state glyph (·/▶/✓) with optional color
        if playback_glyph:
            w = fm.horizontalAdvance(playback_glyph)
            glyph_color = playback_color if playback_color else default_color
            self._draw_text(painter, QRect(x, rect.top(), w, rect.height()), playback_glyph, glyph_color, font)
            x += w + _CELL_GAP

        # Paint unviewed match marker (🚨)
        if match_marker:
            w = fm.horizontalAdvance(match_marker)
            self._draw_text(painter, QRect(x, rect.top(), w, rect.height()), match_marker, default_color, font)
            x += w

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

    # ── Shared comfy/comfy_plus line painters ───────────────────────────────
    #
    # comfy is 2 lines (title+year, badge row); comfy_plus is the SAME 2 lines
    # plus a middle elided-plot line when the row has plot text (else it's
    # identical to comfy — see _comfy_plus_line_count). Both densities share
    # these per-line painters so the layout logic lives in exactly one place.

    def _paint_title_year_line(self, painter, line: QRect, index, default_color, font) -> None:
        """Line 1: media icon + fav + playback glyph + 🚨 + title (elided) +
        quality chip — left, with the quality chip hugging the title (no
        stretch between them, same idiom as the compact density: measure the
        chip's width and subtract it from the title's box BEFORE eliding, so
        it sits immediately after the title rather than floating).

        Right-aligned flush to ``line``'s right edge, left-to-right:
        ``[year][region chip][subtitle marker chip][secondary language
        chip][primary language chip]`` — the channel's OWN (honest) language
        (``detected_prefix``) always sits furthest right (owner spec); the
        region chip (``detected_region``) sits leftmost of the group since it
        answers a different question (where, not what language).
        """
        fm = QFontMetrics(font)
        media_icon = index.data(MEDIA_ICON_ROLE) or ""
        fav_glyph = index.data(FAV_GLYPH_ROLE) or ""
        playback_glyph = index.data(PLAYBACK_GLYPH_ROLE) or ""
        playback_color = index.data(PLAYBACK_GLYPH_COLOR_ROLE)
        match_marker = index.data(MATCH_MARKER_ROLE) or ""
        title = index.data(TITLE_ROLE) or ""
        quality_cell = _quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")

        # _language_cell is a generic "code chip" builder (region, language, or
        # a compound sub/dub marker like "AR-SUB" are all short code-shaped
        # tokens) — reused here for every right-group cell but the year so all
        # four chips share the exact same chip styling.
        right_cells = [c for c in (
            _year_cell(index.data(YEAR_ROLE) or ""),
            _language_cell(index.data(LANGUAGE_ROLE) or ""),            # region
            _language_cell(index.data(SUBTITLE_MARKER_ROLE) or ""),     # e.g. "AR-SUB"
            _language_cell(index.data(SECONDARY_LANGUAGE_ROLE) or ""),  # category's disagreeing language
            _language_cell(index.data(PRIMARY_LANGUAGE_ROLE) or ""),    # channel's own — furthest right
        ) if c is not None]
        right_widths = [self._cell_width(fm, c) for c in right_cells]
        right_rects = right_aligned_rects(line, right_widths, _CELL_GAP)
        right_group_left = (
            right_rects[0].left() - _CELL_GAP if right_rects
            else line.left() + line.width()
        )

        x = line.left()
        for glyph in (media_icon, fav_glyph):
            if not glyph:
                continue
            w = fm.horizontalAdvance(glyph)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), glyph, default_color, font)
            x += w + _CELL_GAP

        # Paint playback-state glyph (·/▶/✓) with optional color
        if playback_glyph:
            w = fm.horizontalAdvance(playback_glyph)
            glyph_color = playback_color if playback_color else default_color
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), playback_glyph, glyph_color, font)
            x += w + _CELL_GAP

        # Paint unviewed match marker (🚨)
        if match_marker:
            w = fm.horizontalAdvance(match_marker)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), match_marker, default_color, font)
            x += w

        quality_w = self._cell_width(fm, quality_cell) if quality_cell else 0
        title_right = right_group_left - (quality_w + _CELL_GAP if quality_cell else 0)
        title_box_w = max(0, title_right - x)
        title_box = QRect(x, line.top(), title_box_w, line.height())
        elided = fm.elidedText(title, Qt.TextElideMode.ElideRight, title_box_w)
        self._draw_text(painter, title_box, elided, default_color, font)

        if quality_cell:
            q_rect = QRect(x + title_box_w + _CELL_GAP, line.top(), quality_w, line.height())
            self._paint_cell(painter, q_rect, quality_cell, font)

        for cell, r in zip(right_cells, right_rects):
            self._paint_cell(painter, r, cell, font)

    def _paint_badge_line(self, painter, line: QRect, index, font) -> None:
        """Badge row — a rating glyph left, the clean collection chip
        (``detected_collection`` — the category with its leading marker
        stripped) right-aligned. Used as comfy's line 2 and comfy_plus's
        final line. Region/subtitle/language chips and the quality chip now
        live on line 1 (owner spec) — this line no longer carries them."""
        fm = QFontMetrics(font)
        collection_cell = _category_cell(index.data(COLLECTION_ROLE) or "")
        collection_w = self._cell_width(fm, collection_cell) if collection_cell else 0
        collection_rects = (
            right_aligned_rects(line, [collection_w], _CELL_GAP) if collection_cell else []
        )

        left_cells = [c for c in (
            # variant-count badge (#387) keeps its place on the badge row;
            # the chips it used to sit beside moved to line 1 (owner spec).
            _variant_badge_cell(index.data(VARIANT_COUNT_ROLE) or 1),
            _rating_glyph_cell(index.data(RATING_ROLE) or 0),
        ) if c is not None]
        lx = line.left()
        for cell in left_cells:
            w = self._cell_width(fm, cell)
            c_rect = QRect(lx, line.top(), w, line.height())
            self._paint_cell(painter, c_rect, cell, font)
            lx += w + _CELL_GAP

        if collection_cell:
            self._paint_cell(painter, collection_rects[0], collection_cell, font)

    def _paint_plot_line(self, painter, line: QRect, plot: str, font) -> None:
        """comfy_plus's middle line — the plot, elided to fit, muted token."""
        fm = QFontMetrics(font)
        elided = fm.elidedText(plot, Qt.TextElideMode.ElideRight, line.width())
        self._draw_text(painter, line, elided, _theme.COLOR_MUTED, font)

    # ── Comfy (two lines) ────────────────────────────────────────────────────

    def _paint_comfy(self, painter, rect: QRect, index, default_color, font) -> None:
        fm = QFontMetrics(font)
        line1, line2 = stacked_line_rects(rect, fm.height(), _LINE_GAP)
        self._paint_title_year_line(painter, line1, index, default_color, font)
        self._paint_badge_line(painter, line2, index, font)

    # ── Comfy+ (two or three lines — plot line collapses when absent) ───────

    def _paint_comfy_plus(self, painter, rect: QRect, index, default_color, font) -> None:
        fm = QFontMetrics(font)
        plot = index.data(PLOT_ROLE) or ""
        lines = stacked_line_rects_n(rect, fm.height(), _LINE_GAP, 3 if plot else 2)
        self._paint_title_year_line(painter, lines[0], index, default_color, font)
        if plot:
            self._paint_plot_line(painter, lines[1], plot, font)
            self._paint_badge_line(painter, lines[2], index, font)
        else:
            self._paint_badge_line(painter, lines[1], index, font)
