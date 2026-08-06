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
     left-aligned, then ``[year][region/platform chip][rating chip]`` right-aligned
     flush to the row's right edge.
   - ``"comfy"`` (default) — two lines: line 1 is
     ``[media icon][fav][glyph][🚨][title][quality chip]`` (the quality chip hugs
     the title — no stretch between them) left, then right-aligned flush to the
     row's right edge, in this order: ``[year][region/platform chip][subtitle
     marker chip][secondary language chip][primary language chip]`` — the
     channel's OWN (honest) language always sits furthest right. Line 2 is the
     badge row: state on the left (a rating glyph, and the ``×N`` variant
     badge), taxonomy on the right — a genre chip, then the clean collection
     chip (``detected_collection``, render-time-transformed via
     :func:`~metatv.core.channel_name_utils.collection_display`) flush right.
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

   **Three emphasis tiers (#298).** The row used to carry SEVEN boxed
   treatments — blue language, green region, teal genre, grey collection,
   purple platform, outlined quality, muted year — plus a poster tile, while
   the TITLE, the thing anyone is actually scanning for, had no treatment at
   all. Nothing receded, so nothing led. Now:

   - **Tier 1, FILL** — language only (own language, the category's
     disagreeing language, and any sub/dub marker: one hue, one treatment),
     plus genuine row STATE (selection). Nothing else in the row gets a fill.
   - **Tier 2, TINTED TEXT, no box** — region, genre, platform, collection.
     The hue stays, because the hue is what was carrying the facet encoding;
     the box was not. Collection is the one neutral member, deliberately: the
     palette publishes one hue per facet and no two may share one, so a fifth
     hue would have to be borrowed from a facet that already means something
     else. Platform in particular used to be the LOUDEST thing in the row (a
     solid purple fill) for a fact almost nobody scans by.
   - **Tier 3, OUTLINE** — quality and the year. Quality is the row's one
     CLAIM rather than a category, so it earns a border, and it paints
     IMMEDIATELY AFTER THE TITLE (it qualifies this copy) rather than in the
     right-hand rail.

   The title itself paints in ``COLOR_ROW_TITLE`` (``on-surface.strong``) at
   DemiBold, so it is unambiguously the loudest thing in its own row.

   Hues come from the palette's ``facet.*`` block via the ``COLOR_ROW_*``
   tokens — never invented locally, and never a literal. No tier ever uses an
   alpha wash as a resting fill; the overlay ramp is for hover.

   Chip ORDER is declared once, in :data:`ROW_CHIP_ORDER`, and every density
   asks that constant for the subset it shows — the two densities previously
   built their own tuples and had already drifted apart. The title is elided
   (``Qt.TextElideMode.ElideRight``) against a *fixed* box computed from the
   other cells' measured widths, so a long title can never push a chip out of
   the row.

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

import re
from typing import TYPE_CHECKING, NamedTuple, Optional, Union

from PyQt6.QtCore import QRect, QSize, Qt
from PyQt6.QtGui import (
    QAbstractTextDocumentLayout,
    QBrush,
    QColor,
    QFont,
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

from metatv.core.channel_name_utils import (
    PLATFORM_CODES,
    collection_display,
    platform_display,
    quality_display,
)
from metatv.gui import icons as _icons
from metatv.gui import theme as _theme
from metatv.gui.badge_utils import _quality_outline_colors
from metatv.gui.channel_list_model import (
    CATEGORY_ROLE,
    CHANNEL_HTML_ROLE,
    COLLECTION_ROLE,
    FAV_GLYPH_ROLE,
    GENRE_ROLE,
    GENRES_ROLE,
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

# Platform-names style (Settings → Interface → Channel List → "Platform names"):
# "auto" (default) resolves per-density in _effective_platform_style — full
# brand name in comfy/comfy_plus, short code in compact; "full"/"short"
# override the density for every row regardless.
PLATFORM_STYLE_AUTO = "auto"
PLATFORM_STYLE_FULL = "full"
PLATFORM_STYLE_SHORT = "short"
_VALID_PLATFORM_STYLES = (PLATFORM_STYLE_AUTO, PLATFORM_STYLE_FULL, PLATFORM_STYLE_SHORT)

# Structural spacing (not a colour/font-size — px literals are fine inline
# per CLAUDE.md's styles rule).
_ROW_V_PAD = 4       # vertical padding top+bottom of a single-line/compact row
_ROW_H_PAD = 10       # breathing room at BOTH row edges; the right side also keeps
                      # right-aligned cells out from under the vertical scrollbar.
                      # 10, not 6: a scrollbar is ~12px, so 6 left the chips
                      # technically clear but visually crowded against it.
_LINE_GAP = 2         # gap between comfy's two stacked text lines
_CELL_GAP = 6         # horizontal gap between adjacent cells
_CHIP_H_PAD = 7       # chip internal horizontal padding — matches theme.LANG_CHIP
                      # ("padding: 1px 7px"), the sidebar pill these should look like
_THUMB_RADIUS = 4     # poster-placeholder tile corner radius. Its own constant:
                      # it borrowed _CHIP_RADIUS, so rounding the chips into pills
                      # would otherwise have rounded a 90px-tall poster tile too.
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
                      # Was 3, which read as a squared-off box next to the sidebar's
                      # rounded pills. Clamped to half the chip height at paint time
                      # (_chip_radius) so a short chip becomes a true pill rather
                      # than an over-rounded lozenge.

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


# ---------------------------------------------------------------------------
# Colour conversion — the ONE chokepoint every colour this delegate paints
# must go through. Never construct a bare QColor(token) at a paint call site.
# ---------------------------------------------------------------------------

# CSS rgba(r,g,b,a) / rgb(r,g,b) — the format theme_palettes.py's OVERLAY_*
# tokens use. Whitespace-tolerant; the alpha group is optional (rgb() form).
_RGBA_RE = re.compile(
    r'^\s*rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)\s*$'
)


def _to_qcolor(token: Union[str, QColor, None]) -> QColor:
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


class _Cell(NamedTuple):
    """One paintable unit, in one of the row's THREE emphasis tiers (#298).

    - **Tier 1, fill** — ``is_chip=True``, ``bg`` set: a solid fill with
      ``fg``-coloured text on it. Language only, plus genuine row state.
    - **Tier 2, tinted text** — ``is_chip=False``: a bare text run in the
      facet's hue, no box at all. Region, genre, platform, collection.
    - **Tier 3, outline** — ``is_chip=True, outline=True``: a border stroke
      (``border``, defaulting to ``fg``) around an UNFILLED interior, text in
      ``fg``. Quality and year.

    ``border`` exists because tier 3 has two members with different needs:
    quality's stroke is its tier hue (same as its text), while the year's text
    is neutral metadata but its box must be quieter still than that text.
    """

    text: str
    is_chip: bool
    fg: str        # QColor-constructible token/hex (theme.* or a QColor.name())
    bg: Optional[str] = None   # fill token — tier 1 only; None on an outline chip
                               # (an alpha wash as a RESTING fill is a hover
                               # effect in the wrong place — owner directive)
    outline: bool = False      # True => border-only chip (tier 3), never filled
    border: Optional[str] = None  # outline stroke token; falls back to ``fg``
    # Facet identity + hover copy (#24). A delegate-painted chip has no widget,
    # so it cannot carry setToolTip() — the view hit-tests the painted rect and
    # renders `tip` itself. `facet`/`value` are what a click filters on; both
    # empty means the cell is decorative and neither hovers nor clicks.
    facet: str = ""
    value: str = ""
    tip: str = ""


def _on_selection(cell: _Cell, color: str) -> _Cell:
    """Re-render *cell* for a SELECTED row, flattened to *color*.

    A selected row IS the tier-1 fill (``COLOR_ACCENT``), so every cell on it is
    now sitting on a saturated accent rather than on the list surface — and a
    facet hue chosen for legibility on the list surface has no reason to clear
    4.5:1 on the accent. Before this, a selected row painted green ``KR`` and a
    blue-filled ``EN`` box directly onto the blue highlight, which is where the
    old row's worst contrast in the app actually was.

    Fills and hues are dropped; the outline tier keeps its box (the shape is
    still carrying "this is a claim, not a category") with the stroke in the
    on-accent colour. Hue-as-encoding is lost for exactly one row — the one
    whose state is already unambiguous from the fill under it.
    """
    if cell.outline:
        return cell._replace(fg=color, bg=None, border=color)
    return cell._replace(is_chip=False, fg=color, bg=None, border=None)


# ---------------------------------------------------------------------------
# Chip order — ONE definition, deliberately not emergent from the paint code.
# ---------------------------------------------------------------------------

CHIP_SLOT_QUALITY = "quality"
CHIP_SLOT_VARIANTS = "variants"
CHIP_SLOT_RATING = "rating"
CHIP_SLOT_GENRE = "genre"
CHIP_SLOT_COLLECTION = "collection"
CHIP_SLOT_YEAR = "year"
CHIP_SLOT_REGION = "region"          # region OR platform — one field, two hues
CHIP_SLOT_SUBTITLE = "subtitle"
CHIP_SLOT_LANGUAGE_2 = "language_secondary"
CHIP_SLOT_LANGUAGE = "language"

#: Left-to-right precedence for every chip the row can paint, in ONE place.
#:
#: Each line asks for the subset it owns (see ``_ordered``) and gets them back
#: in this order, so the order is a single readable declaration rather than
#: something you have to reconstruct by reading three paint methods and
#: diffing their tuple literals — which is what it was, and why the two
#: densities had silently drifted apart. A future Settings → Interface control
#: reorders this tuple and every density follows.
#:
#: Position notes: quality leads because it is painted in the LEFT group,
#: hugging the title — it qualifies this copy of the title, so it belongs next
#: to it, not in the right rail. State (variants, rating) precedes taxonomy on
#: its line. The channel's own honest language sits furthest right of the
#: right-aligned group, which is the anchor the eye returns to (owner spec).
ROW_CHIP_ORDER: tuple[str, ...] = (
    CHIP_SLOT_QUALITY,
    CHIP_SLOT_VARIANTS,
    CHIP_SLOT_RATING,
    CHIP_SLOT_GENRE,
    CHIP_SLOT_COLLECTION,
    CHIP_SLOT_YEAR,
    CHIP_SLOT_REGION,
    CHIP_SLOT_SUBTITLE,
    CHIP_SLOT_LANGUAGE_2,
    CHIP_SLOT_LANGUAGE,
)

#: How many genres a row will show before it stops (#298 — "show multiple
#: genres when present"). ``detected_genres`` regularly holds 4+ segments;
#: past three they stop being scannable and start eating the title's box.
_MAX_GENRES = 3


def _ordered(by_slot: dict[str, list[_Cell]], slots: tuple[str, ...]) -> list[_Cell]:
    """Cells for *slots*, sorted by :data:`ROW_CHIP_ORDER` and flattened.

    A slot may hold several cells (genre, which paints one per genre); they keep
    their own relative order inside the slot.
    """
    out: list[_Cell] = []
    for slot in ROW_CHIP_ORDER:
        if slot in slots:
            out.extend(by_slot.get(slot, ()))
    return out


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


def _region_label(code: str) -> str:
    """Human-readable name for a region/language code, for hover copy only.

    Reads the curated ``REGION_FULL_NAMES`` table (CLAUDE.md's lookup-table
    rule — never a parallel dict here) and falls back to the raw code, which is
    what an unmapped or provider-invented token should show.
    """
    from metatv.core.channel_name_utils import REGION_FULL_NAMES, normalize_region_code

    if not code:
        return ""
    full = REGION_FULL_NAMES.get(normalize_region_code(code))
    return f"{full} ({code})" if full else code


# ---------------------------------------------------------------------------
# Cell builders — map a raw role value to a paintable _Cell (or None to omit).
# ---------------------------------------------------------------------------

def _year_cell(year) -> Optional[_Cell]:
    """Year — TIER 3, outline (owner call: "put an outline on the year").

    Neutral text (``COLOR_ROW_META``) inside a quieter neutral box
    (``COLOR_BORDER``): the year is the one metadata field that is a plain
    number, so without a box it reads as part of whatever text abuts it.
    """
    # Coerce: the year reaches us as a str from ChannelListDTO but as an int
    # from some model stubs/roles, and a non-str text reaches QFontMetrics
    # .horizontalAdvance() and raises.
    if not year:
        return None
    # No facet: "year" is not a tag facet (tag_decomposer emits audio /
    # collection / genre / language / quality / region), so there is nothing
    # to filter on. Tooltip only — a chip that looks clickable and does
    # nothing is worse than one that plainly just labels itself.
    return _Cell(str(year), True, _theme.COLOR_ROW_META, outline=True,
                 border=_theme.COLOR_BORDER, tip=f"Released {year}")


def _quality_cell(token: str) -> Optional[_Cell]:
    """Quality chip — TIER 3, OUTLINE ONLY: border + text in the tier's colour
    from ``_quality_outline_colors()``, over an interior that is not filled at
    all (#298 dropped the ``OVERLAY_08`` tint the chip used to carry — an
    alpha wash is a hover effect, and using one as a resting fill is what put
    an un-authored, un-themeable grey into the row).

    Quality is the row's one CLAIM rather than a category — "this copy is 4K" —
    which is why it gets a border when no other facet does, and why it paints
    immediately after the title instead of in the right-hand rail: it qualifies
    the title, and a claim separated from what it qualifies reads as a
    different fact.

    Deliberately reads ``_quality_outline_colors()``, NOT ``_quality_colors()``
    (still used unchanged by ``badge_utils.make_quality_chip``'s solid-fill
    widget elsewhere): ``COLOR_QUALITY_*`` is a SOLID-FILL palette, held
    theme-invariant on purpose (theme_palettes.py's module docstring — "the
    owner explicitly likes this hue system"), so it can't be palette-tuned for
    contrast the way the LANG_CHIP-idiom facets' ``COLOR_ACCENT_*``
    foregrounds are — as TEXT/BORDER against the app's OWN background instead,
    those same values measured 1.57-4.09:1, well under a 4.5:1 floor, on
    EVERY palette (not just Daylight). ``COLOR_QUALITY_OUTLINE_*`` is a
    separate, dedicated per-palette family — same hue as the corresponding
    ``COLOR_QUALITY_*`` token, lightness tuned per palette (brighter in the
    two dark palettes, darker in Daylight) so text/border clears 4.5:1
    against ``COLOR_BG_SECTION`` everywhere — see
    ``tests/test_palette_completeness.py``'s
    ``test_quality_outline_chip_contrast_at_least_4_5_every_palette``.

    """
    if not token:
        return None
    upper = token.upper()
    color = _quality_outline_colors().get(upper, _theme.COLOR_FAINT)
    return _Cell(quality_display(upper), True, color, None, outline=True,
                 facet="quality", value=upper,
                 tip=f"Picture quality: {quality_display(upper)} — click to show "
                     f"only {quality_display(upper)} versions")


def _region_or_platform_cell(code: str, platform_style: str) -> Optional[_Cell]:
    """Region-or-platform — TIER 2, tinted text, for ``LANGUAGE_ROLE``
    (``detected_region`` — the field doubles as BOTH a geographic region code
    and a streaming-platform code, e.g. ``"US"`` vs ``"NF"``/``"A+"``).

    Two distinct hues, no box on either: a recognized :data:`PLATFORM_CODES`
    member paints in ``COLOR_ROW_PLATFORM`` (``platform_display`` resolves the
    brand name per *platform_style*), anything else in ``COLOR_ROW_REGION``.

    Platform used to be the single LOUDEST treatment in the row — a solid
    purple fill — for a fact almost nobody scans by. It now sits in the same
    tier as its neighbours and keeps its hue, which is the part that was
    carrying the meaning.
    """
    if not code:
        return None
    if code in PLATFORM_CODES:
        brand = platform_display(code, platform_style)
        return _Cell(
            brand, False, _theme.COLOR_ROW_PLATFORM,
            facet="region", value=code,
            tip=f"Streaming platform: {brand} — click to show only {brand}",
        )
    return _Cell(code, False, _theme.COLOR_ROW_REGION,
                 facet="region", value=code,
                 tip=f"Region: {_region_label(code)} — click to show only this region")


def _language_cell(text: str, *, filterable: bool = True) -> Optional[_Cell]:
    """Language family — TIER 1, the row's ONLY facet fill: the channel's own/
    secondary language and any sub/dub marker (``PRIMARY_LANGUAGE_ROLE``,
    ``SECONDARY_LANGUAGE_ROLE``, ``SUBTITLE_MARKER_ROLE``) all share one hue
    and one treatment.

    Language keeps the fill on the owner's call — it is the highest-value facet
    after the title itself, and a tier system with nothing in its top tier
    would just be a flatter version of the same problem. ``COLOR_ROW_LANGUAGE``
    on ``COLOR_ROW_LANGUAGE_FILL`` is a same-hue pair (Radix step 11 text on
    step 4 fill), so the chip clears 4.5:1 without a neutral in sight.
    """
    if not text:
        return None
    if not filterable:
        # Sub/dub markers ("AR-SUB") are NOT language tags — there is no facet
        # that can filter them (the audio facet is empty in practice), so the
        # chip explains itself and stops there. Giving it facet="language"
        # rendered a pointing-hand cursor over a click that silently did
        # nothing, which is worse than no affordance.
        return _Cell(text, True, _theme.COLOR_ROW_LANGUAGE,
                     _theme.COLOR_ROW_LANGUAGE_FILL,
                     tip=f"Subtitles/dub: {text}")
    return _Cell(text, True, _theme.COLOR_ROW_LANGUAGE,
                 _theme.COLOR_ROW_LANGUAGE_FILL,
                 facet="language", value=text,
                 tip=f"Language: {_region_label(text)} — click to show only this language")


def _genre_cell(genre: str) -> Optional[_Cell]:
    """One genre — TIER 2, tinted text in ``COLOR_ROW_GENRE``."""
    if not genre:
        return None
    return _Cell(genre, False, _theme.COLOR_ROW_GENRE,
                 facet="genre", value=genre,
                 tip=f"Genre: {genre} — click to show only {genre}")


def _genre_cells(genres, fallback: str = "") -> list[_Cell]:
    """Up to :data:`_MAX_GENRES` genre cells (#298 — "show multiple genres
    when present").

    Reads the ingestion-computed ``detected_genres`` list; *fallback* is the
    single ``detected_genre`` for rows ingested before that column existed and
    not yet re-swept, so a pre-migration library still shows its one genre
    rather than none. Neither is ever re-derived at render — both are stored
    fields (``update_detected_prefixes``).
    """
    values = [g for g in (genres or ()) if g]
    if not values and fallback:
        values = [fallback]
    seen: set[str] = set()
    cells: list[_Cell] = []
    for genre in values:
        if genre in seen:
            continue
        seen.add(genre)
        cell = _genre_cell(genre)
        if cell is not None:
            cells.append(cell)
        if len(cells) >= _MAX_GENRES:
            break
    return cells


def _category_cell(category: str, platform_code: str = "",
                   filter_category: str = "") -> Optional[_Cell]:
    """Collection — TIER 2, but NEUTRAL text (``COLOR_ROW_COLLECTION``), not a
    hue.

    Every other tier-2 member carries a facet hue. Collection deliberately does
    not: the palette publishes one hue per facet and no two may share one, so a
    fifth hue here would either be invented or borrowed from a facet that
    already means something else — and a borrowed hue is a false statement
    about the data. Dropping the box is the change; the grey was already right.

    The TEXT is a render-layer transform via
    :func:`~metatv.core.channel_name_utils.collection_display` (trailing
    media-type token stripped + a leading platform-duplicate token stripped
    when *platform_code* is this row's own recognized platform code) — never
    touches the stored ``detected_collection`` (Discover reads that verbatim
    and must keep SERIES/MOVIES, #257 owner directive)."""
    display = collection_display(category, platform_code or None)
    if not display:
        return None
    # DISPLAY comes from detected_collection (cleaned); the FILTER value is the
    # curated ChannelDB.category, a different column — that is what the
    # collection filter matches, and filtering on the displayed string returns
    # nothing. Falls back to the display value only when no curated category
    # exists, which the applier treats as "nothing to filter on".
    return _Cell(display, False, _theme.COLOR_ROW_COLLECTION,
                 facet="collection", value=(filter_category or ""),
                 tip=f"Collection: {display} — click to show only this collection")


def _rating_glyph_cell(rating: int) -> Optional[_Cell]:
    """Rating — a bare 👍/👎 glyph, in EVERY density.

    Compact used to paint this as a green/red filled chip. The glyph is an
    emoji: it carries its own colour, so the fill behind it was adding a
    coloured box that said nothing the glyph did not already say — and under
    the tier rules a fill has to mean state the row cannot otherwise show.
    ``fg`` is still set for the fallback case where a font renders the glyph
    monochrome.
    """
    if not rating:
        return None
    glyph = _icons.like_icon if rating > 0 else _icons.dislike_icon
    return _Cell(glyph, False, _theme.COLOR_ROW_META)


def _variant_badge_cell(count: int) -> Optional[_Cell]:
    """Collapsed-variant "×N" badge (Settings → Interface → "Collapse quality/
    language versions") — plain neutral text.

    Omitted (None) for singleton/uncollapsed rows — ``ChannelListDTO.
    variant_count`` defaults to 1 whenever collapsing is off, so this is a
    no-op everywhere the setting is unused."""
    if not count or count <= 1:
        return None
    return _Cell(f"×{count}", False, _theme.COLOR_ROW_META,
                 tip=f"{count} versions of this title were collapsed into one row "
                     f"(Settings → Interface → Collapse quality/language versions)")


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
        # Inset both edges equally. The right inset is the functional one —
        # right-aligned cells anchor to container.right(), so without it they
        # render flush to the viewport edge and the vertical scrollbar paints
        # over them. The matching left inset keeps the row balanced rather than
        # just shifted left. Applied here, before the clip and before
        # content_rect is derived, so every density and the thumbnail path all
        # inherit it from one place.
        text_rect = text_rect.adjusted(_ROW_H_PAD, 0, -_ROW_H_PAD, 0)

        # Scope hit-region recording to this row, and clear any previous pass so
        # rects never accumulate across repaints.
        self._painting_row = index.row()
        self._hit_regions[index.row()] = []

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
        # A selected row is a solid accent FILL, so every cell on it is now on
        # the accent rather than on the list surface — the tier colours are
        # flattened onto the highlight foreground rather than painted as-is.
        selected = bool(opt.state & QStyle.StateFlag.State_Selected)
        title_color = self._title_color(opt, index)
        if self._density == DENSITY_COMPACT:
            self._paint_compact(painter, content_rect, index, default_color, opt.font,
                                title_color=title_color, selected=selected)
        elif self._density == DENSITY_COMFY_PLUS:
            self._paint_comfy_plus(painter, content_rect, index, default_color, opt.font,
                                   title_color=title_color, selected=selected)
        else:
            self._paint_comfy(painter, content_rect, index, default_color, opt.font,
                              title_color=title_color, selected=selected)
        painter.restore()
        self._painting_row = None

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
        # A SUNK surface, not a light slab. COLOR_FAINT made the placeholder the
        # LOUDEST object in a row with no poster — a missing image shouting over
        # the title that is actually there — and its letter sat on it at 2.10:1,
        # half the floor for UI chrome. COLOR_BG_CARD then fixed the contrast but
        # kept the tile a step ABOVE the list surface, so it still led the row.
        # ``surface.sunk`` is the role named for this: absence reads as absence.
        painter.setBrush(_to_qcolor(_theme.COLOR_ROW_THUMB_PLACEHOLDER))
        painter.drawRoundedRect(rect, _THUMB_RADIUS, _THUMB_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)
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
        """Default colour for non-chip text: highlight when selected, else the
        row's ForegroundRole brush (dimmed for degraded/watched rows) or palette text.
        """
        if opt.state & QStyle.StateFlag.State_Selected:
            return opt.palette.color(QPalette.ColorRole.HighlightedText)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            return fg.color()
        return opt.palette.color(QPalette.ColorRole.Text)

    def _title_color(self, opt: QStyleOptionViewItem, index) -> object:
        """Colour for the TITLE specifically — the loudest thing in its row.

        The title is the one thing the eye is actually scanning for, and it was
        painting in the same body-text token as the metadata around it, so
        nothing in the row led. ``COLOR_ROW_TITLE`` is ``on-surface.strong``
        (Radix step 12) against the metadata's step 11.

        The two overrides both still win, because both are saying something
        about the row that outranks emphasis: a SELECTED row's title takes the
        highlight foreground, and a row carrying an explicit ``ForegroundRole``
        (watched-dim, degraded-grey) keeps that dimming — brightening the title
        of a row the model just dimmed would undo the signal.
        """
        if opt.state & QStyle.StateFlag.State_Selected:
            return opt.palette.color(QPalette.ColorRole.HighlightedText)
        fg = index.data(Qt.ItemDataRole.ForegroundRole)
        if isinstance(fg, QBrush):
            return fg.color()
        return _theme.COLOR_ROW_TITLE

    @staticmethod
    def _title_font(font):
        """The row font at DemiBold — weight is the other half of "the title
        leads". Colour alone moves it one Radix step; weight is what makes it
        read as the row's subject at a glance.

        Returns a COPY: the passed font is the shared style option's, and
        mutating it in place would bold every cell painted after the title.
        """
        title_font = QFont(font)
        title_font.setWeight(QFont.Weight.DemiBold)
        return title_font

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
            painter.setPen(_to_qcolor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, cell.text)
        else:
            painter.setPen(_to_qcolor(cell.fg))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, cell.text)

    # ── Shared row-building seam ─────────────────────────────────────────────

    def _cells_by_slot(
        self, index, *, selected_color: Optional[object] = None
    ) -> dict[str, list[_Cell]]:
        """Build EVERY chip this row can paint, keyed by its slot id.

        The one place a role is turned into a ``_Cell``. Each density then asks
        :func:`_ordered` for the subset it shows, which is what keeps compact
        and comfy from drifting apart — they used to build their own tuples,
        and had already ended up with the same chips in different orders.

        Args:
            index: the row's model index.
            selected_color: when set, the row is SELECTED and every cell is
                flattened onto it — see :func:`_on_selection`.
        """
        region_code = index.data(LANGUAGE_ROLE) or ""
        platform_code = region_code if region_code in PLATFORM_CODES else ""

        def one(cell: Optional[_Cell]) -> list[_Cell]:
            return [cell] if cell is not None else []

        by_slot = {
            CHIP_SLOT_QUALITY: one(_quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")),
            CHIP_SLOT_VARIANTS: one(_variant_badge_cell(index.data(VARIANT_COUNT_ROLE) or 1)),
            CHIP_SLOT_RATING: one(_rating_glyph_cell(index.data(RATING_ROLE) or 0)),
            CHIP_SLOT_GENRE: _genre_cells(
                index.data(GENRES_ROLE), index.data(GENRE_ROLE) or ""
            ),
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
        if selected_color is not None:
            color = (
                selected_color.name() if isinstance(selected_color, QColor)
                else selected_color
            )
            return {slot: [_on_selection(c, color) for c in cells]
                    for slot, cells in by_slot.items()}
        return by_slot

    def _paint_right_group(
        self, painter, line: QRect, by_slot, slots: tuple[str, ...], font
    ) -> int:
        """Paint *slots* right-aligned flush to ``line``'s right edge, in
        :data:`ROW_CHIP_ORDER`. Returns the x the group starts at (minus one
        gap) so the caller can bound the title against it."""
        fm = QFontMetrics(font)
        cells = _ordered(by_slot, slots)
        rects = right_aligned_rects(line, [self._cell_width(fm, c) for c in cells], _CELL_GAP)
        for cell, rect in zip(cells, rects):
            self._paint_cell(painter, rect, cell, font)
        return rects[0].left() - _CELL_GAP if rects else line.left() + line.width()

    def _paint_leading_glyphs(self, painter, line: QRect, index, default_color, font) -> int:
        """Media icon, favourite star, playback glyph (·/▶/✓) and the unviewed
        watch-for marker (🚨), left to right. Returns the x the title starts at.

        Shared by every density — compact and comfy carried byte-identical
        copies of this run.
        """
        fm = QFontMetrics(font)
        x = line.left()
        for glyph in (index.data(MEDIA_ICON_ROLE) or "", index.data(FAV_GLYPH_ROLE) or ""):
            if not glyph:
                continue
            w = fm.horizontalAdvance(glyph)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), glyph,
                            default_color, font)
            x += w + _CELL_GAP

        playback_glyph = index.data(PLAYBACK_GLYPH_ROLE) or ""
        if playback_glyph:
            playback_color = index.data(PLAYBACK_GLYPH_COLOR_ROLE)
            w = fm.horizontalAdvance(playback_glyph)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), playback_glyph,
                            playback_color if playback_color else default_color, font)
            x += w + _CELL_GAP

        match_marker = index.data(MATCH_MARKER_ROLE) or ""
        if match_marker:
            w = fm.horizontalAdvance(match_marker)
            self._draw_text(painter, QRect(x, line.top(), w, line.height()), match_marker,
                            default_color, font)
            x += w
        return x

    def _paint_title_run(self, painter, line: QRect, index, *, x: int, right_limit: int,
                         title_color, by_slot, font) -> None:
        """The title (elided, ``_title_font``/``_title_color``) followed
        IMMEDIATELY by the quality outline chip.

        Quality hugs the title TEXT, not the title BOX: the box runs all the way
        to the right group, so offsetting by its width parked the chip against
        that group instead, where it read as one more right-rail fact rather
        than as a qualifier on this copy (owner UX report, 0.21.0).

        The title is measured with its OWN (heavier, therefore wider) metrics —
        eliding a DemiBold string against regular-weight measurements overflows
        the box and pushes the chip out of the row.
        """
        title = index.data(TITLE_ROLE) or ""
        title_font = self._title_font(font)
        title_fm = QFontMetrics(title_font)
        quality_cells = by_slot.get(CHIP_SLOT_QUALITY) or []
        quality_cell = quality_cells[0] if quality_cells else None
        quality_w = self._cell_width(QFontMetrics(font), quality_cell) if quality_cell else 0

        title_box_w = max(0, right_limit - x - (quality_w + _CELL_GAP if quality_cell else 0))
        title_box = QRect(x, line.top(), title_box_w, line.height())
        elided = title_fm.elidedText(title, Qt.TextElideMode.ElideRight, title_box_w)
        self._draw_text(painter, title_box, elided, title_color, title_font)

        if quality_cell:
            title_w = min(title_fm.horizontalAdvance(elided), title_box_w)
            q_rect = QRect(x + title_w + _CELL_GAP, line.top(), quality_w, line.height())
            self._paint_cell(painter, q_rect, quality_cell, font)

    # ── Compact (one line) ───────────────────────────────────────────────────

    #: Compact's right-hand group. A deliberate SUBSET of the slots comfy shows
    #: — compact exists to fit more rows on screen, so the language family and
    #: the taxonomy pair stay off it; adding them back would squeeze the title
    #: box, which is the one thing this redesign is protecting.
    _COMPACT_RIGHT_SLOTS = (
        CHIP_SLOT_VARIANTS, CHIP_SLOT_RATING, CHIP_SLOT_YEAR, CHIP_SLOT_REGION,
    )

    def _paint_compact(self, painter, rect: QRect, index, default_color, font,
                       *, title_color=None, selected: bool = False) -> None:
        by_slot = self._cells_by_slot(
            index, selected_color=default_color if selected else None
        )
        right_limit = self._paint_right_group(
            painter, rect, by_slot, self._COMPACT_RIGHT_SLOTS, font
        )
        x = self._paint_leading_glyphs(painter, rect, index, default_color, font)
        self._paint_title_run(
            painter, rect, index, x=x, right_limit=right_limit,
            title_color=title_color if title_color is not None else _theme.COLOR_ROW_TITLE,
            by_slot=by_slot, font=font,
        )

    # ── Shared comfy/comfy_plus line painters ───────────────────────────────
    #
    # comfy is 2 lines (title+year, badge row); comfy_plus is the SAME 2 lines
    # plus a middle elided-plot line when the row has plot text (else it's
    # identical to comfy — see _comfy_plus_line_count). Both densities share
    # these per-line painters so the layout logic lives in exactly one place.

    #: Comfy line 1's right-hand group. Order comes from :data:`ROW_CHIP_ORDER`,
    #: not from this tuple — membership is all that is declared here.
    _LINE1_RIGHT_SLOTS = (
        CHIP_SLOT_YEAR, CHIP_SLOT_REGION, CHIP_SLOT_SUBTITLE,
        CHIP_SLOT_LANGUAGE_2, CHIP_SLOT_LANGUAGE,
    )

    def _paint_title_year_line(self, painter, line: QRect, index, default_color, font,
                               *, title_color=None, selected: bool = False) -> None:
        """Line 1: media icon + fav + playback glyph + 🚨 + title (elided,
        strong) + the quality outline chip hugging the title.

        Right-aligned flush to ``line``'s right edge, in ``ROW_CHIP_ORDER``:
        ``[year][region/platform][subtitle marker][secondary language]
        [primary language]`` — the channel's OWN (honest) language
        (``detected_prefix``) always sits furthest right (owner spec); the
        region/platform slot sits leftmost of the group since it answers a
        different question (where/which service, not what language).
        """
        by_slot = self._cells_by_slot(
            index, selected_color=default_color if selected else None
        )
        right_limit = self._paint_right_group(
            painter, line, by_slot, self._LINE1_RIGHT_SLOTS, font
        )
        x = self._paint_leading_glyphs(painter, line, index, default_color, font)
        self._paint_title_run(
            painter, line, index, x=x, right_limit=right_limit,
            title_color=title_color if title_color is not None else _theme.COLOR_ROW_TITLE,
            by_slot=by_slot, font=font,
        )

    #: Comfy line 2 — state left, taxonomy right (#257 Part C). Genre may
    #: expand to several cells (``_MAX_GENRES``); collection stays flush right.
    _BADGE_LEFT_SLOTS = (CHIP_SLOT_VARIANTS, CHIP_SLOT_RATING)
    _BADGE_RIGHT_SLOTS = (CHIP_SLOT_GENRE, CHIP_SLOT_COLLECTION)

    def _paint_badge_line(self, painter, line: QRect, index, font,
                          *, selected_color=None) -> None:
        """Badge row — grammar is STATE on the left, TAXONOMY on the right
        (#257 Part C): the ``×N`` variant badge + a rating glyph left, then the
        genres and the clean collection (``detected_collection``,
        render-time-transformed via ``_category_cell``/``collection_display``)
        right-aligned. Used as comfy's line 2 and comfy_plus's final line.
        Region/subtitle/language and the quality chip live on line 1 (owner
        spec) — this line never carries them."""
        fm = QFontMetrics(font)
        by_slot = self._cells_by_slot(index, selected_color=selected_color)

        self._paint_right_group(painter, line, by_slot, self._BADGE_RIGHT_SLOTS, font)

        lx = line.left()
        for cell in _ordered(by_slot, self._BADGE_LEFT_SLOTS):
            w = self._cell_width(fm, cell)
            self._paint_cell(painter, QRect(lx, line.top(), w, line.height()), cell, font)
            lx += w + _CELL_GAP

    def _paint_plot_line(self, painter, line: QRect, plot: str, font, *, color=None) -> None:
        """comfy_plus's middle line — the plot, elided to fit, muted token (or
        the highlight foreground on a selected row, where a muted grey would be
        sitting on the accent fill)."""
        fm = QFontMetrics(font)
        elided = fm.elidedText(plot, Qt.TextElideMode.ElideRight, line.width())
        self._draw_text(painter, line, elided, color or _theme.COLOR_MUTED, font)

    # ── Comfy (two lines) ────────────────────────────────────────────────────

    def _paint_comfy(self, painter, rect: QRect, index, default_color, font,
                     *, title_color=None, selected: bool = False) -> None:
        fm = QFontMetrics(font)
        line1, line2 = stacked_line_rects(rect, fm.height(), _LINE_GAP)
        self._paint_title_year_line(painter, line1, index, default_color, font,
                                    title_color=title_color, selected=selected)
        self._paint_badge_line(painter, line2, index, font,
                               selected_color=default_color if selected else None)

    # ── Comfy+ (two or three lines — plot line collapses when absent) ───────

    def _paint_comfy_plus(self, painter, rect: QRect, index, default_color, font,
                          *, title_color=None, selected: bool = False) -> None:
        fm = QFontMetrics(font)
        plot = index.data(PLOT_ROLE) or ""
        lines = stacked_line_rects_n(rect, fm.height(), _LINE_GAP, 3 if plot else 2)
        selected_color = default_color if selected else None
        self._paint_title_year_line(painter, lines[0], index, default_color, font,
                                    title_color=title_color, selected=selected)
        if plot:
            self._paint_plot_line(painter, lines[1], plot, font,
                                  color=selected_color or _theme.COLOR_MUTED)
            self._paint_badge_line(painter, lines[2], index, font,
                                   selected_color=selected_color)
        else:
            self._paint_badge_line(painter, lines[1], index, font,
                                   selected_color=selected_color)
