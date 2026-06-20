"""Behavioral tests for Discover-view layout bug fixes D1 and D3.

D1 — Cards render at correct width after lazy set_cards() (no smoosh).
D3 — collapse_btn is always the rightmost header control (stable expand target).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_card(i: int):
    from metatv.core.discovery_engine import ContentCard
    return ContentCard(
        channel_id=f"ch-{i}",
        title=f"Movie {i}",
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


# ---------------------------------------------------------------------------
# D1 — _size_card_row produces the correct deterministic width
# ---------------------------------------------------------------------------

class TestSetCardsInnerWidgetWidth:
    """D1: inner widget must be sized from fixed card dims, not sizeHint()."""

    def test_set_cards_inner_width_deterministic(self, qapp):
        """After set_cards(N) the inner widget width equals the exact math:
        margins.left + margins.right + N*_CARD_W + (N-1)*spacing.
        """
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import _CARD_W

        cfg = Config()
        ic = _make_image_cache()
        n = 5

        # Build header-only shelf (collapsed=False so we can inspect the row).
        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)

        shelf.set_cards([_make_card(i) for i in range(n)], image_cache=ic, config=cfg)
        qapp.processEvents()

        m = shelf._inner_layout.contentsMargins()
        spacing = shelf._inner_layout.spacing()
        expected_w = m.left() + m.right() + n * _CARD_W + max(0, n - 1) * spacing

        actual_w = shelf._inner_widget.width()
        assert actual_w == expected_w, (
            f"inner widget width after set_cards({n}) should be {expected_w}px "
            f"(margins {m.left()}+{m.right()}, {n}×{_CARD_W} + {n-1}×{spacing} spacing), "
            f"got {actual_w}px"
        )

    def test_eager_build_and_lazy_set_cards_agree(self, qapp):
        """Eager-built shelf and lazy set_cards() shelf produce identical widths."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()
        cards = [_make_card(i) for i in range(4)]

        # Eager shelf — cards supplied at construction time.
        shelf_eager = _Shelf("Eager", "genre:E", cards, ic, cfg, collapsed=False)
        qapp.processEvents()

        # Lazy shelf — cards added via set_cards().
        shelf_lazy = _Shelf("Lazy", "genre:L", [], ic, cfg, collapsed=False)
        shelf_lazy.set_cards(cards, image_cache=ic, config=cfg)
        qapp.processEvents()

        w_eager = shelf_eager._inner_widget.width()
        w_lazy = shelf_lazy._inner_widget.width()
        assert w_eager == w_lazy, (
            f"eager ({w_eager}px) and lazy ({w_lazy}px) shelves must produce "
            "identical inner widths for the same card count"
        )

    def test_set_cards_width_grows_with_card_count(self, qapp):
        """Inner widget grows proportionally as card count increases."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()

        shelf_3 = _Shelf("S3", "genre:S3", [], ic, cfg, collapsed=False)
        shelf_3.set_cards([_make_card(i) for i in range(3)], image_cache=ic, config=cfg)

        shelf_8 = _Shelf("S8", "genre:S8", [], ic, cfg, collapsed=False)
        shelf_8.set_cards([_make_card(i) for i in range(8)], image_cache=ic, config=cfg)

        w_3 = shelf_3._inner_widget.width()
        w_8 = shelf_8._inner_widget.width()
        assert w_8 > w_3, (
            f"8-card shelf ({w_8}px) must be wider than 3-card shelf ({w_3}px)"
        )

    def test_set_cards_not_smooshed(self, qapp):
        """Inner widget after set_cards must be at least _CARD_W wide (not smooshed)."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import _CARD_W

        cfg = Config()
        ic = _make_image_cache()

        shelf = _Shelf("Smoosh", "genre:Smoosh", [], ic, cfg, collapsed=False)
        shelf.set_cards([_make_card(0)], image_cache=ic, config=cfg)
        qapp.processEvents()

        w = shelf._inner_widget.width()
        assert w >= _CARD_W, (
            f"inner widget width ({w}px) must be ≥ _CARD_W ({_CARD_W}px) — "
            "a smaller value means cards are smooshed"
        )

    def test_collapsed_then_set_cards_width_correct(self, qapp):
        """A shelf built collapsed then populated via set_cards() sizes correctly."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf
        from metatv.gui.discover_card import _CARD_W

        cfg = Config()
        ic = _make_image_cache()
        n = 3

        # Build collapsed (header-only) — the typical lazy path.
        shelf = _Shelf("Collapsed", "genre:C", [], ic, cfg, collapsed=True)
        shelf.set_cards([_make_card(i) for i in range(n)], image_cache=ic, config=cfg)
        qapp.processEvents()

        m = shelf._inner_layout.contentsMargins()
        spacing = shelf._inner_layout.spacing()
        expected_w = m.left() + m.right() + n * _CARD_W + max(0, n - 1) * spacing

        actual_w = shelf._inner_widget.width()
        assert actual_w == expected_w, (
            f"collapsed-then-set_cards inner width should be {expected_w}px, got {actual_w}px"
        )


# ---------------------------------------------------------------------------
# D3 — collapse_btn is always the rightmost header control
# ---------------------------------------------------------------------------

class TestCollapseButtonIsRightmost:
    """D3: collapse_btn must come after (to the right of) pin_btn and hide_btn."""

    def _header_layout(self, shelf):
        """Extract the QHBoxLayout that is the header row from the shelf's main VLayout."""
        vl = shelf.layout()
        # The header row is the first item (index 0) in the outer VBoxLayout.
        return vl.itemAt(0).layout()

    def _widget_index(self, layout, widget) -> int:
        """Return the layout index of *widget*, or -1 if not found."""
        for i in range(layout.count()):
            item = layout.itemAt(i)
            if item and item.widget() is widget:
                return i
        return -1

    def test_collapse_btn_after_hide_btn(self, qapp):
        """collapse_btn layout index > hide_btn layout index."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()
        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)

        header = self._header_layout(shelf)
        idx_collapse = self._widget_index(header, shelf._collapse_btn)
        idx_hide = self._widget_index(header, shelf._hide_btn)

        assert idx_collapse != -1, "collapse_btn must be in the header layout"
        assert idx_hide != -1, "hide_btn must be in the header layout"
        assert idx_collapse > idx_hide, (
            f"collapse_btn (idx={idx_collapse}) must come after hide_btn (idx={idx_hide}) "
            "so expand stays rightmost and stable"
        )

    def test_collapse_btn_after_pin_btn(self, qapp):
        """collapse_btn layout index > pin_btn layout index."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()
        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)

        header = self._header_layout(shelf)
        idx_collapse = self._widget_index(header, shelf._collapse_btn)
        idx_pin = self._widget_index(header, shelf._pin_btn)

        assert idx_collapse != -1, "collapse_btn must be in the header layout"
        assert idx_pin != -1, "pin_btn must be in the header layout"
        assert idx_collapse > idx_pin, (
            f"collapse_btn (idx={idx_collapse}) must come after pin_btn (idx={idx_pin})"
        )

    def test_collapse_btn_rightmost_widget(self, qapp):
        """collapse_btn must be the last widget in the header layout (rightmost)."""
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()
        shelf = _Shelf("Test", "genre:Test", [], ic, cfg, collapsed=False)

        header = self._header_layout(shelf)
        # Find the last *widget* slot (spacers don't count as a mis-click target).
        last_widget_idx = -1
        last_widget = None
        for i in range(header.count()):
            item = header.itemAt(i)
            if item and item.widget() is not None:
                last_widget_idx = i
                last_widget = item.widget()

        assert last_widget is shelf._collapse_btn, (
            f"collapse_btn must be the last widget in the header — "
            f"found {last_widget!r} at index {last_widget_idx}"
        )

    def test_collapse_btn_not_hidden_in_both_states(self, qapp):
        """collapse_btn must not be explicitly hidden in either expanded or collapsed state.

        Uses isHidden() rather than isVisible() because in a headless test
        environment, no widget is 'visible' until it's shown in a window —
        isHidden() checks the widget's own explicit hide() flag, which is what
        _apply_state() sets for pin_btn/hide_btn in collapsed mode.
        """
        from metatv.core.config import Config
        from metatv.gui.discover_shelf import _Shelf

        cfg = Config()
        ic = _make_image_cache()

        shelf_expanded = _Shelf("E", "genre:E", [], ic, cfg, collapsed=False)
        assert not shelf_expanded._collapse_btn.isHidden(), (
            "collapse_btn must not be hidden when shelf is expanded"
        )

        shelf_collapsed = _Shelf("C", "genre:C", [], ic, cfg, collapsed=True)
        assert not shelf_collapsed._collapse_btn.isHidden(), (
            "collapse_btn must not be hidden when shelf is collapsed — "
            "it is the only always-visible header control in collapsed state"
        )
