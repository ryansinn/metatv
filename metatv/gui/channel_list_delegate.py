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

   Chips are painted as rounded rects, one hue per facet (#257 — the ONE chip
   system, adopting ``theme.LANG_CHIP``'s "hue-tinted background + same-hue
   bright foreground" idiom instead of a neutral white-alpha background; hues
   come from ``filter_group_row._accent_colors()``, never invented locally):
   language (own/secondary language + subtitle marker) = blue, region = green,
   genre = teal, collection = muted grey (``OVERLAY_08`` + ``COLOR_MUTED``,
   unchanged). Two facets are deliberately styled DIFFERENTLY from that tinted-
   fill idiom: platform (Netflix/Disney+/Apple+/…, a ``PLATFORM_CODES`` member
   sharing the region chip's role/field) is a SOLID purple fill, and quality is
   OUTLINE ONLY (border + text in the tier's ``_quality_outline_colors()`` hue
   — a dedicated per-palette family, contrast-tuned so it clears 4.5:1 against
   the list's own background in every palette — a subtle ``OVERLAY_08`` tint
   instead of literally transparent; see ``_quality_cell``'s docstring). All
   colours are theme tokens, never literals. The title is elided
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
    """One paintable unit: either a plain text run or a coloured chip.

    A chip (``is_chip=True``) is a SOLID fill by default — ``bg`` painted
    behind ``fg``-coloured text (the LANG_CHIP idiom: hue-tinted background +
    same-hue bright foreground, or platform's solid accent fill). Setting
    ``outline=True`` instead draws ``bg`` (if any — a subtle tint, never
    literally required) as a BORDER stroke around a chip whose interior is
    otherwise unfilled, with the text in ``fg`` — the quality chip's own
    treatment (#257), distinct from every other facet chip.
    """

    text: str
    is_chip: bool
    fg: str        # QColor-constructible token/hex (theme.* or a QColor.name())
    bg: Optional[str] = None   # chip background/border token (chip only)
    outline: bool = False      # True => border-only chip (quality), never filled
    # Facet identity + hover copy (#24). A delegate-painted chip has no widget,
    # so it cannot carry setToolTip() — the view hit-tests the painted rect and
    # renders `tip` itself. `facet`/`value` are what a click filters on; both
    # empty means the cell is decorative and neither hovers nor clicks.
    facet: str = ""
    value: str = ""
    tip: str = ""


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
    # Coerce: the year reaches us as a str from ChannelListDTO but as an int
    # from some model stubs/roles, and a non-str text reaches QFontMetrics
    # .horizontalAdvance() and raises.
    if not year:
        return None
    # No facet: "year" is not a tag facet (tag_decomposer emits audio /
    # collection / genre / language / quality / region), so there is nothing
    # to filter on. Tooltip only — a chip that looks clickable and does
    # nothing is worse than one that plainly just labels itself.
    return _Cell(str(year), False, _theme.COLOR_MUTED, tip=f"Released {year}")


def _quality_cell(token: str) -> Optional[_Cell]:
    """Quality chip — OUTLINE ONLY (What's New 257, Part A): border + text in the tier's
    colour from ``_quality_outline_colors()``, not a solid fill — the one
    facet chip styled differently from the rest of the row's new
    hue-tinted-fill family.

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

    Background stays ``OVERLAY_08`` (a subtle, existing neutral tint) rather
    than literally transparent, per the original owner instruction — this
    softens the chip's visual boundary; it isn't what makes the text/border
    contrast pass (a same/darker-neutral background tint alone cannot raise
    contrast when the tier text is the darker of the pair — verified by
    direct computation), the per-palette hue-preserving lightness tuning does.
    """
    if not token:
        return None
    upper = token.upper()
    color = _quality_outline_colors().get(upper, _theme.COLOR_FAINT)
    return _Cell(quality_display(upper), True, color, _theme.OVERLAY_08, outline=True,
                 facet="quality", value=upper,
                 tip=f"Picture quality: {quality_display(upper)} — click to show "
                     f"only {quality_display(upper)} versions")


def _region_or_platform_cell(code: str, platform_style: str) -> Optional[_Cell]:
    """Region-or-platform chip for ``LANGUAGE_ROLE`` (``detected_region`` —
    the field doubles as BOTH a geographic region code and a streaming-
    platform code, e.g. ``"US"`` vs ``"NF"``/``"A+"``).

    Two distinct hues (#257 Part A): a recognized :data:`PLATFORM_CODES`
    member renders as a SOLID purple fill (``platform_display`` resolves the
    brand name per *platform_style*); anything else renders as the
    LANG_CHIP-idiom green-tinted region chip, unchanged code text.
    """
    if not code:
        return None
    if code in PLATFORM_CODES:
        brand = platform_display(code, platform_style)
        return _Cell(
            brand, True,
            _theme.COLOR_TEXT_HI, _theme.COLOR_ACCENT_PURPLE,
            facet="region", value=code,
            tip=f"Streaming platform: {brand} — click to show only {brand}",
        )
    return _Cell(code, True, _theme.COLOR_ACCENT_GREEN, _theme.OVERLAY_GREEN_15,
                 facet="region", value=code,
                 tip=f"Region: {_region_label(code)} — click to show only this region")


def _language_cell(text: str, *, filterable: bool = True) -> Optional[_Cell]:
    """Language-family chip (LANG_CHIP idiom, blue) — the channel's own/
    secondary language and any sub/dub marker (``PRIMARY_LANGUAGE_ROLE``,
    ``SECONDARY_LANGUAGE_ROLE``, ``SUBTITLE_MARKER_ROLE``): all
    language-adjacent facets, sharing one hue."""
    if not text:
        return None
    if not filterable:
        # Sub/dub markers ("AR-SUB") are NOT language tags — there is no facet
        # that can filter them (the audio facet is empty in practice), so the
        # chip explains itself and stops there. Giving it facet="language"
        # rendered a pointing-hand cursor over a click that silently did
        # nothing, which is worse than no affordance.
        return _Cell(text, True, _theme.COLOR_ACCENT_BLUE, _theme.OVERLAY_BLUE_15,
                     tip=f"Subtitles/dub: {text}")
    return _Cell(text, True, _theme.COLOR_ACCENT_BLUE, _theme.OVERLAY_BLUE_15,
                 facet="language", value=text,
                 tip=f"Language: {_region_label(text)} — click to show only this language")


def _genre_cell(genre: str) -> Optional[_Cell]:
    """Genre chip (LANG_CHIP idiom, teal) — comfy line 2's taxonomy group
    (#257 Part C; state stays left — rating glyph + variant badge — taxonomy
    right: genre, then the collection chip)."""
    if not genre:
        return None
    return _Cell(genre, True, _theme.COLOR_ACCENT_TEAL, _theme.OVERLAY_TEAL_15,
                 facet="genre", value=genre,
                 tip=f"Genre: {genre} — click to show only {genre}")


def _category_cell(category: str, platform_code: str = "",
                   filter_category: str = "") -> Optional[_Cell]:
    """Collection chip — MUTED GREY, unchanged (owner call #257):
    ``OVERLAY_08`` + ``COLOR_MUTED``. The TEXT is a render-layer transform
    via :func:`~metatv.core.channel_name_utils.collection_display` (trailing
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
    return _Cell(display, True, _theme.COLOR_MUTED, _theme.OVERLAY_08,
                 facet="collection", value=(filter_category or ""),
                 tip=f"Collection: {display} — click to show only this collection")


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
    return _Cell(f"×{count}", True, _theme.COLOR_MUTED, _theme.OVERLAY_08,
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
        if self._density == DENSITY_COMPACT:
            self._paint_compact(painter, content_rect, index, default_color, opt.font)
        elif self._density == DENSITY_COMFY_PLUS:
            self._paint_comfy_plus(painter, content_rect, index, default_color, opt.font)
        else:
            self._paint_comfy(painter, content_rect, index, default_color, opt.font)
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
        painter.setBrush(_to_qcolor(_theme.COLOR_FAINT))
        painter.drawRoundedRect(rect, _THUMB_RADIUS, _THUMB_RADIUS)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_to_qcolor(_theme.COLOR_MUTED))
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
            # Border-only chip (quality, #257) — never a solid fill. ``bg``
            # (a subtle tint, e.g. OVERLAY_08) paints as the interior when
            # present, then the border + text are ``fg`` (the tier colour).
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(_to_qcolor(cell.bg) if cell.bg else Qt.BrushStyle.NoBrush)
            _r = self._chip_radius(rect)
            painter.drawRoundedRect(rect, _r, _r)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(_to_qcolor(cell.fg))
            _r = self._chip_radius(rect)
            painter.drawRoundedRect(rect, _r, _r)
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
            _region_or_platform_cell(index.data(LANGUAGE_ROLE) or "", self._effective_platform_style()),
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
            # The chip hugs the TITLE TEXT, not the title box. ``title_box_w`` is
            # the full space up to the right group, so offsetting by it parked the
            # chip against the right group instead (owner UX report, 0.21.0).
            title_w = min(fm.horizontalAdvance(elided), title_box_w)
            q_rect = QRect(x + title_w + _CELL_GAP, rect.top(), quality_w, rect.height())
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
        ``[year][region/platform chip][subtitle marker chip][secondary
        language chip][primary language chip]`` — the channel's OWN (honest)
        language (``detected_prefix``) always sits furthest right (owner
        spec); the region/platform chip (``detected_region``) sits leftmost
        of the group since it answers a different question (where/which
        service, not what language).
        """
        fm = QFontMetrics(font)
        media_icon = index.data(MEDIA_ICON_ROLE) or ""
        fav_glyph = index.data(FAV_GLYPH_ROLE) or ""
        playback_glyph = index.data(PLAYBACK_GLYPH_ROLE) or ""
        playback_color = index.data(PLAYBACK_GLYPH_COLOR_ROLE)
        match_marker = index.data(MATCH_MARKER_ROLE) or ""
        title = index.data(TITLE_ROLE) or ""
        quality_cell = _quality_cell(index.data(QUALITY_TOKEN_ROLE) or "")

        # _language_cell is the language-family chip builder (own/secondary
        # language or a compound sub/dub marker like "AR-SUB" are all
        # language-adjacent, short code-shaped tokens — blue). The region/
        # platform slot uses the DIFFERENT-hue _region_or_platform_cell
        # builder (green region vs solid-purple platform, #257 Part A).
        right_cells = [c for c in (
            _year_cell(index.data(YEAR_ROLE) or ""),
            _region_or_platform_cell(
                index.data(LANGUAGE_ROLE) or "", self._effective_platform_style()
            ),                                                           # region/platform
            _language_cell(index.data(SUBTITLE_MARKER_ROLE) or "",
                           filterable=False),                               # e.g. "AR-SUB"
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
            # Hug the title TEXT — see the note in _paint_compact.
            title_w = min(fm.horizontalAdvance(elided), title_box_w)
            q_rect = QRect(x + title_w + _CELL_GAP, line.top(), quality_w, line.height())
            self._paint_cell(painter, q_rect, quality_cell, font)

        for cell, r in zip(right_cells, right_rects):
            self._paint_cell(painter, r, cell, font)

    def _paint_badge_line(self, painter, line: QRect, index, font) -> None:
        """Badge row — grammar is STATE on the left, TAXONOMY on the right
        (#257 Part C): a rating glyph + the ``×N`` variant badge left, a
        genre chip (teal) then the clean collection chip (``detected_collection``,
        render-time-transformed via ``_category_cell``/``collection_display``)
        right-aligned, genre before collection. Used as comfy's line 2 and
        comfy_plus's final line. Region/subtitle/language chips and the
        quality chip live on line 1 (owner spec) — this line never carries
        them."""
        fm = QFontMetrics(font)
        region_code = index.data(LANGUAGE_ROLE) or ""
        platform_code = region_code if region_code in PLATFORM_CODES else ""
        genre_cell = _genre_cell(index.data(GENRE_ROLE) or "")
        collection_cell = _category_cell(index.data(COLLECTION_ROLE) or "", platform_code,
                                        filter_category=index.data(CATEGORY_ROLE) or "")

        right_cells = [c for c in (genre_cell, collection_cell) if c is not None]
        right_widths = [self._cell_width(fm, c) for c in right_cells]
        right_rects = right_aligned_rects(line, right_widths, _CELL_GAP)

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

        for cell, r in zip(right_cells, right_rects):
            self._paint_cell(painter, r, cell, font)

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
