"""Rendered-appearance gate for the results row's three emphasis tiers (#298).

Every assertion here is on what the delegate PAINTS — the colours handed to a
real ``QPainter``, the ``QRect`` geometry of the cells it draws, and WCAG
contrast computed on the actual fill/foreground pairs — never on a token merely
being defined, a cell field merely being set, or a list merely being ordered.
That distinction is the reason this file exists: the suite that was supposed to
stop the row from drifting asserted parsed data, cell ORDER, and token
EXISTENCE, all of which pass for infinitely many wrong-looking renderings.

Each test below was run against the pre-#298 delegate and FAILS there; the
docstrings record what the old value was, so a future change that quietly
reverts one has to argue with a number rather than with a name.
"""

from __future__ import annotations

import re

import pytest
from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QFont, QPainter, QPixmap

import metatv.gui.channel_list_delegate as d
# CHIP_SLOT_* are defined in channel_row_cells and the tier-3 geometry in
# channel_row_cell_paint; naming the DEFINING module (CLAUDE.md) is what
# keeps these from breaking when the delegate stops importing one.
import metatv.gui.channel_row_cells as _cells
import metatv.gui.channel_row_cell_paint as _cellpaint
from metatv.core.channel_name_utils import collection_display
from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from metatv.gui.channel_row_cells import (
    ROW_META_ORDER,
    ROW_RAIL_ORDER,
    _language_cell,
    _MAX_GENRES,   # defined here; the delegate imported it only to re-export
)
from tests.conftest import ROW_ROLE_DEFAULTS, paint_channel_row, row_model

PALETTES = list(tp.PALETTES.keys())
ROW_W = 620


# ---------------------------------------------------------------------------
# Contrast — WCAG 2.1, on values COMPOSITED onto the surface they land on.
# ---------------------------------------------------------------------------

_RGBA = re.compile(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)")


def _rgb(value) -> tuple[int, int, int, float]:
    """(r, g, b, alpha) for any token value the delegate can paint."""
    text = value.name() if isinstance(value, QColor) else str(value)
    match = _RGBA.match(text.strip())
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
                float(match.group(4)) if match.group(4) else 1.0)
    color = QColor(text)
    return (color.red(), color.green(), color.blue(), color.alphaF())


def _over(fg, bg) -> tuple[int, int, int]:
    """*fg* composited over *bg* — the step whose absence let a 1.1:1 button
    pass every check in this project once already. An alpha token measured as
    if it were opaque is a measurement of a colour nobody ever sees."""
    fr, fg_, fb, fa = _rgb(fg)
    br, bg_, bb, _ = _rgb(bg)
    return (round(fr * fa + br * (1 - fa)),
            round(fg_ * fa + bg_ * (1 - fa)),
            round(fb * fa + bb * (1 - fa)))


def _luminance(value) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = value if isinstance(value, tuple) else _rgb(value)[:3]
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg, bg) -> float:
    hi, lo = sorted((_luminance(_over(fg, bg)), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _list_surface() -> str:
    """The colour the results list actually paints its rows on.

    ``QPalette.Base``, which :func:`theme.qt_palette` sources from
    ``COLOR_BG_DEEP`` — NOT ``COLOR_BG_SECTION``. Measuring row contrast
    against the section background would be measuring against a surface the
    rows are not on.
    """
    return str(_theme.COLOR_BG_DEEP)


# ---------------------------------------------------------------------------
# Capture harness — records what the delegate paints for one full row.
# ---------------------------------------------------------------------------

#: The row this file measures. Field values live in ``ROW_ROLE_DEFAULTS``
#: (tests/conftest.py) so a role added to the row shows up here automatically
#: instead of being quietly absent.
_ROW_DATA = dict(ROW_ROLE_DEFAULTS)


def _index(**overrides):
    model = row_model(**overrides)
    index = model.index(0)
    index._model_keepalive = model  # noqa: SLF001
    return index


def _paint_row(delegate: ChannelRowDelegate, index, *, selected=False,
               density=d.DENSITY_COMFY):
    """Run the REAL ``paint()`` and record every rect it drew into.

    This replaced a harness that called ``_paint_comfy``/``_paint_compact``
    directly and stubbed the title colour with a test-only method bolted onto
    the delegate. Both are gone: the V3 row has one paint entry point, and
    driving anything else means the geometry chokepoint and the selection
    handling are never exercised by the tests that claim to cover them.
    """
    delegate.set_thumbnails_enabled(True)
    return paint_channel_row(delegate, index, rect=QRect(0, 0, ROW_W, 68),
                             selected=selected, density=density)


# ---------------------------------------------------------------------------
# 1. The title leads its row — the whole point of the redesign.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_title_outcontrasts_every_other_thing_painted_in_its_row(qapp, palette_name):
    """The title must be the loudest element in its own row, measured.

    Pre-#298 the title painted in ``COLOR_TEXT``, the SAME token as the
    metadata beside it, so it had no emphasis to lose — on the list surface
    this redesign moves the rows onto, that token measures 9.06:1 while the
    region hue beside it measures 10.06:1 and genre 10.34:1, i.e. the row's
    brightest text was a two-letter country code. It is now
    ``on-surface.strong`` at 16.25:1.

    Honest scope: run against the OLD list surface (the #363a3f hairline slab,
    which was itself the bug) the old row passed this particular check at
    5.50:1 vs 6.11:1 — because everything was equally washed out, not because
    the title led. The emphasis claim is nailed down by the weight test and the
    fill count below; this one is the forward gate that keeps it true.
    """
    _theme.apply_theme(palette_name)
    painted = _paint_row(ChannelRowDelegate(), _index())
    surface = _list_surface()

    title_contrast = _contrast(_theme.COLOR_ROW_TITLE, surface)
    for _rect, text, color, _font in painted.texts:
        if text == _ROW_DATA["TITLE_ROLE"]:
            continue
        assert _contrast(color, surface) < title_contrast, (
            f"{palette_name}: {text!r} ({color}) is painted at least as loud as "
            f"the title ({title_contrast:.2f}:1)"
        )
    for _rect, cell in painted.cells:
        # A tier-1 chip's text sits on its OWN fill, so it is measured there.
        against = cell.bg if cell.bg else surface
        assert _contrast(cell.fg, against) < title_contrast, (
            f"{palette_name}: chip {cell.text!r} is painted at least as loud as the title"
        )


def test_title_is_heavier_than_the_metadata_around_it(qapp):
    """Weight, not just colour — one Radix step of lightness alone does not
    make a title read as the row's subject.

    PRE-#298 THIS FAILED: every run in the row was painted with the same
    ``opt.font``, so ``title_font.weight() == other.weight()`` exactly.
    """
    painted = _paint_row(ChannelRowDelegate(), _index())
    title_font = next(f for _r, t, _c, f in painted.texts
                      if t == _ROW_DATA["TITLE_ROLE"])
    assert title_font.weight() > QFont().weight()


# ---------------------------------------------------------------------------
# 2. Tier 1 is language and state ONLY — asserted on real painter fills.
# ---------------------------------------------------------------------------

class _FillRecordingPainter(QPainter):
    """A real QPainter that remembers every brush it was actually asked to
    fill with. Subclassing the real class matters: the delegate calls
    ``setBrush(Qt.BrushStyle.NoBrush)`` and ``drawRoundedRect`` in orders a
    mock would happily accept while painting nothing."""

    def __init__(self, device) -> None:
        super().__init__(device)
        self.fills: list[str] = []

    def drawRoundedRect(self, *args, **kwargs):  # noqa: N802
        # Compared against the ENUM MEMBER, not against 0: PyQt6 exposes scoped
        # enums as real Python enums, so ``style() != 0`` is true even for
        # NoBrush and every outline stroke would be recorded as a fill.
        if self.brush().style() != Qt.BrushStyle.NoBrush:
            self.fills.append(self.brush().color().name())
        return super().drawRoundedRect(*args, **kwargs)


@pytest.mark.parametrize("palette_name", PALETTES)
def test_only_the_language_chip_is_actually_filled(qapp, palette_name):
    """Counted from real fill operations, not from cell fields.

    PRE-#298 THIS FAILED: a row like this one painted FIVE fills — language,
    region, genre, collection and (solid, at full opacity) platform — plus a
    tinted interior behind the quality outline. Tier 1 is language and genuine
    row state; a row with a fill on every fact has no top tier at all.

    Measured on a row at REST. A selected/hovered row legitimately adds its own
    chrome fill, and the artwork well legitimately fills a placeholder tile —
    both are row STATE and row STRUCTURE, neither is a facet, so the row is
    painted without either.
    """
    _theme.apply_theme(palette_name)
    delegate = ChannelRowDelegate()
    delegate.set_density(d.DENSITY_COMFY)
    delegate.set_thumbnails_enabled(False)
    pixmap = QPixmap(ROW_W, 68)
    painter = _FillRecordingPainter(pixmap)
    try:
        delegate.paint(painter, _rest_option(QRect(0, 0, ROW_W, 68)), _index())
    finally:
        painter.end()

    expected = QColor(str(_theme.COLOR_ROW_LANGUAGE_FILL)).name()
    assert painter.fills == [expected], (
        f"{palette_name}: expected exactly one fill (the language chip), got "
        f"{painter.fills}"
    )


def _rest_option(rect):
    """A style option for a row that is neither selected nor hovered."""
    from PyQt6.QtWidgets import QStyle, QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.rect = rect
    opt.state = QStyle.StateFlag.State_Enabled
    opt.palette = _theme.qt_palette()
    return opt


@pytest.mark.parametrize("palette_name", PALETTES)
def test_language_chip_text_clears_4_5_on_its_own_fill(qapp, palette_name):
    """The one surviving fill has to be readable ON ITSELF, not on the list."""
    _theme.apply_theme(palette_name)
    cell = _language_cell("EN")
    ratio = _contrast(cell.fg, cell.bg)
    assert ratio >= 4.5, f"{palette_name}: language chip is {ratio:.2f}:1 on its own fill"


@pytest.mark.parametrize("palette_name", PALETTES)
def test_the_language_fill_is_visible_against_the_list_surface(qapp, palette_name):
    """A fill nobody can see is not a tier — it is the tinted-text tier with
    extra steps."""
    _theme.apply_theme(palette_name)
    fill, surface = str(_theme.COLOR_ROW_LANGUAGE_FILL), _list_surface()
    assert abs(_luminance(fill) - _luminance(surface)) > 0.004, (
        f"{palette_name}: the language fill is indistinguishable from the list"
    )


# ---------------------------------------------------------------------------
# 3. Tier 2 keeps the hue — and no two facets may share one.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_no_two_facet_hues_are_the_same(qapp, palette_name):
    """Once the box is gone the hue is the ENTIRE facet encoding, so two facets
    sharing one stops being a near-miss and becomes a false statement about the
    data. The owner caught exactly this in the first mockup."""
    _theme.apply_theme(palette_name)
    hues = {
        "language": str(_theme.COLOR_ROW_LANGUAGE),
        "region": str(_theme.COLOR_ROW_REGION),
        "genre": str(_theme.COLOR_ROW_GENRE),
        "platform": str(_theme.COLOR_ROW_PLATFORM),
    }
    seen: dict[str, str] = {}
    for facet, value in hues.items():
        name = QColor(value).name()
        assert name not in seen, (
            f"{palette_name}: {facet} and {seen[name]} are both {name}"
        )
        seen[name] = facet


@pytest.mark.parametrize("palette_name", PALETTES)
def test_every_tier_2_hue_clears_4_5_on_the_list_surface(qapp, palette_name):
    """Tier 2 is TEXT — with the box gone there is no tinted backing to help
    it, so the hue itself has to carry the contrast."""
    _theme.apply_theme(palette_name)
    surface = _list_surface()
    for name in ("COLOR_ROW_REGION", "COLOR_ROW_GENRE", "COLOR_ROW_PLATFORM",
                 "COLOR_ROW_COLLECTION", "COLOR_ROW_META"):
        ratio = _contrast(getattr(_theme, name), surface)
        assert ratio >= 4.5, f"{palette_name}: {name} is {ratio:.2f}:1 on the list"


# ---------------------------------------------------------------------------
# 4. Tier 3 — outlined, never filled, and quality sits by the title.
# ---------------------------------------------------------------------------

def test_quality_hugs_the_title_and_is_not_in_the_rail(qapp):
    """Quality qualifies THIS COPY of the title, so it sits next to it.

    #298 established that; V3 briefly moved it into the right-hand rail to give
    it a fixed column, and the owner reported the cost within a day: quality is
    on 6.6% of rows, and a right-aligned group containing an optional member
    puts every member LEFT of it in a different column depending on that
    member's presence — the language badge visibly jumped down a scrolling
    list. Against the title, its absence costs a few pixels of title box and
    nothing else.

    Geometry, not order: a cell can be first in a list and still be painted on
    the far side of the row.
    """
    painted = _paint_row(ChannelRowDelegate(), _index())
    quality = painted.rect_of("4K")
    title = painted.rect_of(_ROW_DATA["TITLE_ROLE"])
    language = painted.rect_of("EN")

    # On the title's LINE, and left of the rail that shares it.
    #
    # Overlap, not identical centres. This asserted
    # ``quality.center().y() == title.center().y()`` and that is a pixel, not a
    # property: it holds only while the two text runs happen to be the same
    # height. Applying the app's own bundled face (which the suite had never
    # done — see conftest's _bundled_ui_font) makes the chip 16px tall against
    # the title's 18, so the centres round one pixel apart and a correct
    # layout failed.
    #
    # What "same line" actually means is that the boxes overlap almost
    # completely. On the meta line they would not overlap at all, which is the
    # arrangement this test exists to forbid.
    overlap = min(quality.bottom(), title.bottom()) - max(quality.top(), title.top())
    assert overlap >= 0.6 * min(quality.height(), title.height()), (
        f"quality must sit on the title's own line, not the meta line "
        f"(overlap {overlap}px of {min(quality.height(), title.height())}px)"
    )
    assert quality.left() >= title.left()
    assert quality.right() < language.left(), (
        "quality is painted inside the right-hand rail"
    )
    # …and nowhere near the right edge — the arrangement's failure signature.
    assert quality.left() < ROW_W // 2, (
        f"quality parked on the right half ({quality.left()} of {ROW_W})"
    )
    # The meta line is a separate line below it.
    assert painted.rect_of("2024").top() > title.bottom() - title.height() // 2


def test_tier_3_boxes_are_never_filled(qapp):
    """PRE-#298 THIS FAILED: the quality chip painted an ``OVERLAY_08``
    interior — a white-alpha wash used as a RESTING fill, which is the exact
    move that put an un-authored, un-themeable grey into the row."""
    painted = _paint_row(ChannelRowDelegate(), _index())
    outlined = [c for _r, c in painted.cells if c.outline]
    assert [c.text for c in outlined] == ["4K"], (
        "quality is tier 3's only member — the year joined the meta line, where "
        f"the separator does the boxing; got {[c.text for c in outlined]}"
    )
    for cell in outlined:
        assert cell.bg is None, f"{cell.text!r} outline box is filled with {cell.bg}"


def test_outline_box_fits_inside_the_line_it_is_drawn_on(qapp):
    """The stroke is drawn ON the rect's edge and the row clips to the fill, so
    a box at full height loses its top and bottom edges — which rendered the
    chip as a lozenge with the ends cut off."""
    from metatv.gui import channel_row_layout as _layout

    delegate = ChannelRowDelegate()
    painted = _paint_row(delegate, _index())
    fill = _layout.row_layout(QRect(0, 0, ROW_W, 68), has_art=True,
                              art_square=False, rail_w=0).fill
    box = painted.rect_of("4K").adjusted(0, _cellpaint._OUTLINE_V_INSET, 0, -_cellpaint._OUTLINE_V_INSET)
    assert box.top() > fill.top() and box.bottom() < fill.bottom()


# ---------------------------------------------------------------------------
# 5. Chip order comes from ONE constant — asserted on painted x positions.
# ---------------------------------------------------------------------------

def test_meta_line_positions_follow_the_single_order_constant(qapp):
    """Order != position. This walks the meta line left to right and checks the
    painted x of each segment against :data:`ROW_META_ORDER`, so re-ordering the
    constant is the only way to re-order the row."""
    painted = _paint_row(ChannelRowDelegate(), _index(VARIANT_COUNT_ROLE=3))
    slot_text = {
        _cells.CHIP_SLOT_YEAR: "2024",
        _cells.CHIP_SLOT_REGION: "KR",
        _cells.CHIP_SLOT_GENRE: "Drama / Thriller",
        _cells.CHIP_SLOT_COLLECTION: collection_display(_ROW_DATA["COLLECTION_ROLE"], None),
        _cells.CHIP_SLOT_VARIANTS: "×3",
    }
    expected = [slot_text[s] for s in ROW_META_ORDER if s in slot_text]
    lefts = [painted.rect_of(text).left() for text in expected]
    assert lefts == sorted(lefts), (
        f"painted left-to-right order {expected} does not match ROW_META_ORDER"
    )


def test_rail_positions_follow_the_single_order_constant(qapp):
    """The same guarantee for the right-hand rail."""
    painted = _paint_row(ChannelRowDelegate(),
                         _index(SUBTITLE_MARKER_ROLE="KO-SUB",
                                SECONDARY_LANGUAGE_ROLE="JA"))
    slot_text = {
        _cells.CHIP_SLOT_SUBTITLE: "KO-SUB",
        _cells.CHIP_SLOT_LANGUAGE_2: "JA",
        _cells.CHIP_SLOT_LANGUAGE: "EN",
    }
    expected = [slot_text[s] for s in ROW_RAIL_ORDER if s in slot_text]
    lefts = [painted.rect_of(text).left() for text in expected]
    assert lefts == sorted(lefts), (
        f"painted left-to-right order {expected} does not match ROW_RAIL_ORDER"
    )


def test_multiple_genres_are_painted_when_present(qapp):
    """A title that is both Drama and Thriller was claiming to be only Drama.

    They now paint as ONE run — three separate cells would put three ``·``
    separators inside a single fact.
    """
    painted = _paint_row(ChannelRowDelegate(), _index())
    assert painted.cell("Drama / Thriller") is not None
    assert painted.cell("Drama") is None


def test_genre_count_is_capped(qapp):
    """Past three they stop being scannable and start eating the title's box."""
    painted = _paint_row(
        ChannelRowDelegate(),
        _index(GENRES_ROLE=("A", "B", "C", "D", "E")),
    )
    run = next(c for _r, c in painted.cells if c.facet == "genre")
    assert run.text.count("/") == _MAX_GENRES - 1
    assert "D" not in run.text.split(" / ")


# ---------------------------------------------------------------------------
# 6. A selected row is a TINT, so what sits on it keeps its own hue.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_a_selected_row_keeps_every_hue_and_stays_legible(qapp, palette_name):
    """The inverse of the pre-V3 rule, and deliberately so.

    #298's selected row was a SATURATED accent fill, so every cell had to be
    flattened onto the highlight foreground to stay readable — which meant the
    one row the user had deliberately picked was the one row that lost its facet
    encoding. V3's selection is ``primary.container``, a tint, so the hues
    survive; this test is what stops a future change from re-saturating the fill
    without noticing what it costs.
    """
    _theme.apply_theme(palette_name)
    at_rest = _paint_row(ChannelRowDelegate(), _index())
    selected = _paint_row(ChannelRowDelegate(), _index(), selected=True)

    resting_hues = {c.text: str(c.fg) for _r, c in at_rest.cells}
    for _rect, cell in selected.cells:
        assert str(cell.fg) == resting_hues[cell.text], (
            f"{palette_name}: {cell.text!r} lost its hue on a selected row"
        )
        against = cell.bg if cell.bg else _theme.COLOR_ROW_SELECTED_FILL
        ratio = _contrast(cell.fg, against)
        assert ratio >= 4.5, (
            f"{palette_name}: {cell.text!r} is {ratio:.2f}:1 on the selection tint"
        )


# ---------------------------------------------------------------------------
# 7. The surfaces underneath — the list, and a missing poster.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_the_list_surface_is_not_the_hairline_token(qapp, palette_name):
    """PRE-#298 THIS FAILED: ``QPalette.Base`` — the background of the results
    list and every text field — read ``COLOR_LINE``, a SEPARATOR token. In
    Midnight that painted the channel list on #363a3f, a mid-grey slab
    noticeably lighter than the app around it (owner report). A resting surface
    must be a surface token.
    """
    from metatv.gui.theme import qt_palette
    from PyQt6.QtGui import QPalette

    _theme.apply_theme(palette_name)
    base = qt_palette().color(QPalette.ColorRole.Base).name()
    assert base != QColor(str(_theme.COLOR_LINE)).name()
    assert base == QColor(str(_theme.COLOR_BG_DEEP)).name()


@pytest.mark.parametrize("palette_name", ["Midnight", "Graphite"])
def test_the_list_recedes_below_the_app_chrome_in_dark_palettes(qapp, palette_name):
    """Content recessed into the shell, not floating on top of it — and
    distinct from it, so the panel edge stays readable without a border."""
    _theme.apply_theme(palette_name)
    list_lum = _luminance(_list_surface())
    chrome_lum = _luminance(str(_theme.COLOR_BG_SECTION))
    assert list_lum < chrome_lum
    assert chrome_lum - list_lum > 0.001


@pytest.mark.parametrize("palette_name", PALETTES)
def test_a_missing_poster_reads_as_absence_not_as_content(qapp, palette_name):
    """PRE-#298 THIS FAILED: the placeholder tile painted ``COLOR_BG_CARD``, a
    step ABOVE the list surface, which made a MISSING image the brightest
    object in its row — a hole in the data shouting over the title that is
    actually there. (Before that it was ``COLOR_FAINT``, at 2.10:1.)

    Also checks the letter on the tile still clears the 4.5:1 text floor, so
    "sink it" cannot be over-applied into invisibility.
    """
    _theme.apply_theme(palette_name)
    tile = str(_theme.COLOR_ROW_THUMB_PLACEHOLDER)
    surface = _list_surface()
    # Contrast RATIO, not a raw luminance delta: luminance is not perceptually
    # uniform, so one fixed delta is a different-sized step near white than it
    # is near black, and a light palette would be held to a stricter rule than
    # a dark one for no reason.
    ratio = _contrast(tile, surface)
    assert ratio < 1.15, (
        f"{palette_name}: the placeholder tile stands {ratio:.3f}:1 off the list "
        f"surface — a missing image is announcing itself"
    )
    letter = _contrast(_theme.COLOR_TEXT, tile)
    assert letter >= 4.5, f"{palette_name}: placeholder letter is {letter:.2f}:1"


# ---------------------------------------------------------------------------
# 8. The token layer these tiers are built on.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_every_row_token_resolves_in_every_palette(qapp, palette_name):
    """A row token missing from one palette is an AttributeError raised inside
    ``paint()`` — i.e. a crash while scrolling, in one theme only."""
    _theme.apply_theme(palette_name)
    for name in ("COLOR_ROW_TITLE", "COLOR_ROW_LANGUAGE", "COLOR_ROW_LANGUAGE_FILL",
                 "COLOR_ROW_REGION", "COLOR_ROW_GENRE", "COLOR_ROW_PLATFORM",
                 "COLOR_ROW_META", "COLOR_ROW_COLLECTION",
                 "COLOR_ROW_THUMB_PLACEHOLDER"):
        value = getattr(_theme, name, None)
        assert value, f"{palette_name}: {name} is missing"
        assert QColor(str(value)).isValid(), f"{palette_name}: {name}={value!r} is unpaintable"
