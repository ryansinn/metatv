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

Every test executes the changed path and asserts an outcome that would break
if the #257 chip-system logic regressed — no shape/substring-only coverage.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

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
from metatv.gui.badge_utils import _quality_colors
from metatv.gui.channel_list_delegate import (
    ChannelRowDelegate,
    _category_cell,
    _genre_cell,
    _language_cell,
    _quality_cell,
    _region_or_platform_cell,
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
        """The pre-#257 quality chip painted _quality_colors()'s tier colour
        as a SOLID BRUSH FILL. The outline-only rewrite must never do that —
        the tier colour may only appear as the PEN (border/text), never as a
        filled brush."""
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _quality_cell("4K")
        assert cell is not None
        assert cell.outline is True

        delegate._paint_cell(painter, QRect(0, 0, 40, 20), cell, QFont())

        tier_color = QColor(_quality_colors()["4K"]).name()
        filled_colors = _brush_color_names(painter)
        assert tier_color not in filled_colors, (
            f"quality chip painted the tier colour {tier_color!r} as a SOLID "
            f"brush fill {filled_colors!r} — it must be outline-only (#257)"
        )

    def test_quality_chip_border_and_text_use_the_tier_colour(self, qapp):
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _quality_cell("HD")
        delegate._paint_cell(painter, QRect(0, 0, 40, 20), cell, QFont())

        tier_color = QColor(_quality_colors()["HD"]).name()
        pen_colors = [
            args[0].name() for op, *args in painter.calls
            if op == "setPen" and isinstance(args[0], QColor)
        ]
        assert tier_color in pen_colors, (
            "quality chip's border/text pen must use the tier colour"
        )

    def test_platform_chip_paints_a_solid_purple_fill(self, qapp):
        delegate = ChannelRowDelegate()
        painter = _RecordingPainter()
        cell = _region_or_platform_cell("A+", "full")
        assert cell is not None
        assert cell.outline is False

        delegate._paint_cell(painter, QRect(0, 0, 60, 20), cell, QFont())

        purple = QColor(_theme.COLOR_ACCENT_PURPLE).name()
        assert purple in _brush_color_names(painter), (
            "platform chip must paint a SOLID purple fill (#257 Part A)"
        )

    def test_region_chip_uses_green_tint_not_platform_purple(self, qapp):
        cell = _region_or_platform_cell("US", "full")
        assert cell is not None
        assert cell.bg == _theme.OVERLAY_GREEN_15
        assert cell.fg == _theme.COLOR_ACCENT_GREEN
        assert cell.outline is False


# ---------------------------------------------------------------------------
# 3. Facet-hue cell builders — LANG_CHIP-idiom tinted fill per facet
# ---------------------------------------------------------------------------

class TestFacetHueCellBuilders:

    def test_language_cell_is_blue_tint(self, qapp):
        cell = _language_cell("DE")
        assert cell.fg == _theme.COLOR_ACCENT_BLUE
        assert cell.bg == _theme.OVERLAY_BLUE_15
        assert cell.outline is False

    def test_genre_cell_is_teal_tint(self, qapp):
        cell = _genre_cell("Action")
        assert cell.fg == _theme.COLOR_ACCENT_TEAL
        assert cell.bg == _theme.OVERLAY_TEAL_15
        assert cell.outline is False

    def test_genre_cell_none_for_empty(self, qapp):
        assert _genre_cell("") is None
        assert _genre_cell(None) is None

    def test_collection_chip_colour_unchanged_muted_grey(self, qapp):
        """Owner call: collection stays EXACTLY as today — OVERLAY_08 +
        COLOR_MUTED — while its TEXT is transformed by collection_display."""
        cell = _category_cell("APPLE+ KIDS", "A+")
        assert cell.text == "KIDS"
        assert cell.fg == _theme.COLOR_MUTED
        assert cell.bg == _theme.OVERLAY_08
        assert cell.outline is False

    def test_collection_chip_omitted_when_fully_redundant(self, qapp):
        assert _category_cell("APPLE+ SERIES", "A+") is None


# ---------------------------------------------------------------------------
# 4. Genre chip wiring end-to-end + rendered geometry (before collection,
#    both flush right)
# ---------------------------------------------------------------------------

def _dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()),
        name="Channel",
        media_type="movie",
        provider_id="p1",
        is_favorite=False,
        category=None,
        quality=None,
        detected_prefix="EN",
        detected_region="A+",
        detected_quality="4K",
        detected_year="2024",
        detected_title="Some Show",
        user_rating=0,
        detected_collection="APPLE+ KIDS",
        detected_genre="Comedy",
    )
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

    def test_badge_line_paints_genre_before_collection_both_flush_right(self, qapp):
        model = _model([_dto()])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((QRect(rect), cell))

        with patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_badge_line(MagicMock(), line, idx, QFont())

        rects_by_text = {c.text: r for r, c in cell_calls}
        # detected_collection "APPLE+ KIDS" with own platform "A+" renders as "KIDS".
        assert "Comedy" in rects_by_text, "genre chip was never painted"
        assert "KIDS" in rects_by_text, "collection chip was never painted"

        genre_rect = rects_by_text["Comedy"]
        collection_rect = rects_by_text["KIDS"]
        assert genre_rect.left() < collection_rect.left(), (
            "genre must sit to the LEFT of collection (taxonomy group order, #257 Part C)"
        )
        assert collection_rect.right() == line.right(), "collection stays flush right"

    def test_badge_line_omits_genre_chip_when_absent(self, qapp):
        model = _model([_dto(detected_genre=None)])
        idx = model.index(0)
        delegate = ChannelRowDelegate()

        cell_calls = []

        def _capture_paint_cell(painter, rect, cell, font):
            cell_calls.append((QRect(rect), cell))

        with patch.object(delegate, "_paint_cell", side_effect=_capture_paint_cell):
            line = QRect(0, 0, 600, 20)
            delegate._paint_badge_line(MagicMock(), line, idx, QFont())

        texts = {c.text for _, c in cell_calls}
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

    def test_platform_chip_text_changes_with_effective_style(self, qapp):
        """End-to-end: a comfy row shows the full brand name, a compact row
        the short code, for the SAME channel."""
        from metatv.gui.channel_list_delegate import DENSITY_COMPACT

        model = _model([_dto(detected_region="A+")])
        idx = model.index(0)

        comfy_delegate = ChannelRowDelegate()
        cell_calls = []
        with patch.object(comfy_delegate, "_paint_cell",
                           side_effect=lambda p, r, c, f: cell_calls.append(c)), \
             patch.object(comfy_delegate, "_draw_text"):
            comfy_delegate._paint_title_year_line(
                MagicMock(), QRect(0, 0, 600, 20), idx, "#fff", QFont()
            )
        assert any(c.text == "Apple+" for c in cell_calls)

        compact_delegate = ChannelRowDelegate()
        compact_delegate.set_density(DENSITY_COMPACT)
        cell_calls2 = []
        with patch.object(compact_delegate, "_paint_cell",
                           side_effect=lambda p, r, c, f: cell_calls2.append(c)), \
             patch.object(compact_delegate, "_draw_text"):
            compact_delegate._paint_compact(
                MagicMock(), QRect(0, 0, 600, 20), idx, "#fff", QFont()
            )
        assert any(c.text == "A+" for c in cell_calls2)


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
