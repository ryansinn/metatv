"""Behavioral tests for the comfy-row chip system unification (#257).

Owner report: the channel-list delegate painted its own chips on neutral
white-alpha backgrounds instead of the app's one canonical bordered-chip
idiom (``theme.LANG_CHIP``), and a row showed THREE chips for TWO facts
(platform prefix "A+", collection "APPLE+ SERIES", and the media-type icon).

Covers:

1. ``platform_display`` / ``collection_display`` (``channel_name_utils.py``)
   — the new display-layer chokepoints, modeled on ``quality_display``.
2. The delegate's chip PAINT BEHAVIOR (not just cell data) — proves the
   quality chip is genuinely outline-only (never a solid tier-colour fill)
   and the platform chip is genuinely a solid purple fill, by recording the
   actual QPainter operation sequence ``_paint_cell`` issues.
3. Facet-hue cell builders return the LANG_CHIP-idiom tinted fill (blue
   language / green region / teal genre) vs the two deliberately different
   treatments (solid purple platform, outline quality) vs the unchanged
   muted-grey collection chip.
4. Genre chip wiring end-to-end: ``ChannelListDTO.detected_genre`` ->
   ``GENRE_ROLE`` -> painted on comfy line 2, positioned before (left of) the
   collection chip, both flush right.
5. Settings round-trip for ``platform_name_style`` ("auto"/"full"/"short")
   through ``Config`` and the settings-dialog load/save helpers, mirroring
   ``test_channel_row_density.py``'s density round-trip tests.
6. The ``_to_qcolor`` colour-conversion chokepoint (review follow-up): a bare
   ``QColor(token)`` cannot parse the CSS ``rgba(...)`` strings
   ``theme_palettes.py``'s ``OVERLAY_*`` tokens use — it silently returns an
   INVALID colour that paints as opaque black. Proves the exact bug, proves
   the fix parses every token this delegate can paint into a VALID colour in
   all three palettes, and proves an actual ``_paint_cell`` call never hands
   the painter an invalid brush/pen.

Every test executes the changed path and asserts an outcome that would break
if the #257 chip-system logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import QComboBox

from metatv.core.channel_name_utils import (
    PLATFORM_CODES,
    REGION_FULL_NAMES,
    collection_display,
    platform_display,
)
from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import theme as _theme
from metatv.gui.badge_utils import _quality_colors, _quality_outline_colors
from metatv.gui.channel_list_delegate import DENSITY_COMFY, ChannelRowDelegate, _to_qcolor
from metatv.gui.channel_row_cells import (
    _category_cell,
    _genre_cell,
    _language_cell,
    _quality_cell,
    _region_or_platform_cell,
    _variant_badge_cell,
    _year_cell,
)
from metatv.gui.channel_list_model import GENRE_ROLE, ChannelListModel
from metatv.gui.settings_dialog import (
    _load_platform_name_style,
    _save_platform_name_style,
)
from metatv.gui.settings_dialog_tabs import _PLATFORM_NAME_STYLE_CHOICES


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# 1a. platform_display — the display-layer chokepoint for the platform chip
# ---------------------------------------------------------------------------

class TestPlatformDisplay:

    def test_short_style_returns_code_unchanged(self):
        assert platform_display("A+", "short") == "A+"
        assert platform_display("NF", "short") == "NF"

    def test_full_style_returns_friendly_name(self):
        assert platform_display("A+", "full") == "Apple+"
        assert platform_display("NF", "full") == "Netflix"

    def test_unknown_code_falls_back_to_code_itself(self):
        assert platform_display("ZZZPLATFORM", "full") == "ZZZPLATFORM"

    def test_empty_code_returns_falsy_unchanged(self):
        assert platform_display("", "full") == ""
        assert platform_display(None, "full") is None

    def test_a_plus_is_a_recognized_platform_code(self):
        """Owner report: "A+" (Apple TV+) was already a documented streaming
        platform in REGION_FULL_NAMES but missing from PLATFORM_CODES, so it
        fell through to the plain region chip instead of the platform one."""
        assert "A+" in PLATFORM_CODES
        assert REGION_FULL_NAMES["A+"] == "Apple+"


# ---------------------------------------------------------------------------
# 1b. collection_display — trailing media-type strip + platform-dedup strip
# ---------------------------------------------------------------------------

class TestCollectionDisplay:

    def test_trailing_media_type_token_stripped(self):
        assert collection_display("APPLE+ SERIES") == "APPLE+"
        assert collection_display("4K MOVIES") == "4K"

    def test_series_mania_survives_intact(self):
        """Guard: whole-token-only trailing match — "MANIA" is not a media
        type, so the real collection name "SERIES MANIA" must NOT be
        damaged even though it CONTAINS the word "SERIES"."""
        assert collection_display("SERIES MANIA") == "SERIES MANIA"

    def test_platform_duplicate_leading_token_stripped(self):
        """"APPLE+ KIDS" with this row's own platform code "A+" -> "KIDS":
        "APPLE+" case-insensitively matches platform_display("A+", "full")."""
        assert collection_display("APPLE+ KIDS", "A+") == "KIDS"

    def test_no_platform_code_leaves_collection_whole(self):
        """"HINDU SUBS" has no platform prefix to dedupe against — stays whole."""
        assert collection_display("HINDU SUBS", None) == "HINDU SUBS"
        assert collection_display("HINDU SUBS") == "HINDU SUBS"

    def test_fully_redundant_collection_collapses_to_empty(self):
        """"APPLE+ SERIES" is BOTH a trailing media-type word AND (after
        stripping it) a pure platform-name duplicate — killing the "triple
        redundancy" the owner reported means the chip disappears entirely,
        since every token is already shown elsewhere on the row (platform
        chip + media-type icon)."""
        assert collection_display("APPLE+ SERIES", "A+") == ""

    def test_none_and_empty_input_passthrough(self):
        assert collection_display(None) is None
        assert collection_display("") == ""

    def test_platform_code_that_does_not_match_leaves_collection_whole(self):
        assert collection_display("HINDU SUBS", "NF") == "HINDU SUBS"


# ---------------------------------------------------------------------------
# 2. Chip PAINT BEHAVIOR — proves outline-vs-solid via the actual QPainter
#    call sequence _paint_cell issues, not just the _Cell dataclass fields.
# ---------------------------------------------------------------------------

class _RecordingPainter:
    """Records every call so a test can inspect the ACTUAL paint sequence —
    a stronger proof of rendered appearance than reading _Cell fields."""

    def __init__(self):
        self.calls: list[tuple] = []

    def setFont(self, font):
        self.calls.append(("setFont", font))

    def setPen(self, pen):
        self.calls.append(("setPen", pen))

    def setBrush(self, brush):
        self.calls.append(("setBrush", brush))

    def drawRoundedRect(self, rect, rx, ry):
        self.calls.append(("drawRoundedRect", QRect(rect), rx, ry))

    def drawText(self, rect, alignment, text):
        self.calls.append(("drawText", QRect(rect), alignment, text))


def _brush_color_names(painter: _RecordingPainter) -> list[str]:
    names = []
    for op, *args in painter.calls:
        if op == "setBrush" and isinstance(args[0], QColor):
            names.append(args[0].name())
    return names


class TestChipPaintBehavior:

    def test_quality_chip_never_paints_a_solid_tier_colour_fill(self, qapp):
        """The pre-#257 quality chip painted a tier colour as a SOLID BRUSH
        FILL. The outline-only rewrite must never do that — the OLD solid-fill
        tier colour (``_quality_colors()``, still used unchanged by
        ``badge_utils.make_quality_chip`` elsewhere) may not appear as a
        filled brush on this chip at all."""
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _quality_cell("4K")
        assert cell is not None
        assert cell.outline is True

        delegate._paint_cell(painter, QRect(0, 0, 40, 20), cell, QFont())

        solid_fill_tier_color = QColor(_quality_colors()["4K"]).name()
        filled_colors = _brush_color_names(painter)
        assert solid_fill_tier_color not in filled_colors, (
            f"quality chip painted the solid-fill tier colour "
            f"{solid_fill_tier_color!r} as a brush fill {filled_colors!r} — "
            "it must be outline-only (#257)"
        )

    def test_quality_chip_border_and_text_use_the_outline_tier_colour(self, qapp):
        """The outline chip's pen (border + text) uses the DEDICATED
        ``_quality_outline_colors()`` family (contrast-tuned per palette),
        never the solid-fill ``_quality_colors()`` family."""
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _quality_cell("HD")
        delegate._paint_cell(painter, QRect(0, 0, 40, 20), cell, QFont())

        outline_tier_color = QColor(_quality_outline_colors()["HD"]).name()
        pen_colors = [
            args[0].name() for op, *args in painter.calls
            if op == "setPen" and isinstance(args[0], QColor)
        ]
        assert outline_tier_color in pen_colors, (
            "quality chip's border/text pen must use the outline tier colour"
        )

    def test_platform_paints_no_fill_at_all(self, qapp):
        """Platform is TIER 2 (#298): hue-tinted text, no box.

        It used to be a solid purple fill — the single loudest treatment in the
        row, for a fact almost nobody scans by. Asserted on what the painter
        actually does, not on the cell's fields: a cell can claim
        ``is_chip=False`` and still get a fill painted if the paint branch
        disagrees with it.
        """
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _region_or_platform_cell("A+", "full")
        assert cell is not None
        assert cell.is_chip is False
        assert cell.bg is None
        assert cell.fg == _theme.COLOR_ROW_PLATFORM

        delegate._paint_cell(painter, QRect(0, 0, 60, 20), cell, QFont())

        assert not _brush_color_names(painter), (
            "platform must paint NO fill — tier 2 is tinted text with no box"
        )

    def test_region_is_tinted_text_in_its_own_hue(self, qapp):
        cell = _region_or_platform_cell("US", "full")
        assert cell is not None
        assert cell.is_chip is False
        assert cell.bg is None
        assert cell.fg == _theme.COLOR_ROW_REGION
        assert cell.outline is False
        # The hue is the only thing still carrying the facet encoding once the
        # box is gone, so region and platform sharing one would erase the
        # distinction entirely rather than merely weaken it.
        assert QColor(_theme.COLOR_ROW_REGION).name() != QColor(_theme.COLOR_ROW_PLATFORM).name()


# ---------------------------------------------------------------------------
# 3. Facet-hue cell builders — LANG_CHIP-idiom tinted fill per facet
# ---------------------------------------------------------------------------

class TestFacetHueCellBuilders:

    def test_language_is_the_only_facet_carrying_a_fill(self, qapp):
        """TIER 1 is language and row state, nothing else (#298 owner call:
        language is the highest-value facet after the title).

        The "only" half is what makes this worth asserting — a test that just
        checked language's own two tokens would still pass on the seven-fill
        row this redesign exists to replace.
        """
        language = _language_cell("DE")
        assert language.is_chip is True
        assert language.bg == _theme.COLOR_ROW_LANGUAGE_FILL
        assert language.fg == _theme.COLOR_ROW_LANGUAGE
        assert language.outline is False

        for other in (_region_or_platform_cell("US", "full"),
                      _region_or_platform_cell("A+", "full"),
                      _genre_cell("Action"),
                      _category_cell("Some Collection"),
                      _year_cell("2024"),
                      _quality_cell("4K"),
                      _variant_badge_cell(3)):
            assert other is not None
            assert other.bg is None, (
                f"{other.text!r} carries a fill — tier 1 is language and state only"
            )

    def test_genre_is_tinted_text_in_its_own_hue(self, qapp):
        cell = _genre_cell("Action")
        assert cell is not None
        assert cell.is_chip is False
        assert cell.bg is None
        assert cell.fg == _theme.COLOR_ROW_GENRE
        assert cell.outline is False

    def test_genre_cell_none_for_empty(self, qapp):
        assert _genre_cell("") is None
        assert _genre_cell(None) is None

    def test_collection_is_neutral_text_not_a_borrowed_facet_hue(self, qapp):
        """Collection is tier 2 but NEUTRAL — the palette publishes one hue per
        facet and no two may share one, so a hue here would have to be borrowed
        from a facet that already means something else. Its TEXT is still
        transformed by collection_display."""
        cell = _category_cell("APPLE+ KIDS", "A+")
        assert cell.text == "KIDS"
        assert cell.is_chip is False
        assert cell.bg is None
        assert cell.fg == _theme.COLOR_ROW_COLLECTION
        assert cell.outline is False
        for facet_token in (_theme.COLOR_ROW_LANGUAGE, _theme.COLOR_ROW_REGION,
                            _theme.COLOR_ROW_GENRE, _theme.COLOR_ROW_PLATFORM):
            assert QColor(cell.fg).name() != QColor(facet_token).name()

    def test_collection_chip_omitted_when_fully_redundant(self, qapp):
        assert _category_cell("APPLE+ SERIES", "A+") is None


# ---------------------------------------------------------------------------
# 4. Genre chip wiring end-to-end + rendered geometry (before collection,
#    both flush right)
# ---------------------------------------------------------------------------

def _dto(**overrides) -> ChannelListDTO:
    base = {
        "id": str(uuid.uuid4()),
        "name": "Channel",
        "media_type": "movie",
        "provider_id": "p1",
        "is_favorite": False,
        "category": None,
        "quality": None,
        "detected_prefix": "EN",
        "detected_region": "A+",
        "detected_quality": "4K",
        "detected_year": "2024",
        "detected_title": "Some Show",
        "user_rating": 0,
        "detected_collection": "APPLE+ KIDS",
        "detected_genre": "Comedy",
    }
    base.update(overrides)
    return ChannelListDTO(**base)


def _model(dtos) -> ChannelListModel:
    model = ChannelListModel()
    model.set_channels(
        dtos,
        provider_icon_map={},
        show_provider_icon=False,
        has_more=False,
        query_params={},
        favorite_icon="",
        unfavorite_icon="",
        get_media_type_icon=lambda mt: "",
    )
    return model


class TestGenreRoleWiring:

    def test_dto_from_orm_carries_detected_genre(self):
        fake_channel = SimpleNamespace(
            id="c1", name="Show", media_type="movie", provider_id="p1",
            is_favorite=False, category=None, quality=None,
            detected_prefix=None, detected_region=None, detected_quality=None,
            detected_year=None, detected_title=None,
            detected_collection=None, detected_collection_language=None,
            detected_collection_subdub=None, detected_genre="Drama",
        )
        dto = ChannelListDTO.from_orm(fake_channel)
        assert dto.detected_genre == "Drama"

    def test_model_returns_detected_genre_for_genre_role(self, qapp):
        model = _model([_dto(detected_genre="Documentary")])
        idx = model.index(0)
        assert model.data(idx, GENRE_ROLE) == "Documentary"

    def test_model_returns_empty_string_for_missing_genre(self, qapp):
        model = _model([_dto(detected_genre=None)])
        idx = model.index(0)
        assert model.data(idx, GENRE_ROLE) == ""

    def test_meta_line_paints_genre_before_collection(self, qapp):
        """Taxonomy order (#257 Part C) survived the V3 rewrite: the genres read
        first, the collection is the fallback fact after them.

        The line they share moved — there is no separate badge row any more —
        so this drives the real ``paint()`` and reads the painted x, which is
        the only thing that can tell "before" from "declared first".
        """
        from tests.conftest import paint_channel_row, row_model

        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMFY)
        model = row_model(GENRES_ROLE=("Comedy",), GENRE_ROLE="Comedy",
                          COLLECTION_ROLE="APPLE+ KIDS", CATEGORY_ROLE="APPLE+ KIDS",
                          LANGUAGE_ROLE="A+")
        painted = paint_channel_row(delegate, model.index(0), rect=QRect(0, 0, 600, 68))

        rects_by_text = {c.text: r for r, c in painted.cells}
        # detected_collection "APPLE+ KIDS" with own platform "A+" renders as "KIDS".
        assert "Comedy" in rects_by_text, "genre was never painted"
        assert "KIDS" in rects_by_text, "collection was never painted"
        assert rects_by_text["Comedy"].left() < rects_by_text["KIDS"].left()
        assert rects_by_text["Comedy"].top() == rects_by_text["KIDS"].top(), (
            "genre and collection belong to the same meta line"
        )

    def test_meta_line_omits_genre_when_absent(self, qapp):
        from tests.conftest import paint_channel_row, row_model

        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMFY)
        model = row_model(GENRES_ROLE=(), GENRE_ROLE="",
                          COLLECTION_ROLE="APPLE+ KIDS", CATEGORY_ROLE="APPLE+ KIDS",
                          LANGUAGE_ROLE="A+")
        painted = paint_channel_row(delegate, model.index(0), rect=QRect(0, 0, 600, 68))
        texts = {c.text for _, c in painted.cells}
        assert "KIDS" in texts
        assert "Comedy" not in texts


# ---------------------------------------------------------------------------
# 5. Platform-names style: "auto" density resolution + Settings round-trip
# ---------------------------------------------------------------------------

class TestPlatformNameStyleResolution:

    def test_auto_resolves_full_in_comfy(self, qapp):
        delegate = ChannelRowDelegate()  # defaults to comfy density
        assert delegate.platform_name_style == "auto"
        assert delegate._effective_platform_style() == "full"

    def test_auto_resolves_short_in_compact(self, qapp):
        from metatv.gui.channel_list_delegate import DENSITY_COMPACT
        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMPACT)
        assert delegate._effective_platform_style() == "short"

    def test_explicit_short_style_wins_regardless_of_density(self, qapp):
        delegate = ChannelRowDelegate()  # comfy density
        delegate.set_platform_name_style("short")
        assert delegate._effective_platform_style() == "short"

    def test_explicit_full_style_wins_in_compact(self, qapp):
        from metatv.gui.channel_list_delegate import DENSITY_COMPACT
        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMPACT)
        delegate.set_platform_name_style("full")
        assert delegate._effective_platform_style() == "full"

    def test_unknown_style_falls_back_to_auto(self, qapp):
        delegate = ChannelRowDelegate()
        delegate.set_platform_name_style("not-a-real-style")
        assert delegate.platform_name_style == "auto"

    def test_platform_text_changes_with_effective_style(self, qapp):
        """End-to-end: the SAME channel reads "Apple+" under the full style and
        "A+" under the short one, in the row that actually shows it.

        Both cases are driven on a COMFY row rather than one of each density.
        V3's compact row is the title line alone — it carries no meta line, so
        it shows no platform at all, and asserting the short style there would
        be asserting the absence of the thing under test.
        """
        from tests.conftest import paint_channel_row, row_model

        model = row_model(LANGUAGE_ROLE="A+")

        def _texts(style):
            delegate = ChannelRowDelegate()
            delegate.set_density(DENSITY_COMFY)
            delegate.set_platform_name_style(style)
            painted = paint_channel_row(delegate, model.index(0),
                                        rect=QRect(0, 0, 600, 68))
            return {c.text for _, c in painted.cells}

        assert "Apple+" in _texts("full")
        assert "A+" in _texts("short")

    def test_compact_carries_no_meta_line(self, qapp):
        """The other half of the statement above, asserted rather than assumed:
        compact exists to fit more rows on screen, so it drops the meta line
        entirely instead of shrinking it."""
        from metatv.gui.channel_list_delegate import DENSITY_COMPACT
        from tests.conftest import paint_channel_row, row_model

        delegate = ChannelRowDelegate()
        delegate.set_density(DENSITY_COMPACT)
        model = row_model(LANGUAGE_ROLE="A+")
        painted = paint_channel_row(delegate, model.index(0), rect=QRect(0, 0, 600, 30))
        texts = {c.text for _, c in painted.cells}
        assert "Apple+" not in texts and "A+" not in texts
        assert "Movie" not in texts, "compact painted a kind word — that is the meta line"
        # …but the language and quality chips stay: they are the rail, not the
        # meta line, and the rail is what compact keeps.
        assert "EN" in texts


class TestPlatformNameStyleConfigAndSettings:

    def test_config_default_is_auto(self):
        cfg, _ = Config.load()
        assert cfg.platform_name_style == "auto"

    def test_config_persists_through_save_and_reload(self):
        cfg, _ = Config.load()
        cfg.platform_name_style = "short"
        cfg.save()

        reloaded, _ = Config.load()
        assert reloaded.platform_name_style == "short"

    def test_settings_dialog_helpers_round_trip(self, qapp):
        combo = QComboBox()
        for label, value in _PLATFORM_NAME_STYLE_CHOICES:
            combo.addItem(label, value)
        cfg = SimpleNamespace(platform_name_style="full")

        _load_platform_name_style(combo, cfg)
        assert combo.currentData() == "full"

        combo.setCurrentIndex(combo.findData("short"))
        _save_platform_name_style(combo, cfg)
        assert cfg.platform_name_style == "short"

    def test_settings_dialog_helpers_unknown_falls_back_to_auto(self, qapp):
        combo = QComboBox()
        for label, value in _PLATFORM_NAME_STYLE_CHOICES:
            combo.addItem(label, value)
        cfg = SimpleNamespace(platform_name_style="not-a-real-style")

        _load_platform_name_style(combo, cfg)
        assert combo.currentData() == "auto"


# ---------------------------------------------------------------------------
# 6. _to_qcolor colour-conversion chokepoint (review follow-up)
#
# QColor(token) cannot parse the CSS rgba(r,g,b,a) strings theme_palettes.py's
# OVERLAY_* tokens use — it silently returns an INVALID colour that paints as
# opaque black, alpha 255. Every chip whose background read an OVERLAY_*
# token (language/region/genre/collection, and the outline quality chip's
# own subtle tint) was painting a solid black box instead of the intended
# translucent tint. _to_qcolor is the single chokepoint every colour this
# delegate paints must route through instead.
# ---------------------------------------------------------------------------

class TestColorConversionChokepoint:

    def test_bare_qcolor_of_an_overlay_token_is_the_bug(self, qapp):
        """Documents the underlying platform behaviour _to_qcolor exists to
        work around: a bare QColor(rgba_token) is INVALID and paints black."""
        for token in ("rgba(255,255,255,0.15)", "rgba(60,120,180,0.5)", "rgba(0,0,0,0.08)"):
            bare = QColor(token)
            assert not bare.isValid(), (
                f"expected a bare QColor({token!r}) to be invalid (the bug this "
                "chokepoint fixes) — if this now passes, PyQt6 added rgba() "
                "parsing and _to_qcolor's manual parse may be redundant"
            )
            assert bare.name() == "#000000"

    def test_to_qcolor_parses_rgba_tokens_into_the_correct_valid_colour(self, qapp):
        cases = [
            ("rgba(255,255,255,0.15)", (255, 255, 255)),
            ("rgba(60,120,180,0.5)", (60, 120, 180)),
            ("rgba(68,136,255,0.15)", (68, 136, 255)),
            ("rgba(0,0,0,0.08)", (0, 0, 0)),  # legitimately black hue, but low alpha
        ]
        for token, expected_rgb in cases:
            color = _to_qcolor(token)
            assert color.isValid(), f"{token!r} produced an INVALID QColor"
            assert (color.red(), color.green(), color.blue()) == expected_rgb, (
                f"{token!r} resolved to "
                f"{(color.red(), color.green(), color.blue())}, expected "
                f"{expected_rgb}"
            )

    def test_to_qcolor_preserves_alpha_from_rgba(self, qapp):
        color = _to_qcolor("rgba(60,120,180,0.5)")
        assert color.alpha() == pytest.approx(round(0.5 * 255), abs=1)

    def test_to_qcolor_handles_hex_and_named_colours(self, qapp):
        assert _to_qcolor("#7755cc").isValid()
        assert _to_qcolor("#7755cc").name() == "#7755cc"
        assert _to_qcolor("gold").isValid()

    def test_to_qcolor_passes_through_an_existing_qcolor(self, qapp):
        original = QColor("#123456")
        assert _to_qcolor(original) is original

    def test_to_qcolor_empty_input_is_invalid_not_a_crash(self, qapp):
        assert _to_qcolor(None).isValid() is False
        assert _to_qcolor("").isValid() is False

    @pytest.mark.parametrize("palette_name", ["Midnight", "Graphite", "Daylight"])
    def test_every_delegate_paintable_token_is_valid_every_palette(self, qapp, palette_name):
        """The regression test that would have caught the rgba()-parsing bug
        before it shipped: every colour value the delegate's cell builders
        can hand to _paint_cell/_draw_text must resolve to a VALID QColor,
        in every palette — not just measured/equal, but genuinely paintable."""
        from metatv.gui import theme

        theme.apply_theme(palette_name)
        try:
            cells = [
                _year_cell("2024"),
                _quality_cell("4K"), _quality_cell("HD"), _quality_cell("RAW"),
                _quality_cell("LIVE"), _quality_cell("SD"), _quality_cell("LQ"),
                _region_or_platform_cell("US", "full"),
                _region_or_platform_cell("A+", "full"),
                _language_cell("DE"),
                _genre_cell("Action"),
                _category_cell("Some Collection"),
                _variant_badge_cell(3),
            ]
            tokens: dict[str, object] = {}
            for cell in cells:
                assert cell is not None
                tokens[cell.fg] = cell
                if cell.bg:
                    tokens[cell.bg] = cell
            # Thumbnail placeholder + playback-glyph tokens — painted
            # directly from theme.* constants, not carried by a _Cell.
            for extra in (
                _theme.COLOR_FAINT, _theme.COLOR_MUTED,
                _theme.COLOR_PLAYBACK_IN_PROGRESS, _theme.COLOR_PLAYBACK_WATCHED,
            ):
                tokens[extra] = "thumbnail/playback"

            invalid = {tok: _to_qcolor(tok) for tok in tokens if not _to_qcolor(tok).isValid()}
            assert not invalid, (
                f"{palette_name}: these delegate-paintable tokens produced an "
                f"INVALID QColor (paints as opaque black): {list(invalid)}"
            )
        finally:
            theme.apply_theme("Midnight")

    def test_paint_cell_never_hands_the_painter_an_invalid_colour(self, qapp):
        """Ties the token-level check to the REAL paint path: run actual
        _paint_cell calls through a recording painter and assert every
        QColor it received (brush or pen) is valid."""
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()

        for cell in (
            _quality_cell("4K"),
            _region_or_platform_cell("A+", "full"),
            _region_or_platform_cell("US", "full"),
            _language_cell("DE"),
            _genre_cell("Action"),
            _category_cell("Some Collection"),
        ):
            delegate._paint_cell(painter, QRect(0, 0, 60, 20), cell, QFont())

        invalid_calls = [
            (op, args[0]) for op, *args in painter.calls
            if op in ("setBrush", "setPen") and isinstance(args[0], QColor)
            and not args[0].isValid()
        ]
        assert not invalid_calls, (
            f"_paint_cell handed the painter an INVALID colour: {invalid_calls}"
        )
