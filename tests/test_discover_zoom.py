"""Behavioral tests for the Discover card zoom slider (D-zoom).

Covers:
- card_metrics() returns correctly scaled dims and clamps out-of-range values.
- _ContentCard built with a zoomed config has the expected fixed size.
- _Shelf._size_card_row() at zoom 1.5 uses the zoomed card width in its math
  (proves card + shelf stay in sync via the shared card_metrics() helper).
- theme.zoomed_font() returns a QFont with pixel size = round(base_px * zoom).
- Slider apply slot saves config and triggers in-place rebuild (no DB re-query).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_card(i: int = 0):
    from metatv.core.discovery_engine import ContentCard
    return ContentCard(
        channel_id=f"ch-{i}",
        title=f"Title {i}",
        media_type="movie",
        thumbnail_url=None,
        rating=7.5,
        year=2020,
        genre="Test",
    )


def _make_image_cache():
    ic = MagicMock()
    ic.get_image_async = MagicMock()
    return ic


def _make_config(zoom: float = 1.0):
    from metatv.core.config import Config
    cfg = Config()
    cfg.discover_zoom = zoom
    return cfg


# ---------------------------------------------------------------------------
# card_metrics() — dimensions and clamping
# ---------------------------------------------------------------------------

class TestCardMetrics:
    """card_metrics() returns correctly scaled and clamped dimensions."""

    def test_unit_zoom_returns_base_dims(self):
        from metatv.gui.discover_card import card_metrics, _CARD_W, _CARD_H, _POSTER_H
        m = card_metrics(1.0)
        assert m.card_w == _CARD_W
        assert m.card_h == _CARD_H
        assert m.poster_h == _POSTER_H

    def test_zoom_1_5_scales_correctly(self):
        from metatv.gui.discover_card import card_metrics, _CARD_W, _CARD_H, _POSTER_H
        z = 1.5
        m = card_metrics(z)
        assert m.card_w == round(_CARD_W * z)
        assert m.card_h == round(_CARD_H * z)
        assert m.poster_h == round(_POSTER_H * z)

    def test_zoom_0_8_scales_correctly(self):
        from metatv.gui.discover_card import card_metrics, _CARD_W, _CARD_H, _POSTER_H
        z = 0.8
        m = card_metrics(z)
        assert m.card_w == round(_CARD_W * z)
        assert m.card_h == round(_CARD_H * z)
        assert m.poster_h == round(_POSTER_H * z)

    def test_below_min_clamped_to_0_6(self):
        from metatv.gui.discover_card import card_metrics, _CARD_W, _CARD_H, _POSTER_H
        m_low = card_metrics(0.1)
        m_min = card_metrics(0.6)
        assert m_low == m_min, (
            "zoom below 0.6 must clamp to 0.6 — "
            f"card_metrics(0.1)={m_low} != card_metrics(0.6)={m_min}"
        )

    def test_above_max_clamped_to_1_8(self):
        from metatv.gui.discover_card import card_metrics, _CARD_W, _CARD_H, _POSTER_H
        m_high = card_metrics(5.0)
        m_max = card_metrics(1.8)
        assert m_high == m_max, (
            "zoom above 1.8 must clamp to 1.8 — "
            f"card_metrics(5.0)={m_high} != card_metrics(1.8)={m_max}"
        )

    def test_metrics_are_integers(self):
        from metatv.gui.discover_card import card_metrics
        m = card_metrics(1.333)
        assert isinstance(m.card_w, int)
        assert isinstance(m.card_h, int)
        assert isinstance(m.poster_h, int)

    def test_different_zooms_give_different_results(self):
        from metatv.gui.discover_card import card_metrics
        m1 = card_metrics(1.0)
        m2 = card_metrics(1.5)
        assert m2.card_w > m1.card_w
        assert m2.card_h > m1.card_h


# ---------------------------------------------------------------------------
# _ContentCard — fixed size reflects zoom
# ---------------------------------------------------------------------------

class TestContentCardZoomedSize:
    """A _ContentCard built with a zoomed config has the correct fixed size."""

    def test_card_width_at_zoom_1_5(self, qapp):
        from metatv.gui.discover_card import _ContentCard, card_metrics
        cfg = _make_config(zoom=1.5)
        ic = _make_image_cache()
        card = _make_card()

        widget = _ContentCard(card, ic, cfg)
        m = card_metrics(1.5)

        assert widget.width() == m.card_w, (
            f"_ContentCard at zoom 1.5 must have width={m.card_w}, got {widget.width()}"
        )
        assert widget.height() == m.card_h, (
            f"_ContentCard at zoom 1.5 must have height={m.card_h}, got {widget.height()}"
        )

    def test_card_width_at_zoom_0_7(self, qapp):
        from metatv.gui.discover_card import _ContentCard, card_metrics
        cfg = _make_config(zoom=0.7)
        ic = _make_image_cache()
        card = _make_card()

        widget = _ContentCard(card, ic, cfg)
        m = card_metrics(0.7)

        assert widget.width() == m.card_w
        assert widget.height() == m.card_h

    def test_card_size_at_unit_zoom_matches_base_constants(self, qapp):
        from metatv.gui.discover_card import _ContentCard, _CARD_W, _CARD_H
        cfg = _make_config(zoom=1.0)
        ic = _make_image_cache()
        card = _make_card()

        widget = _ContentCard(card, ic, cfg)
        assert widget.width() == _CARD_W
        assert widget.height() == _CARD_H


# ---------------------------------------------------------------------------
# _Shelf._size_card_row() — card + shelf dimensions in sync
# ---------------------------------------------------------------------------

class TestShelfSizeCardRowZoom:
    """_Shelf uses card_metrics() so the row width matches the card width."""

    def test_size_card_row_uses_zoomed_card_width(self, qapp):
        """Inner widget width at zoom=1.5 must equal the deterministic math using card_metrics."""
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import card_metrics

        zoom = 1.5
        cfg = _make_config(zoom=zoom)
        ic = _make_image_cache()
        n = 4

        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)
        shelf.set_cards([_make_card(i) for i in range(n)], image_cache=ic, config=cfg)
        qapp.processEvents()

        m = card_metrics(zoom)
        margins = shelf._inner_layout.contentsMargins()
        spacing = shelf._inner_layout.spacing()
        expected_w = margins.left() + margins.right() + n * m.card_w + max(0, n - 1) * spacing

        actual_w = shelf._inner_widget.width()
        assert actual_w == expected_w, (
            f"inner widget width at zoom={zoom} should be {expected_w}px "
            f"(n={n}, card_w={m.card_w}), got {actual_w}px"
        )

    def test_shelf_inner_height_uses_zoomed_card_height(self, qapp):
        """Inner widget height must be card_metrics().card_h + 4 (not the bare constant)."""
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import card_metrics

        zoom = 1.5
        cfg = _make_config(zoom=zoom)
        ic = _make_image_cache()

        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)
        shelf.set_cards([_make_card(0)], image_cache=ic, config=cfg)
        qapp.processEvents()

        m = card_metrics(zoom)
        expected_h = m.card_h + 4
        actual_h = shelf._inner_widget.height()
        assert actual_h == expected_h, (
            f"inner widget height at zoom={zoom} should be {expected_h}px "
            f"(card_h={m.card_h}+4), got {actual_h}px"
        )

    def test_scroll_area_height_uses_zoomed_card_height(self, qapp):
        """Scroll area fixed height must be card_metrics().card_h + 16."""
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import card_metrics

        zoom = 1.5
        cfg = _make_config(zoom=zoom)
        ic = _make_image_cache()

        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)
        m = card_metrics(zoom)
        expected_h = m.card_h + 16
        actual_h = shelf._scroll_area.height()
        assert actual_h == expected_h, (
            f"scroll area height at zoom={zoom} should be {expected_h}px "
            f"(card_h={m.card_h}+16), got {actual_h}px"
        )

    def test_card_and_shelf_widths_stay_in_sync(self, qapp):
        """A single card's width must equal the card_w from card_metrics (same source)."""
        from metatv.gui.discover_card import _ContentCard, card_metrics
        from metatv.gui.discover_shelf import _Shelf

        zoom = 1.3
        cfg = _make_config(zoom=zoom)
        ic = _make_image_cache()

        card_widget = _ContentCard(_make_card(0), ic, cfg)
        m = card_metrics(zoom)
        assert card_widget.width() == m.card_w, (
            "_ContentCard width must match card_metrics().card_w — "
            "both must read the same source so shelf and card never diverge"
        )


# ---------------------------------------------------------------------------
# theme.zoomed_font() — pixel size equals round(base_px * zoom)
# ---------------------------------------------------------------------------

class TestZoomedFont:
    """zoomed_font() returns a QFont with correctly scaled pixel size."""

    def test_unit_zoom_gives_base_pixel_size(self, qapp):
        from metatv.gui import theme as _theme
        f = _theme.zoomed_font(_theme.FONT_MD, 1.0)
        base_px = int(_theme.FONT_MD.replace("px", ""))
        assert f.pixelSize() == base_px

    def test_double_zoom_doubles_pixel_size(self, qapp):
        from metatv.gui import theme as _theme
        f = _theme.zoomed_font(_theme.FONT_MD, 2.0)
        base_px = int(_theme.FONT_MD.replace("px", ""))
        assert f.pixelSize() == round(base_px * 2.0)

    def test_various_tokens_scale_correctly(self, qapp):
        from metatv.gui import theme as _theme
        zoom = 1.5
        for token in (_theme.FONT_XS, _theme.FONT_SM, _theme.FONT_MD, _theme.FONT_LG,
                      _theme.FONT_XL, _theme.FONT_ICON_LG):
            f = _theme.zoomed_font(token, zoom)
            base_px = int(token.replace("px", ""))
            expected = round(base_px * zoom)
            assert f.pixelSize() == expected, (
                f"zoomed_font({token!r}, {zoom}) should have pixelSize={expected}, "
                f"got {f.pixelSize()}"
            )

    def test_bold_flag_applied(self, qapp):
        from metatv.gui import theme as _theme
        f_bold = _theme.zoomed_font(_theme.FONT_MD, 1.0, bold=True)
        f_norm = _theme.zoomed_font(_theme.FONT_MD, 1.0, bold=False)
        assert f_bold.bold() is True
        assert f_norm.bold() is False

    def test_minimum_pixel_size_clamp(self, qapp):
        """Even at extreme low zoom the pixel size is at least 6px."""
        from metatv.gui import theme as _theme
        f = _theme.zoomed_font(_theme.FONT_XS, 0.01)
        assert f.pixelSize() >= 6


# ---------------------------------------------------------------------------
# Slider: apply slot saves config and triggers rebuild
# ---------------------------------------------------------------------------

def _make_discover_view(qapp, *, zoom: float = 1.0):
    """Construct a DiscoverView without a real DB / loader thread."""
    from metatv.core.config import Config
    from metatv.gui.discover_view import DiscoverView
    from PyQt6.QtWidgets import QWidget

    cfg = Config()
    cfg.discover_zoom = zoom
    ic = _make_image_cache()
    db = MagicMock()

    view = DiscoverView.__new__(DiscoverView)
    QWidget.__init__(view)
    view._db = db
    view._config = cfg
    view._image_cache = ic
    view._thread = None
    view._see_all_thread = None
    view._see_all_worker = None
    view._expand_thread = None
    view._expand_worker = None
    view._inflight_expand = None
    view._loaded = False
    view._shelf_data_cache = {}
    view._loaded_shelf_keys = set()
    view._shelf_widgets = {}
    view._shelf_zones = {}
    view._pending_collapsed = []
    view._batch_timer = None
    view._setup_ui()
    return view, cfg


class TestZoomSlider:
    """Slider interactions persist zoom and trigger in-place rebuild."""

    def test_slider_initialised_from_config(self, qapp):
        """Slider value on construction matches round(config.discover_zoom * 100)."""
        view, cfg = _make_discover_view(qapp, zoom=1.3)
        assert view._zoom_slider.value() == round(1.3 * 100)

    def test_apply_zoom_saves_config(self, qapp):
        """Calling _apply_zoom() persists the new zoom level to config."""
        from metatv.core.config import Config
        view, cfg = _make_discover_view(qapp, zoom=1.0)

        with patch.object(Config, "save") as mock_save:
            view._zoom_slider.setValue(150)
            view._apply_zoom()

            assert abs(cfg.discover_zoom - 1.5) < 0.005, (
                f"config.discover_zoom should be ~1.5 after apply, got {cfg.discover_zoom}"
            )
            mock_save.assert_called_once()

    def test_apply_zoom_noop_when_value_unchanged(self, qapp):
        """_apply_zoom is a no-op when the zoom hasn't meaningfully changed."""
        from metatv.core.config import Config
        view, cfg = _make_discover_view(qapp, zoom=1.0)

        with patch.object(Config, "save") as mock_save:
            view._zoom_slider.setValue(100)  # same as initial 1.0
            view._apply_zoom()
            mock_save.assert_not_called()

    def test_apply_zoom_clamps_below_min(self, qapp):
        """Slider at minimum (60) clamps zoom to >= 0.6."""
        from metatv.core.config import Config
        view, cfg = _make_discover_view(qapp, zoom=1.0)

        with patch.object(Config, "save"):
            view._zoom_slider.setValue(60)
            view._apply_zoom()
        assert cfg.discover_zoom >= 0.6

    def test_apply_zoom_clamps_above_max(self, qapp):
        """Slider at maximum (180) keeps zoom <= 1.8."""
        from metatv.core.config import Config
        view, cfg = _make_discover_view(qapp, zoom=1.0)

        with patch.object(Config, "save"):
            view._zoom_slider.setValue(180)
            view._apply_zoom()
        assert cfg.discover_zoom <= 1.8

    def test_apply_zoom_rebuilds_loaded_shelves(self, qapp):
        """After _apply_zoom, loaded shelves have card widgets sized to the new zoom."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import card_metrics
        from metatv.gui.discover_view import _ZONE_EXPANDED

        view, cfg = _make_discover_view(qapp, zoom=1.0)

        # Plant a loaded shelf with cached cards.
        n = 3
        cards = [_make_card(i) for i in range(n)]
        shelf = _Shelf("Drama", "genre:Drama", cards, view._image_cache, cfg, collapsed=False)
        shelf.wire(MagicMock(), MagicMock(), MagicMock())
        view._shelf_widgets["genre:Drama"] = shelf
        view._shelf_zones["genre:Drama"] = _ZONE_EXPANDED
        view._shelf_data_cache["genre:Drama"] = cards
        view._loaded_shelf_keys.add("genre:Drama")

        # Apply a new zoom level (suppress actual config.save file write).
        new_zoom = 1.5
        with patch.object(Config, "save"):
            view._zoom_slider.setValue(round(new_zoom * 100))
            view._apply_zoom()
        qapp.processEvents()

        m = card_metrics(new_zoom)
        # Each card widget in the shelf must now be the new card_w wide.
        for i, card_widget in enumerate(shelf._cards_widgets):
            assert card_widget.width() == m.card_w, (
                f"card[{i}] width after zoom={new_zoom} should be {m.card_w}, "
                f"got {card_widget.width()}"
            )

    def test_slider_tooltip_set(self, qapp):
        """The zoom slider has a tooltip."""
        view, _ = _make_discover_view(qapp)
        assert view._zoom_slider.toolTip() != "", "zoom slider must have a tooltip"
