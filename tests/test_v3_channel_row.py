"""Rendered-appearance gate for the V3 channel row.

Every assertion is on what the delegate PAINTS — the ``QRect`` a thing landed
in, the colour a real ``QPainter`` put on a real pixmap, or WCAG contrast
computed on the two values that actually met. Never on a token merely being
defined, a cell field merely being set, or a list merely being ordered: those
pass for infinitely many wrong-looking rows, which is exactly how two v0.21.0
defects shipped through a green suite.

The three rules this file exists to hold, in the order they matter:

1. **Nothing moves when a row is selected.** Asserted by painting the same row
   in all four states and comparing every rect.
2. **Kind is structural** — the mark, the artwork shape and the first word of
   the meta line all follow ``MEDIA_KIND_ROLE``.
3. **Only render what exists** — quality is not a reserved column, the action
   gutter is.
"""

from __future__ import annotations

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont

import metatv.gui.channel_list_delegate as d
from metatv.gui import channel_row_layout as layout
from metatv.gui import theme as _theme
from metatv.gui import theme_palettes as tp
from metatv.gui.channel_list_delegate import ChannelRowDelegate
from tests.conftest import (
    paint_channel_row,
    render_channel_row,
    row_model,
)

PALETTES = list(tp.PALETTES.keys())
ROW = QRect(0, 0, 620, 68)


@pytest.fixture
def delegate(qapp):
    deleg = ChannelRowDelegate()
    deleg.set_density(d.DENSITY_COMFY)
    deleg.set_thumbnails_enabled(True)
    return deleg


def _index(**overrides):
    model = row_model(**overrides)
    index = model.index(0)
    # The model is parented to nothing and would be collected out from under the
    # index; stash it on the index's own lifetime.
    index._model_keepalive = model  # noqa: SLF001
    return model, index


# ---------------------------------------------------------------------------
# Rule 1 — nothing moves when a row is selected.
# ---------------------------------------------------------------------------

def test_row_geometry_is_identical_in_every_state(delegate):
    """The whole point of the redesign: a row's columns do not shift when it is
    selected, hovered, or both.

    Asserted against the PAINTED rects rather than against ``row_layout``'s
    signature, because a painter is free to ignore what the layout handed it.
    Pre-V3 this could not even be expressed — the old row had no state-invariant
    layout call, and the selected row re-rendered every cell through
    ``_on_selection``, which flipped ``is_chip`` and therefore changed widths.
    """
    _model, index = _index()
    states = {
        "rest": paint_channel_row(delegate, index, rect=ROW),
        "selected": paint_channel_row(delegate, index, rect=ROW, selected=True),
        "hovered": paint_channel_row(delegate, index, rect=ROW, hovered=True),
        "both": paint_channel_row(delegate, index, rect=ROW, selected=True, hovered=True),
    }
    baseline = states["rest"]
    baseline_rects = {t: baseline.rect_of(t)
                      for t in [txt for _, txt, _, _ in baseline.texts]
                      + [c.text for _, c in baseline.cells]}
    assert baseline_rects, "the baseline row painted nothing — harness is broken"
    for name, painted in states.items():
        for text, rect in baseline_rects.items():
            assert painted.rect_of(text) == rect, (
                f"{text!r} moved from {rect} to {painted.rect_of(text)} in state {name!r}"
            )


def test_row_layout_cannot_take_a_state_argument(delegate):
    """``row_layout`` is the single geometry chokepoint, and it accepts no
    selection/hover/current parameter — the invariant above is structural, not
    a convention someone has to remember.

    A guard on the SIGNATURE, deliberately: a future edit that threads state in
    would keep every geometry test above green right up until the first caller
    passed a different value.
    """
    import inspect

    params = set(inspect.signature(layout.row_layout).parameters)
    forbidden = {"selected", "hovered", "current", "state", "option", "opt"}
    assert not (params & forbidden), (
        f"row_layout grew a state parameter: {sorted(params & forbidden)}"
    )


def test_action_gutter_is_reserved_even_when_nothing_is_painted_in_it(delegate):
    """Reserve what is always true. Every row can be acted on, so the gutter is
    subtracted from the content box on EVERY row — including one that is not
    hovered and therefore paints no affordance."""
    _model, index = _index()
    box = layout.row_layout(ROW, has_art=True, art_square=False, rail_w=0)
    resting = paint_channel_row(delegate, index, rect=ROW)
    for text, _cell in [(c.text, c) for _, c in resting.cells]:
        assert resting.rect_of(text).right() < box.action.left(), (
            f"{text!r} was painted under the reserved action gutter"
        )


def test_action_affordance_paints_only_on_hover_or_current(delegate, qapp):
    """…and is INVISIBLE at rest. A resting list of a hundred rows is not a
    hundred buttons."""
    _model, index = _index()
    box = layout.row_layout(ROW, has_art=True, art_square=False, rail_w=0)
    probe = box.action.center()

    at_rest = render_channel_row(delegate, index, rect=ROW)
    on_hover = render_channel_row(delegate, index, rect=ROW, hovered=True)
    on_current = render_channel_row(delegate, index, rect=ROW, selected=True)

    ground = QColor(_theme.COLOR_BG_DEEP).rgb()
    assert at_rest.pixel(probe.x(), probe.y()) == ground, (
        "the action affordance painted on a row that is neither hovered nor current"
    )
    assert on_hover.pixel(probe.x(), probe.y()) != ground
    assert on_current.pixel(probe.x(), probe.y()) != ground


# ---------------------------------------------------------------------------
# Rule 2 — kind is structural.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("kind,word", [("movie", "Movie"), ("series", "Series"),
                                      ("live", "Live")])
def test_kind_is_never_repeated_as_a_word(delegate, kind, word):
    """The mark states the kind; the meta line must not state it again.

    The V3 design called for the kind as the meta line's first word. Against the
    real library that rendered as "Movie · … / Movie · … / Movie · …" straight
    down a filtered list — a column of one repeated word occupying the meta
    line's most valuable position, next to an icon that had already said it
    (owner report, 2026-08-23). Kind is still structural; it is just not
    structural twice.
    """
    _model, index = _index(MEDIA_KIND_ROLE=kind)
    painted = paint_channel_row(delegate, index, rect=ROW)
    drawn = {t for _, t, _, _ in painted.texts} | {c.text for _, c in painted.cells}
    assert word not in drawn, f"the row spelled out {word!r} next to its own mark"


def test_the_meta_line_leads_with_the_first_fact_the_mark_cannot_give(delegate):
    """…and with the kind word gone, the year leads."""
    _model, index = _index()
    painted = paint_channel_row(delegate, index, rect=ROW)
    segments = sorted((rect.left(), c.text) for rect, c in painted.cells if not c.is_chip)
    assert segments[0][1] == "2024"


def test_live_gets_a_square_tile_and_vod_gets_a_poster(delegate):
    """A live channel's logo is a square asset; letterboxing it into a 2:3 well
    would waste the row's height to say nothing. The shapes are DIFFERENT, and
    the poster is the taller of the two."""
    live = layout.row_layout(ROW, has_art=True, art_square=True, rail_w=0).art
    vod = layout.row_layout(ROW, has_art=True, art_square=False, rail_w=0).art
    assert live.width() == live.height(), "the live tile is not square"
    assert vod.height() > vod.width(), "the poster well is not portrait"
    assert vod.height() > live.height()
    assert live.left() == vod.left(), "the two shapes must start in the same column"


def test_kind_mark_is_reserved_on_every_row_including_compact(delegate):
    """Artwork is optional (a density and a setting turn it off); the kind mark
    is not. The text column therefore never starts at the row's own left edge."""
    for density in (d.DENSITY_COMPACT, d.DENSITY_COMFY):
        for has_art in (False, True):
            box = layout.row_layout(ROW, has_art=has_art, art_square=False, rail_w=0)
            assert box.kind.width() > 0
            assert box.text.left() >= box.fill.left() + layout.KIND_GUTTER_W, (
                f"text overlapped the kind gutter (density={density}, art={has_art})"
            )


def test_live_kind_mark_is_the_accent_and_vod_is_not(delegate, qapp):
    """Live is the one kind whose content is happening right now, and the one a
    reader scanning a mixed list needs to pick out. Colour is the SECOND cue —
    the three glyphs are different shapes first — so this is emphasis, not
    encoding."""
    from metatv.gui import icon_utils

    # A LIST per key, not one value: a live row paints its mark twice — once in
    # the gutter and once inside the placeholder tile — and keeping only the
    # last would silently assert the tile's colour instead of the mark's.
    seen: dict[str, list] = {}
    original = icon_utils.vector_pixmap

    def spy(key, color, size=16):
        seen.setdefault(key, []).append(color)
        return original(key, color, size)

    icon_utils.vector_pixmap = spy
    try:
        for kind in ("live", "movie", "series"):
            _model, index = _index(MEDIA_KIND_ROLE=kind)
            paint_channel_row(delegate, index, rect=ROW)
    finally:
        icon_utils.vector_pixmap = original

    from metatv.gui import icons as _icons

    accent = QColor(_theme.COLOR_ACCENT)
    live_colors = [QColor(c) for c in seen[_icons.vector_key("live")]]
    movie_colors = [QColor(c) for c in seen[_icons.vector_key("movie")]]
    assert accent in live_colors, f"the live mark never took the accent: {live_colors}"
    assert accent not in movie_colors, "a movie mark took the accent"


# ---------------------------------------------------------------------------
# Rule 3 — only render what exists.
# ---------------------------------------------------------------------------

def test_the_language_column_never_moves_when_quality_is_absent(delegate):
    """THE bug this arrangement exists to prevent, reported against the built
    row on 2026-08-23.

    Quality and the language badge shared a right-aligned rail. A right-aligned
    group is only stable if every member is always present — and quality is
    present on 6.6% of rows, so the language badge landed in one column on a 4K
    row and a different one on the row beneath it, jumping left and right down a
    scrolling list.

    Quality now paints against the TITLE, where its absence costs a few pixels
    of title box and nothing else.
    """
    _model, with_q = _index(QUALITY_TOKEN_ROLE="4K")
    _model2, without_q = _index(QUALITY_TOKEN_ROLE="")
    painted_with = paint_channel_row(delegate, with_q, rect=ROW)
    painted_without = paint_channel_row(delegate, without_q, rect=ROW)

    assert painted_with.rect_of("EN") == painted_without.rect_of("EN"), (
        "the language badge moved because this row happened to have a quality "
        "token — quality must not share a right-aligned group with it"
    )


def test_quality_paints_immediately_after_the_title_text(delegate):
    """Not after the title BOX, which runs all the way to the rail — offsetting
    by the box width parks the chip against the rail, where it reads as one more
    right-hand fact instead of a qualifier on this copy."""
    _model, index = _index(TITLE_ROLE="Fallout", QUALITY_TOKEN_ROLE="4K")
    painted = paint_channel_row(delegate, index, rect=QRect(0, 0, 900, 68))
    title_rect = painted.rect_of("Fallout")
    quality = painted.rect_of("4K")
    from PyQt6.QtGui import QFontMetrics

    title_font = next(f for _r, t, _c, f in painted.texts if t == "Fallout")
    text_end = title_rect.left() + QFontMetrics(title_font).horizontalAdvance("Fallout")
    assert quality.left() <= text_end + 2 * d._CELL_GAP, (
        f"quality drifted right: starts at {quality.left()}, title text ends at "
        f"{text_end}"
    )
    assert quality.left() < 900 // 2, "quality parked on the right half of the row"


def test_quality_is_rendered_not_reserved(delegate):
    """Quality exists on 6.6% of the library (live 26.2 / movie 3.3 /
    series 2.0). A row without it must give that space back to the title rather
    than hold an empty column implying every title has a claim to make."""
    _model, with_q = _index(QUALITY_TOKEN_ROLE="4K")
    _model2, without_q = _index(QUALITY_TOKEN_ROLE="")

    painted_with = paint_channel_row(delegate, with_q, rect=ROW)
    painted_without = paint_channel_row(delegate, without_q, rect=ROW)

    assert painted_with.cell("4K") is not None
    assert painted_without.cell("4K") is None
    title_with = painted_with.rect_of("The Murky Stream")
    title_without = painted_without.rect_of("The Murky Stream")
    assert title_without.width() > title_with.width(), (
        "dropping the quality chip did not give its space back to the title"
    )


def test_no_rating_is_ever_painted_in_a_row(delegate):
    """Ratings left the row entirely. They are not objective, and in this
    library the top of the range is a wall of identical 10.0s."""
    from metatv.gui import icons as _icons

    _model, index = _index()
    painted = paint_channel_row(delegate, index, rect=ROW)
    drawn = {t for _, t, _, _ in painted.texts} | {c.text for _, c in painted.cells}
    assert _icons.like_icon not in drawn
    assert _icons.dislike_icon not in drawn
    assert not hasattr(d, "CHIP_SLOT_RATING")


def test_absent_facts_leave_no_gap_in_the_meta_line(delegate):
    """A row with only a kind renders ``Live`` and stops — no stranded
    separators, no reserved slots."""
    _model, index = _index(MEDIA_KIND_ROLE="live", YEAR_ROLE="", GENRES_ROLE=(),
                           GENRE_ROLE="", COLLECTION_ROLE="", CATEGORY_ROLE="",
                           LANGUAGE_ROLE="", QUALITY_TOKEN_ROLE="",
                           PRIMARY_LANGUAGE_ROLE="")
    painted = paint_channel_row(delegate, index, rect=ROW)
    assert [c.text for _, c in painted.cells] == [], (
        "a row with no facts painted a meta segment anyway"
    )
    separators = [t for _, t, _, _ in painted.texts if t == d._META_SEPARATOR]
    assert separators == [], "a separator was painted with nothing after it"


def test_a_row_with_no_meta_line_centres_its_title(delegate):
    """…and it centres rather than sitting at the top of an empty two-line
    stack. The row's HEIGHT is unchanged — artwork and the density fix that —
    so a hanging title would just read as a rendering fault."""
    _model, bare = _index(YEAR_ROLE="", GENRES_ROLE=(), GENRE_ROLE="",
                          COLLECTION_ROLE="", CATEGORY_ROLE="", LANGUAGE_ROLE="")
    _model2, full = _index()
    bare_title = paint_channel_row(delegate, bare, rect=ROW).rect_of("The Murky Stream")
    full_title = paint_channel_row(delegate, full, rect=ROW).rect_of("The Murky Stream")
    assert bare_title.top() > full_title.top(), (
        "a title with no meta line beneath it did not drop to the row's centre"
    )
    assert abs(bare_title.center().y() - ROW.center().y()) <= 2


def test_meta_segments_are_separated_by_exactly_one_middle_dot(delegate):
    """``Movie · 2024 · KR · Drama / Thriller · Korean Drama`` — n segments, n-1
    separators, and the separator is U+00B7 rather than a bullet or a pipe."""
    _model, index = _index()
    painted = paint_channel_row(delegate, index, rect=ROW)
    # The meta line is tier 2 — tinted text, no box — so a boxed cell is by
    # definition a rail chip, not a segment. The companion assertion below
    # stops that filter from silently drifting if a segment ever grows a box.
    segments = [c for _, c in painted.cells if not c.is_chip]
    boxed = [c for _, c in painted.cells if c.is_chip]
    assert {c.text for c in boxed} == {"EN", "4K"}, (
        f"unexpected boxed cells: {[c.text for c in boxed]}"
    )
    separators = [t for _, t, _, _ in painted.texts if t == "·"]
    assert len(segments) >= 3
    assert len(separators) == len(segments) - 1
    assert d._META_SEPARATOR == "·"


def test_genres_paint_as_one_run_not_a_string_of_chips(delegate):
    """"Thriller / Drama" is one segment. Three separate cells would put three
    ``·`` separators inside one fact."""
    _model, index = _index(GENRES_ROLE=("Thriller", "Drama"))
    painted = paint_channel_row(delegate, index, rect=ROW)
    assert painted.cell("Thriller / Drama") is not None
    assert painted.cell("Thriller") is None


def test_genre_run_is_capped(delegate):
    """Past three, genres stop being scannable and start eating the title."""
    _model, index = _index(GENRES_ROLE=("A", "B", "C", "D", "E"))
    painted = paint_channel_row(delegate, index, rect=ROW)
    assert painted.cell("A / B / C") is not None


def test_a_long_title_elides_and_never_displaces_the_rail(delegate):
    """The title's box is bounded by ``row_layout``, so no title can push a chip
    out of the row — the failure the pre-#298 row shipped with."""
    long_title = "A Very Long Channel Name That Goes On Well Past The Available Width"
    _model, index = _index(TITLE_ROLE=long_title)
    painted = paint_channel_row(delegate, index, rect=ROW)
    quality = painted.rect_of("4K")
    assert quality.right() <= ROW.right()
    title_rect = next(r for r, t, _, _ in painted.texts if t.startswith("A Very Long"))
    assert title_rect.right() <= quality.left()
    drawn = next(t for _, t, _, _ in painted.texts if t.startswith("A Very Long"))
    assert drawn != long_title, "a title wider than its box was not elided"


# ---------------------------------------------------------------------------
# Chrome — the colours a real painter actually put down.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("palette_name", PALETTES)
def test_selected_and_hover_fills_are_distinguishable_from_each_other(delegate,
                                                                     palette_name, qapp):
    """Selection and hover must not be two shades of the same idea. Selection is
    an accent TINT, hover a neutral one — read off the painted pixel, not the
    token."""
    original = _theme.active_theme() if hasattr(_theme, "active_theme") else None
    _theme.apply_theme(palette_name)
    try:
        _model, index = _index()
        probe_x = ROW.width() // 2
        probe_y = ROW.height() // 2
        selected = render_channel_row(delegate, index, rect=ROW, selected=True)
        hovered = render_channel_row(delegate, index, rect=ROW, hovered=True)
        sel_px = QColor(selected.pixel(probe_x, probe_y))
        hov_px = QColor(hovered.pixel(probe_x, probe_y))
        assert sel_px != hov_px, f"{palette_name}: selection and hover paint the same fill"
        # Distinguishable, not merely different by one bit.
        delta = (abs(sel_px.red() - hov_px.red()) + abs(sel_px.green() - hov_px.green())
                 + abs(sel_px.blue() - hov_px.blue()))
        assert delta >= 20, f"{palette_name}: selection vs hover differ by only {delta}"
    finally:
        if original:
            _theme.apply_theme(original)


@pytest.mark.parametrize("palette_name", PALETTES)
def test_current_row_marker_bar_is_visible_against_its_own_fill(delegate, palette_name,
                                                               qapp):
    """The marker is the row's one unambiguous "this one", so it has to clear
    3:1 against the fill it sits on (WCAG 1.4.11, non-text contrast) — in
    Graphite the obvious choice (``primary.default``) measured 2.12:1 and had to
    be moved up the ramp."""
    palette = tp.PALETTES[palette_name]
    marker = palette["COLOR_ROW_MARKER"]
    fill = palette["COLOR_ROW_SELECTED_FILL"]
    assert _contrast(marker, fill) >= 3.0, (
        f"{palette_name}: marker {marker} on {fill} is "
        f"{_contrast(marker, fill):.2f}:1"
    )


@pytest.mark.parametrize("palette_name", PALETTES)
def test_every_row_foreground_clears_aa_on_all_three_row_surfaces(palette_name):
    """The row now has THREE backgrounds — the list surface, the selected tint
    and the hover tint. A foreground chosen against one of them is not evidence
    about the other two, which is precisely what shipped broken before: the old
    saturated selection had to flatten every cell to stay legible."""
    palette = tp.PALETTES[palette_name]
    surfaces = {
        "list": palette["COLOR_BG_DEEP"],
        "selected": palette["COLOR_ROW_SELECTED_FILL"],
        "hover": palette["COLOR_ROW_HOVER_FILL"],
    }
    foregrounds = {
        name: palette[name] for name in (
            "COLOR_ROW_TITLE", "COLOR_ROW_META", "COLOR_ROW_GENRE",
            "COLOR_ROW_REGION", "COLOR_ROW_PLATFORM", "COLOR_ROW_COLLECTION",
        )
    }
    failures = [
        f"{fg_name} on {surf_name} = {_contrast(fg, surf):.2f}:1"
        for surf_name, surf in surfaces.items()
        for fg_name, fg in foregrounds.items()
        if _contrast(fg, surf) < 4.5
    ]
    assert not failures, f"{palette_name}: {failures}"


@pytest.mark.parametrize("palette_name", PALETTES)
def test_language_chip_stays_visible_on_a_selected_row(palette_name):
    """``facet.language-fill`` and ``primary.container`` are both step 4 of
    adjacent hues and measure **1.0:1** against each other — the chip vanishes
    into the selected row. The fix is a stroke rather than dropping the fill,
    because dropping it would change the chip's WIDTH and break rule 1."""
    palette = tp.PALETTES[palette_name]
    fill = palette["COLOR_ROW_LANGUAGE_FILL"]
    selected = palette["COLOR_ROW_SELECTED_FILL"]
    if _contrast(fill, selected) >= 3.0:
        pytest.skip("this palette's chip fill is already distinguishable")
    stroke = palette["COLOR_ROW_LANGUAGE"]
    assert _contrast(stroke, selected) >= 3.0, (
        f"{palette_name}: the chip's rescue stroke {stroke} is only "
        f"{_contrast(stroke, selected):.2f}:1 on {selected}"
    )


def test_selected_language_chip_is_the_same_width_as_at_rest(delegate):
    """The stroke above must not change the cell's box — rule 1 again, and the
    reason the fix is a border rather than a fill swap."""
    _model, index = _index()
    at_rest = paint_channel_row(delegate, index, rect=ROW)
    selected = paint_channel_row(delegate, index, rect=ROW, selected=True)
    assert at_rest.rect_of("EN") == selected.rect_of("EN")
    assert selected.cell("EN").border, "the chip got no rescue stroke when selected"


# ---------------------------------------------------------------------------
# Type — the title has to lead.
# ---------------------------------------------------------------------------

def test_title_is_larger_and_heavier_than_the_meta_line(delegate):
    """Both, not either. Colour alone moves the title one Radix step; size and
    weight are what make it read as the row's subject at a glance.

    Asserted on the QFont handed to the painter, and on PIXEL size rather than
    point size — the row states its sizes from the FONT_* scale."""
    _model, index = _index()
    painted = paint_channel_row(delegate, index, rect=ROW)
    title_font = next(f for _, t, _, f in painted.texts if t == "The Murky Stream")
    sep_font = next(f for _, t, _, f in painted.texts if t == d._META_SEPARATOR)
    assert title_font.pixelSize() > sep_font.pixelSize()
    assert title_font.weight() > sep_font.weight()
    assert title_font.weight() >= QFont.Weight.DemiBold


def test_title_outcontrasts_everything_else_in_its_row(delegate):
    """The loudest thing in the row is the thing the reader is scanning for."""
    _model, index = _index()
    painted = paint_channel_row(delegate, index, rect=ROW)
    surface = _theme.COLOR_BG_DEEP
    title_color = next(c for _, t, c, _ in painted.texts if t == "The Murky Stream")
    title_contrast = _contrast(title_color, surface)
    for color in painted.all_foregrounds:
        if QColor(_to_hex(color)) == QColor(_to_hex(title_color)):
            continue
        assert _contrast(color, surface) <= title_contrast


# ---------------------------------------------------------------------------
# Density ladder.
# ---------------------------------------------------------------------------

def test_density_ladder_adds_lines_without_changing_the_grammar(delegate):
    """compact = title; comfy = + meta; comfy+ = + plot. Every density paints
    the same columns."""
    _model, index = _index(PLOT_ROLE="A stream runs through it.")
    counts = {}
    for density in (d.DENSITY_COMPACT, d.DENSITY_COMFY, d.DENSITY_COMFY_PLUS):
        painted = paint_channel_row(delegate, index, rect=QRect(0, 0, 620, 120),
                                    density=density)
        tops = {rect.top() for rect, _ in painted.cells}
        tops |= {rect.top() for rect, t, _, _ in painted.texts if t}
        counts[density] = len(tops)
    assert counts[d.DENSITY_COMPACT] < counts[d.DENSITY_COMFY]
    assert counts[d.DENSITY_COMFY] < counts[d.DENSITY_COMFY_PLUS]


def test_comfy_plus_without_a_plot_is_exactly_comfy(delegate):
    """A row with no plot renders two lines, not three with a gap in it."""
    _model, index = _index(PLOT_ROLE="")
    comfy = paint_channel_row(delegate, index, rect=ROW, density=d.DENSITY_COMFY)
    plus = paint_channel_row(delegate, index, rect=ROW, density=d.DENSITY_COMFY_PLUS)
    assert [(r, c.text) for r, c in comfy.cells] == [(r, c.text) for r, c in plus.cells]


def test_compact_reserves_no_artwork(delegate):
    """compact exists to fit more rows on screen."""
    _model, index = _index()
    tall = QRect(0, 0, 620, 120)
    compact_h = delegate.sizeHint(_row_opt(tall), index)
    delegate.set_density(d.DENSITY_COMPACT)
    compact = delegate.sizeHint(_row_opt(tall), index).height()
    delegate.set_density(d.DENSITY_COMFY)
    comfy = delegate.sizeHint(_row_opt(tall), index).height()
    assert compact < comfy
    assert compact < layout.ART_H


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _row_opt(rect):
    from PyQt6.QtWidgets import QStyleOptionViewItem

    opt = QStyleOptionViewItem()
    opt.rect = rect
    return opt


def _to_hex(value) -> str:
    return value.name() if isinstance(value, QColor) else str(value)


def _rgb(value) -> tuple[int, int, int, float]:
    import re

    text = _to_hex(value)
    match = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", text.strip())
    if match:
        return (int(match.group(1)), int(match.group(2)), int(match.group(3)),
                float(match.group(4)) if match.group(4) else 1.0)
    color = QColor(text)
    return (color.red(), color.green(), color.blue(), color.alphaF())


def _luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(fg, bg) -> float:
    """WCAG 2.1 contrast with *fg* COMPOSITED over *bg* — an alpha token
    measured as if opaque is a measurement of a colour nobody ever sees."""
    fr, fg_, fb, fa = _rgb(fg)
    br, bg_, bb, _ = _rgb(bg)
    over = (round(fr * fa + br * (1 - fa)),
            round(fg_ * fa + bg_ * (1 - fa)),
            round(fb * fa + bb * (1 - fa)))
    hi, lo = sorted((_luminance(over), _luminance((br, bg_, bb))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)
