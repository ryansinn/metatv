"""Item delegate for the virtualized channel list — the V3 row.

Two responsibilities:

1. **Header rows** (grouped "Group by type" mode) keep the original single-line
   rich-text render — a ``CHANNEL_HTML_ROLE`` string painted through a
   single-line ``QTextDocument`` (``_paint_html_row``), untouched by any of
   this.

2. **Channel rows.** One grammar, three densities::

       [kind mark][artwork][ title            ][lang][4K][ ⋯ ]
                           [ Movie · 2000 · Thriller / Drama ]
                           [ plot, comfy+ only …            ]

   Density (``set_density``, persisted at ``Config.channel_list_density``,
   wired from Settings → Interface → Channel List) changes only how much of the
   stack renders — ``compact`` is the title line alone with no artwork,
   ``comfy`` adds the meta line, ``comfy_plus`` adds the plot when the row has
   one. A comfy_plus row with no plot renders IDENTICALLY to comfy rather than
   as a three-line row with a gap in it.

Three rules, in the order they matter
-------------------------------------

**Nothing moves when a row is selected.** The action slot at the right is
always reserved and only *painted* on hover or when the row is current. Row
geometry is computed by :func:`~metatv.gui.channel_row_layout.row_layout`,
which takes NO state argument — so a column that shifts on selection is not
something to remember to avoid, it is unrepresentable. That is also what makes
the design work by touch and by keyboard, where hover does not exist.

**Kind is structural.** Movie, series and live each get their own mark in the
row's leftmost gutter, their own artwork shape (a 2:3 poster, or a SQUARE tile
for a live channel, whose logo is a square asset), and their own first word on
the meta line. They do not have the same facts, so they do not get the same row.

**Only render what exists.** Quality paints on the 6.6% of rows that have a
value and nowhere else — it is not a reserved column, because reserving one
would imply every title has a claim to make (live 26.2% / movie 3.3% /
series 2.0%). *Reserve what is always true; render what is sometimes true.*
Ratings are not in the row at all: they are not objective, and in this library
the top of the range is a wall of identical 10.0s.

Emphasis tiers (#298, carried forward)
--------------------------------------

- **Tier 1, FILL** — the language family only (the channel's own language, the
  category's disagreeing language, any sub/dub marker: one hue, one treatment).
  Owner's call: it is the highest-value facet after the title. It lives in the
  right-hand rail, inward of quality.
- **Tier 2, TINTED TEXT, no box** — the meta line, in full. Region/platform and
  genre keep their facet hues; kind, year, collection and the variant count are
  neutral, because the palette publishes one hue per facet and no two may share
  one. V3's meta line *is* tier 2 applied to a whole sentence.
- **Tier 3, OUTLINE** — quality alone. It is the row's one CLAIM rather than a
  category, so it earns a border when nothing else does.

Selection is a TINT (``primary.4``) plus a marker bar, not the saturated accent
it used to be — which is why a selected row keeps its normal text ramp and its
facet hues instead of flattening every cell onto a highlight foreground. The
row paints its own chrome for this reason; ``QStyle``'s item background is
full-bleed and cannot be inset or rounded.

Slot ORDER is declared once, in :data:`ROW_META_ORDER` and
:data:`ROW_RAIL_ORDER` — the meta line and the rail each ask that constant for
the subset they show, rather than each building its own tuple, which is how the
two previously drifted apart.

Artwork (comfy/comfy_plus only, opt-out via ``set_thumbnails_enabled`` — never
painted in compact) reserves a FIXED rect, so the columns after it never wobble.
``paint`` fetches the pixmap via ``ImageCache.get_image_sync`` — a cache-hit-only
lookup that is safe on the paint path (never downloads, never touches the
network) — and falls back to a sunk tile carrying the row's kind mark on a miss.
Actually fetching an uncached image is the VIEWPORT-ONLY hydrator's job
(``channel_list_thumbnails.py``), never the delegate's.

All three densities read the structured per-field roles on ``ChannelListModel``
(``TITLE_ROLE``, ``MEDIA_KIND_ROLE``, ``YEAR_ROLE``, …) rather than the composed
``DisplayRole``/``CHANNEL_HTML_ROLE`` strings — those two stay available
unchanged for header rows and any other reader (tests, accessibility).

Row geometry is factored out entirely into ``channel_row_layout`` — pure
functions over ``QRect`` with no painter, no theme and no row state, so layout
correctness is unit-testable without rendering pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QTextDocument,
    QTextOption,
)
from PyQt6.QtWidgets import (
    QApplication,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
)

from metatv.core.channel_name_utils import PLATFORM_CODES
from metatv.gui import channel_row_layout as _layout
from metatv.gui import channel_row_lead as _lead
from metatv.gui import icon_utils as _icon_utils
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui import channel_list_section_band as _band
from metatv.gui.channel_list_roles import LABEL_ROW_KINDS
from metatv.gui.channel_list_model import (
    CATEGORY_ROLE,
    CHANNEL_HTML_ROLE,
    COLLECTION_ROLE,
    FAV_GLYPH_ROLE,
    GENRE_ROLE,
    LEAGUE_ROLE,
    GENRES_ROLE,
    LANGUAGE_ROLE,
    MATCH_MARKER_ROLE,
    MEDIA_KIND_ROLE,
    PLAYBACK_GLYPH_COLOR_ROLE,
    PLAYBACK_GLYPH_ROLE,
    PLOT_ROLE,
    POSTER_URL_ROLE,
    PRIMARY_LANGUAGE_ROLE,
    QUALITY_TOKEN_ROLE,
    SPORT_ROLE,
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

# Platform-names style (Settings → Interface → Channel List → "Platform names"):
# "auto" (default) resolves per-density in _effective_platform_style — full
# brand name in comfy/comfy_plus, short code in compact; "full"/"short"
# override the density for every row regardless.
PLATFORM_STYLE_AUTO = "auto"
PLATFORM_STYLE_FULL = "full"
PLATFORM_STYLE_SHORT = "short"
_VALID_PLATFORM_STYLES = (PLATFORM_STYLE_AUTO, PLATFORM_STYLE_FULL, PLATFORM_STYLE_SHORT)


# Structural spacing. The ROW's geometry now lives in ``channel_row_layout``
# (one module, no painter, no row state — see its docstring for why); the names
# below are re-exported so a caller that only wants "the row's edge padding"
# still finds it here, and are the ONLY place this file states a px value.
_ROW_H_PAD = _layout.ROW_PAD_H
_ROW_V_PAD = _layout.ROW_PAD_V
_LINE_GAP = _layout.LINE_GAP
#: Artwork well — 2:3 poster (movie/series) or the square tile a live channel
#: gets instead. ``_THUMB_W``/``_THUMB_H`` keep their old names because they are
#: what the thumbnail hydrator and its tests ask for.
_THUMB_W = _layout.ART_W
_THUMB_H = _layout.ART_H
_THUMB_GAP = _layout.ART_GAP

# Cell-level spacing — these belong to the CHIPS, not to the row, so they stay.
_CELL_GAP = 6         # horizontal gap between adjacent cells
#: Gap on either side of the "·" that joins meta-line segments. Narrower than
#: ``_CELL_GAP``: the separator is already doing the separating, and a full gap
#: on both sides of it makes one sentence read as three fragments.
_META_GAP = 4
#: The meta line's segment separator. A MIDDLE DOT (U+00B7), never a bullet or a
#: pipe — it is the lightest mark that still reads as "and also", which is what
#: keeps ``Movie · 2000 · Thriller / Drama`` scanning as one line of prose.
_META_SEPARATOR = "\u00b7"
#: How genres join INSIDE the genre segment. A slash, not a comma: the genres
#: are alternatives describing one title, and the mockup's own rows read
#: "Thriller / Drama".
_GENRE_JOINER = " / "

_CHIP_H_PAD = 7       # chip internal horizontal padding — matches theme.LANG_CHIP
                      # ("padding: 1px 7px"), the sidebar pill these should look like
_THUMB_RADIUS = _layout.FILL_RADIUS   # poster/tile corner radius — the same
                      # radius as the row fill it sits inside, so the artwork
                      # reads as part of the row rather than as a card on it.
_OUTLINE_RADIUS = 3   # TIER 3 corner radius. Deliberately NOT the pill radius
                      # below: a filled pill and an outlined pill of the same
                      # shape read as two colours of one thing, when the whole
                      # point of the tiers is that they are different KINDS of
                      # thing. A tight rounded rect also stops a short outlined
                      # chip ("2024") from rendering as a squashed lozenge.
_OUTLINE_V_INSET = 1  # px inset top+bottom on a tier-3 box. The stroke is drawn
                      # ON the rect's edge, and the row's clip rect cuts the
                      # line rect exactly — so a box at full line height loses
                      # its top and bottom edges to clipping.
_CHIP_RADIUS = 8      # chip corner radius — matches LANG_CHIP's "border-radius: 8px".
                      # Clamped to half the chip height at paint time
                      # (_chip_radius) so a short chip becomes a true pill rather
                      # than an over-rounded lozenge.

# The colour-conversion chokepoint lives in ``token_color`` — see that module
# for why a bare ``QColor(token)`` is a silent bug. Bound to the private name
# this file has always used it under.
from metatv.gui.token_color import to_qcolor as _to_qcolor  # noqa: E402

# ---------------------------------------------------------------------------
# Pure rect math — unit-testable without a painter/style.
# ---------------------------------------------------------------------------

#: Row/line geometry is ``channel_row_layout``'s job — these names stay bound
#: here because they are the delegate's published surface (tests and the
#: thumbnail hydrator import them from this module), but there is exactly one
#: implementation and it lives in the layout module.
right_aligned_rects = _layout.right_aligned_rects
stacked_line_rects_n = _layout.stacked_lines


def stacked_line_rects(container: QRect, line_height: int, gap: int) -> tuple[QRect, QRect]:
    """Two vertically-stacked line rects — the fixed-2 convenience wrapper."""
    line1, line2 = _layout.stacked_lines(container, line_height, gap, 2)
    return line1, line2


# Cell values, the slot order and the builders live in ``channel_row_cells`` —
# see that module's docstring for the split. Re-exported here because this
# module is the row's published surface.
from metatv.gui.channel_row_cells import (  # noqa: E402
    CHIP_SLOT_COLLECTION,
    CHIP_SLOT_GENRE,
    CHIP_SLOT_LANGUAGE,
    CHIP_SLOT_LANGUAGE_2,
    CHIP_SLOT_LEAGUE,
    CHIP_SLOT_QUALITY,
    CHIP_SLOT_REGION,
    CHIP_SLOT_SPORT,
    CHIP_SLOT_SUBTITLE,
    CHIP_SLOT_VARIANTS,
    CHIP_SLOT_YEAR,
    ROW_META_ORDER,
    ROW_RAIL_ORDER,
    _KIND_ICON_ROLES,
    _category_cell,
    _Cell,
    _edged_on_selection,
    _genre_cells,
    _league_cell,
    _sport_cell,
    _language_cell,
    _ordered,
    _quality_cell,
    _region_or_platform_cell,
    _variant_badge_cell,
    _year_cell,
)


class ChannelRowDelegate(QStyledItemDelegate):
    """Paints channel rows in one of three densities; header rows unchanged."""

    def __init__(self, parent=None, image_cache: Optional["ImageCache"] = None) -> None:
        super().__init__(parent)
        self._density: str = DENSITY_COMFY
        self._image_cache = image_cache
        self._thumbnails_enabled: bool = False
        self._platform_name_style: str = PLATFORM_STYLE_AUTO
        # Hit regions for delegate-painted chips (#24), keyed by model row and
        # rebuilt on each row's paint. Bounded by what is on screen: a row that
        # scrolls away is re-recorded the next time it paints, and its stale
        # entry is harmless because the view only ever queries the row under the
        # cursor. _painting_row scopes the recording in _paint_cell, which does
        # not otherwise know which row it belongs to.
        self._hit_regions: dict[int, list[tuple[QRect, _Cell]]] = {}
        self._painting_row: Optional[int] = None
        self._row_discriminator: str = ""   # see set_row_discriminator

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

    def set_row_discriminator(self, mode: str) -> None:
        """What the leading slot shows: "sport", "region", or "" (collapsed).

        Told, not worked out — "what still varies" is a fact about the QUERY and
        a delegate sees one row. Rule: ``channel_row_lead``. Unknown → ``""``."""
        self._row_discriminator = mode if mode in _lead.VALID_DISCRIMINATORS else ""

    @property
    def row_discriminator(self) -> str:
        return self._row_discriminator

    def set_platform_name_style(self, style: str) -> None:
        """Set the platform chip's name style ("auto"/"full"/"short",
        Settings → Interface → Channel List → "Platform names"); unknown
        values fall back to "auto"."""
        self._platform_name_style = style if style in _VALID_PLATFORM_STYLES else PLATFORM_STYLE_AUTO

    @property
    def platform_name_style(self) -> str:
        return self._platform_name_style

    def _effective_platform_style(self) -> str:
        """Resolve the configured Platform-names style against this row's
        density: "auto" -> full brand name in comfy/comfy_plus, short code
        in compact (owner spec #257); an explicit "full"/"short" override
        wins regardless of density. Density-awareness is a control-layer
        decision that belongs here (the delegate already tracks density),
        never inside :func:`~metatv.core.channel_name_utils.platform_display`
        itself."""
        if self._platform_name_style in (PLATFORM_STYLE_FULL, PLATFORM_STYLE_SHORT):
            return self._platform_name_style
        return PLATFORM_STYLE_SHORT if self._density == DENSITY_COMPACT else PLATFORM_STYLE_FULL

    def _comfy_plus_line_count(self, index) -> int:
        """comfy_plus is 3 lines when the row has plot text, else 2 (= comfy)."""
        return 3 if index.data(PLOT_ROLE) else 2

    def _shows_thumbnail(self, row_kind, index) -> bool:
        """Whether THIS row reserves an artwork well: channel rows only, never
        header rows, never compact density, and only when enabled.

        The KIND MARK is not covered by this — it is structural and paints on
        every channel row regardless, including compact and including rows with
        thumbnails switched off. Artwork is the optional half of "what is this";
        the mark is the half that is always true.
        """
        return (
            row_kind != "header"
            and self._density != DENSITY_COMPACT
            and self._thumbnails_enabled
        )

    @staticmethod
    def _kind_of(index) -> str:
        """This row's normalised media kind ("live"/"movie"/"series"/"")."""
        return index.data(MEDIA_KIND_ROLE) or ""

    def _line_count(self, index) -> int:
        """Text lines this row stacks: 1 compact, 2 comfy, 3 comfy+ with plot.

        comfy_plus with no plot renders IDENTICALLY to comfy — two lines, not a
        three-line row with an empty gap.
        """
        if self._density == DENSITY_COMPACT:
            return 1
        if self._density == DENSITY_COMFY_PLUS and index.data(PLOT_ROLE):
            return 3
        return 2

    # ── Fonts ────────────────────────────────────────────────────────────────
    #
    # The row states its own sizes from the FONT_* scale rather than inheriting
    # the view's font, because the title/meta relationship IS the design: the
    # title has to lead on size AND weight, and a meta line at the same size as
    # its title reads as two titles.

    @staticmethod
    def _sized_font(font, token: str, *, demibold: bool = False):
        """A COPY of *font* at the FONT_* *token*'s pixel size.

        A copy, always: the passed font is the shared style option's, and
        mutating it in place would resize every cell painted afterwards.
        """
        out = QFont(font)
        out.setPixelSize(int(token.replace("px", "")))
        if demibold:
            out.setWeight(QFont.Weight.DemiBold)
        return out

    def _title_font(self, font):
        """The title: one step up the scale AND DemiBold. Colour alone moves it
        one Radix step; size and weight are what make it read as the row's
        subject at a glance."""
        return self._sized_font(font, _theme.FONT_LG, demibold=True)

    def _meta_font(self, font):
        """The meta line and every chip: one step DOWN from body, so the line
        recedes behind the title instead of competing with it."""
        return self._sized_font(font, _theme.FONT_SM)

    # ── QStyledItemDelegate overrides ───────────────────────────────────────

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        row_kind = index.data(ROW_KIND_ROLE)
        if row_kind == "header":
            return QSize(option.rect.width(), _band.band_height(opt.font))
        if row_kind in LABEL_ROW_KINDS:
            return QSize(option.rect.width(), QFontMetrics(opt.font).height() + 2 * _ROW_V_PAD)

        title_h = QFontMetrics(self._title_font(opt.font)).height()
        meta_h = QFontMetrics(self._meta_font(opt.font)).height()
        lines = self._line_count(index)
        stack = title_h + (lines - 1) * (meta_h + _LINE_GAP)

        # Height comes from the LAYOUT module, and deliberately does not depend
        # on this row's own artwork shape — a live channel's square tile
        # centres inside the same row height a poster gets, rather than giving
        # a mixed list two rhythms. See ``row_height``.
        return QSize(option.rect.width(), _layout.row_height(
            stack, has_art=self._shows_thumbnail(row_kind, index)
        ))

    def paint(self, painter, option, index) -> None:  # noqa: N802
        if index.data(ROW_KIND_ROLE) in LABEL_ROW_KINDS:
            opt = QStyleOptionViewItem(option)
            self.initStyleOption(opt, index)
            # The section band is PAINTED — a flex:1 rule and a segmented
            # control have no rich-text equivalent. A person sub-heading is one
            # line of type and takes the shared HTML path.
            if not _band.paint_row(painter, option.rect, index, opt.font):
                self._paint_html_row(painter, option, index)
            return

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        default_color = self._resolve_default_color(opt, index)
        meta_font = self._meta_font(opt.font)

        kind = self._kind_of(index)
        has_art = self._shows_thumbnail("channel", index)
        by_slot = self._cells_by_slot(index)
        rail_cells = _ordered(by_slot, ROW_RAIL_ORDER)
        rail_w = self._group_width(QFontMetrics(meta_font), rail_cells)
        quality_cells = by_slot.get(CHIP_SLOT_QUALITY) or []
        quality_cell = quality_cells[0] if quality_cells else None

        # The ONE call that decides where anything goes. It is handed no
        # selection/hover flag — see channel_row_layout's docstring: row
        # geometry taking no state argument is what makes "nothing moves when a
        # row is selected" unrepresentable rather than merely remembered.
        lead_text, lead_role = _lead.lead_slot(
            self._row_discriminator, index.data(SPORT_ROLE) or "",
            index.data(LANGUAGE_ROLE) or "")
        box = _layout.row_layout(
            option.rect, has_art=has_art, art_square=(kind == "live"),
            rail_w=rail_w, lead_w=_lead.slot_width(lead_text, lead_role),
        )

        # Scope hit-region recording to this row, and clear any previous pass so
        # rects never accumulate across repaints.
        self._painting_row = index.row()
        self._hit_regions[index.row()] = []

        painter.save()
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setClipRect(option.rect)

        self._paint_chrome(painter, box, opt)
        self._paint_kind_mark(painter, box.kind, kind, default_color)
        _lead.paint_lead_slot(painter, box.lead, lead_text, lead_role,
                              _to_qcolor(default_color).name(), meta_font,
                              self._draw_text)
        if has_art:
            self._paint_thumbnail(painter, box.art, index, kind)

        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        rail_rects = _layout.right_aligned_rects(
            box.rail,
            [self._cell_width(QFontMetrics(meta_font), c) for c in rail_cells],
            _CELL_GAP,
        )
        for cell, rect in zip(rail_cells, rail_rects):
            if selected and cell.is_chip and not cell.outline:
                cell = _edged_on_selection(cell)
            self._paint_cell(painter, rect, cell, meta_font)

        self._paint_text_stack(painter, box.text, index, opt, by_slot, meta_font,
                               quality_cell=quality_cell)

        if selected or (opt.state & QStyle.StateFlag.State_MouseOver):
            self._paint_action(painter, box.action)
        painter.restore()
        self._painting_row = None

    # ── Row chrome (this delegate paints it; QStyle does not) ────────────────

    def _paint_chrome(self, painter, box: "_layout.RowLayout", opt) -> None:
        """The row's fill and its current-row marker bar.

        Deliberately NOT ``style.drawControl(CE_ItemViewItem)``: the V3 fill is
        INSET on all four sides and rounded, so it reads as an object resting on
        the list surface, and Qt's own item background is a full-bleed rect that
        cannot be inset. Painting it here is also what lets selection be a TINT
        instead of a saturated accent — which is why a selected row can keep its
        normal text ramp and its facet hues (see ``_resolve_default_color``).
        """
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        hovered = bool(opt.state & QStyle.StateFlag.State_MouseOver)
        if not (selected or hovered):
            return
        fill = _theme.COLOR_ROW_SELECTED_FILL if selected else _theme.COLOR_ROW_HOVER_FILL
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_to_qcolor(fill))
        painter.drawRoundedRect(box.fill, _layout.FILL_RADIUS, _layout.FILL_RADIUS)
        if selected:
            # Colour-never-alone: the bar's SHAPE carries "this one", so the
            # tint underneath does not have to be the only cue.
            painter.setBrush(_to_qcolor(_theme.COLOR_ROW_MARKER))
            painter.drawRoundedRect(box.marker, _layout.MARKER_W / 2, _layout.MARKER_W / 2)

    def _paint_action(self, painter, rect: QRect) -> None:
        """The ``⋯`` affordance — always RESERVED (see ``row_layout``), painted
        only on hover/current so a resting list is not a wall of buttons.

        Drawn as a vector glyph, never the literal character: ``⋯`` (U+22EF)
        and ``…`` (U+2026) are trivially confusable in source, they sit at
        different heights, and neither can take a theme colour.
        """
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_to_qcolor(_theme.COLOR_ROW_ACTION_FILL))
        painter.drawRoundedRect(rect, _OUTLINE_RADIUS + 2, _OUTLINE_RADIUS + 2)
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key("more"), _theme.COLOR_ROW_ACTION_FG, _layout.KIND_ICON
        )
        if not pixmap.isNull():
            painter.drawPixmap(
                QRect(rect.center().x() - _layout.KIND_ICON // 2 + 1,
                      rect.center().y() - _layout.KIND_ICON // 2 + 1,
                      _layout.KIND_ICON, _layout.KIND_ICON),
                pixmap,
            )

    def mode_toggle_rects(self, option_rect: QRect, index, base_font):
        """``(whole, part)`` hit rects for a header's Whole|Part, else two nulls."""
        return _band.toggle_rects_for(option_rect, index, base_font)

    def action_rect(self, option_rect: QRect, index) -> QRect:
        """The action affordance's rect for a row — what the VIEW hit-tests.

        Recomputed from the same ``row_layout`` call ``paint`` makes rather than
        stashed during paint: the gutter is reserved on every row whether or not
        it was painted, so a click must land on rows that have never been
        hovered.
        """
        if index.data(ROW_KIND_ROLE) in LABEL_ROW_KINDS:
            return QRect()
        return _layout.row_layout(
            option_rect,
            has_art=self._shows_thumbnail("channel", index),
            art_square=(self._kind_of(index) == "live"),
            rail_w=0,
        ).action

    # ── Kind mark + artwork ─────────────────────────────────────────────────

    def _paint_kind_mark(self, painter, rect: QRect, kind: str, default_color) -> None:
        """The structural media-kind mark.

        Live takes the ACCENT; movie and series take the row's neutral
        foreground. That is not decoration: live is the only kind whose content
        is happening right now, and it is the one a reader scanning a mixed list
        needs to pick out. Colour-never-alone holds because the three glyphs are
        different shapes before they are different colours.
        """
        role = _KIND_ICON_ROLES.get(kind)
        if role is None:
            return
        color = _theme.COLOR_ACCENT if kind == "live" else _to_qcolor(default_color).name()
        pixmap = _icon_utils.vector_pixmap(
            _icons.vector_key(role), color, _layout.KIND_ICON
        )
        if not pixmap.isNull():
            painter.drawPixmap(rect, pixmap)

    def _paint_thumbnail(self, painter, rect: QRect, index, kind: str = "") -> None:
        """Paint the real poster (cache-hit only — never downloads from
        ``paint()``) cropped to fill *rect*, or a placeholder on a miss."""
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
        self._paint_thumbnail_placeholder(painter, rect, index, kind)

    def _paint_thumbnail_placeholder(self, painter, rect: QRect, index,
                                     kind: str = "") -> None:
        """Zero-network fallback: a SUNK tile carrying the row's kind mark, or
        the title's first letter when the kind is unknown.

        The kind glyph rather than a letter because the tile is square for live
        channels and a live channel's "title" is a call sign — ``C`` for
        CHRISTMAS 1 says nothing the row does not already say, while the mark
        says what the tile is standing in for.

        ``surface.sunk`` is the role named for this: absence reads as absence.
        A step ABOVE the list surface made a MISSING image the loudest object in
        its row — a hole in the data shouting over the title that is there.
        """
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_to_qcolor(_theme.COLOR_ROW_THUMB_PLACEHOLDER))
        painter.drawRoundedRect(rect, _THUMB_RADIUS, _THUMB_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # The kind glyph stands in ONLY for a live channel. A live channel's
        # "title" is a call sign, so ``C`` for CHRISTMAS 1 says nothing the row
        # does not already say — while a movie's initial does, and repeating the
        # gutter mark inside the well next to it would just say kind twice.
        role = _KIND_ICON_ROLES.get(kind) if kind == "live" else None
        if role is not None:
            pixmap = _icon_utils.vector_pixmap(
                _icons.vector_key(role), _theme.COLOR_TEXT, _layout.KIND_ICON
            )
            if not pixmap.isNull():
                painter.drawPixmap(
                    QRect(rect.center().x() - _layout.KIND_ICON // 2 + 1,
                          rect.center().y() - _layout.KIND_ICON // 2 + 1,
                          _layout.KIND_ICON, _layout.KIND_ICON),
                    pixmap,
                )
                return
        title = index.data(TITLE_ROLE) or ""
        letter = title.strip()[:1].upper() if title.strip() else "?"
        painter.setPen(_to_qcolor(_theme.COLOR_TEXT))
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

    def _title_color(self, opt: QStyleOptionViewItem, index) -> object:
        """Colour for the TITLE — the loudest thing in its row.

        ``COLOR_ROW_TITLE`` is ``on-surface.strong`` (Radix step 12) against the
        meta line's step 11. A row carrying an explicit ``ForegroundRole``
        (watched-dim, degraded-grey) keeps that dimming — brightening the title
        of a row the model just dimmed would undo the signal.
        """
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            return fg.color()
        return _theme.COLOR_ROW_TITLE

    def _draw_text(self, painter, rect: QRect, text: str, color, font) -> None:
        painter.setFont(font)
        painter.setPen(_to_qcolor(color))
        painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)

    def _cell_width(self, fm: QFontMetrics, cell: _Cell) -> int:
        w = fm.horizontalAdvance(cell.text)
        return w + 2 * _CHIP_H_PAD if cell.is_chip else w

    def hit_cells(self, row: int) -> list[tuple[QRect, _Cell]]:
        """Painted (rect, cell) pairs for *row* that carry hover/click meaning.

        Delegate-painted chips are not widgets, so they have no ``setToolTip``
        and no ``mousePressEvent`` of their own — the view has to hit-test the
        rectangles this delegate actually drew (#24). Recorded during ``paint``
        rather than recomputed, so a hit region can never disagree with what the
        user sees.

        Only rows currently on screen have entries; scrolling repaints and
        refreshes them. Returns ``[]`` for a row that has not been painted.
        """
        return list(self._hit_regions.get(row, ()))

    @staticmethod
    def _chip_radius(rect: QRect) -> float:
        """Corner radius for a chip of *rect*'s height.

        ``_CHIP_RADIUS`` is the target (matching the sidebar pill), but a chip
        shorter than twice that would render as an over-rounded lozenge, so it
        is capped at half the height — which is exactly a pill.
        """
        return min(_CHIP_RADIUS, rect.height() / 2)

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

    # ── The text stack ───────────────────────────────────────────────────────

    def _paint_text_stack(self, painter, box: QRect, index, opt, by_slot, meta_font,
                          *, quality_cell=None) -> None:
        """Title (with the quality chip against it), then the meta line, then
        (comfy+ only) the plot.

        Each line is measured with the metrics of the font it is actually
        painted in — eliding a DemiBold title against regular-weight metrics
        overflows its box, which is how a long title used to push a chip out of
        the row.
        """
        title_font = self._title_font(opt.font)
        title_h = QFontMetrics(title_font).height()
        meta_h = QFontMetrics(meta_font).height()
        lines = self._line_count(index)
        meta_cells = _ordered(by_slot, ROW_META_ORDER)
        plot = index.data(PLOT_ROLE) or ""

        # The stack is sized from the DENSITY, never from whether this
        # particular row happens to have facts to put on its meta line.
        #
        # It briefly was: a row with an empty meta line collapsed to one line
        # and re-centred its title. That looked reasonable on a single row and
        # wrecked the list — titles no longer shared a baseline, so scrolling
        # past a mix of rows made every few titles jump up and down while the
        # row pitch stayed constant. It was also the row's own first rule
        # broken from the inside: geometry must not depend on the row's
        # content any more than on its selection state. An empty meta line
        # simply paints nothing, and the title stays where its neighbours'
        # titles are.
        stack_h = title_h + (lines - 1) * (meta_h + _LINE_GAP)
        top = box.top() + max(0, (box.height() - stack_h) // 2)

        self._paint_title(
            painter, QRect(box.left(), top, box.width(), title_h), index, opt,
            title_font, quality_cell=quality_cell, meta_font=meta_font,
        )
        if lines == 1:
            return

        y = top + title_h + _LINE_GAP
        if meta_cells:
            self._paint_meta_line(
                painter, QRect(box.left(), y, box.width(), meta_h), meta_cells, meta_font
            )
        if lines >= 3:
            y += meta_h + _LINE_GAP
            self._paint_plot_line(
                painter, QRect(box.left(), y, box.width(), meta_h), plot, meta_font
            )

    def _paint_title(self, painter, line: QRect, index, opt, title_font, *,
                     quality_cell=None, meta_font=None) -> None:
        """The title, elided against a box whose right edge is fixed by
        ``row_layout``, with the quality chip painted IMMEDIATELY after the
        title text.

        Quality hugs the title TEXT, not the title BOX: the box runs all the way
        to the rail, so offsetting by its width parks the chip against the rail
        instead, where it reads as one more right-hand fact rather than as a
        qualifier on this copy.

        Why it is here and not in the rail at all: quality exists on 6.6% of
        rows, and a right-aligned rail containing an optional member puts every
        member LEFT of it in a different column depending on that member's
        presence — the language badge visibly jumped down a scrolling list.
        Against the title, quality's absence costs nothing but a few pixels of
        title box, and the language column never moves.
        """
        leading = self._paint_leading_glyphs(painter, line, index, title_font)
        title = index.data(TITLE_ROLE) or ""
        title_fm = QFontMetrics(title_font)
        chip_font = meta_font if meta_font is not None else opt.font
        quality_w = (self._cell_width(QFontMetrics(chip_font), quality_cell)
                     if quality_cell else 0)

        box_w = max(0, line.right() - leading + 1
                    - (quality_w + _CELL_GAP if quality_cell else 0))
        elided = title_fm.elidedText(title, Qt.TextElideMode.ElideRight, box_w)
        self._draw_text(painter, QRect(leading, line.top(), box_w, line.height()),
                        elided, self._title_color(opt, index), title_font)

        if quality_cell:
            title_w = min(title_fm.horizontalAdvance(elided), box_w)
            chip_h = min(_layout.CHIP_H, line.height())
            self._paint_cell(
                painter,
                QRect(leading + title_w + _CELL_GAP,
                      line.top() + max(0, (line.height() - chip_h) // 2),
                      quality_w, chip_h),
                quality_cell, chip_font,
            )

    def _paint_leading_glyphs(self, painter, line: QRect, index, font) -> int:
        """The favourite star, the playback glyph (·/▶/✓) and the unviewed
        watch-for marker (🚨), left to right. Returns the x the title starts at.

        The MEDIA icon is deliberately absent: kind moved out to the structural
        mark in the row's own gutter, so painting it again here would state the
        same fact twice on one line.
        """
        fm = QFontMetrics(font)
        x = line.left()
        glyph = index.data(FAV_GLYPH_ROLE) or ""
        if glyph:
            w = fm.horizontalAdvance(glyph)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), glyph,
                            _theme.COLOR_ROW_META, font)
            x += w + _CELL_GAP

        playback_glyph = index.data(PLAYBACK_GLYPH_ROLE) or ""
        if playback_glyph:
            playback_color = index.data(PLAYBACK_GLYPH_COLOR_ROLE)
            w = fm.horizontalAdvance(playback_glyph)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), playback_glyph,
                            playback_color if playback_color else _theme.COLOR_ROW_META, font)
            x += w + _CELL_GAP

        match_marker = index.data(MATCH_MARKER_ROLE) or ""
        if match_marker:
            w = fm.horizontalAdvance(match_marker)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), match_marker,
                            _theme.COLOR_ROW_META, font)
            x += w
        return x

    def _paint_meta_line(self, painter, line: QRect, cells, font) -> None:
        """``2000 · Thriller / Drama · Anime`` — one run of tier-2 tinted
        segments joined by :data:`_META_SEPARATOR`.

        Segments are painted left to right and STOP at the line's right edge
        rather than eliding the run: a half-drawn ``Thrill…`` says less than an
        absent segment, and the facts are ordered by how much they matter, so
        what is dropped is what mattered least. Each segment keeps its own hit
        rect, which is what preserves click-to-filter on genre/region/collection
        now that they are text rather than chips.
        """
        fm = QFontMetrics(font)
        sep_w = fm.horizontalAdvance(_META_SEPARATOR)
        x = line.left()
        first = True
        for cell in cells:
            width = fm.horizontalAdvance(cell.text)
            advance = width if first else sep_w + 2 * _META_GAP + width
            if x + advance > line.right() + 1:
                break
            if not first:
                self._draw_text(
                    painter, QRect(x + _META_GAP, line.top(), sep_w, line.height()),
                    _META_SEPARATOR, _theme.COLOR_ROW_META, font,
                )
                x += sep_w + 2 * _META_GAP
            self._paint_cell(painter, QRect(x, line.top(), width, line.height()), cell, font)
            x += width
            first = False

    def _paint_plot_line(self, painter, line: QRect, plot: str, font) -> None:
        """comfy_plus's last line — the plot, elided to fit, in the muted
        token."""
        if not plot:
            return
        elided = QFontMetrics(font).elidedText(
            plot, Qt.TextElideMode.ElideRight, line.width()
        )
        self._draw_text(painter, line, elided, _theme.COLOR_MUTED, font)
