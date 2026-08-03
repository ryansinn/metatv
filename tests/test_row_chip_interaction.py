"""Tests for clickable/hoverable row chips (task #24).

Owner report: "mouse hover works on sidebars and UI content, but not on chips in
result lists" — followed by "on click should just filter those search results
with the chips in the search area, like with filters, and yes, also hover to
give more detail about what the chip represents".

Row chips are painted by ``ChannelRowDelegate``, not built as child widgets, so
they have neither ``setToolTip`` nor a ``mousePressEvent`` of their own. The
delegate records the rects it actually painted and the view hit-tests them.

The load-bearing property is that the hit region matches what was DRAWN — a
recomputed region can drift from the visible chip and produce clicks that land
on nothing (or on the wrong facet). These tests assert against captured paint
geometry, not against a re-derivation of it.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_delegate import DENSITY_COMFY, ChannelRowDelegate
from metatv.gui.channel_list_model import ChannelListModel


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


def _dto(**overrides) -> ChannelListDTO:
    base = dict(
        id=str(uuid.uuid4()), name="Channel", media_type="movie", provider_id="p1",
        is_favorite=False, category=None, quality=None,
        detected_prefix="EN", detected_region="US", detected_quality="4K",
        detected_year="2024", detected_title="My Great Show", user_rating=0,
        detected_collection=None, detected_collection_language=None,
        detected_collection_subdub=None,
    )
    base.update(overrides)
    return ChannelListDTO(**base)


def _painted_delegate(qapp, dto=None) -> ChannelRowDelegate:
    """Paint one real row and return the delegate holding its hit regions."""
    model = ChannelListModel()
    model.set_channels(
        [dto or _dto()], provider_icon_map={}, show_provider_icon=False,
        has_more=False, query_params={}, favorite_icon="", unfavorite_icon="",
        get_media_type_icon=lambda mt: "",
    )
    delegate = ChannelRowDelegate()
    delegate._density = DENSITY_COMFY

    opt = QStyleOptionViewItem()
    opt.rect = QRect(0, 0, 600, 44)
    pixmap = QPixmap(600, 44)
    painter = QPainter(pixmap)
    try:
        with patch.object(delegate, "_shows_thumbnail", return_value=False):
            delegate.paint(painter, opt, model.index(0))
    finally:
        painter.end()
    return delegate


class TestHitRegions:

    def test_painted_chips_are_hit_testable(self, qapp):
        delegate = _painted_delegate(qapp)

        cells = delegate.hit_cells(0)

        assert cells, "no hit regions recorded — chips would be inert"
        facets = {cell.facet for _rect, cell in cells if cell.facet}
        assert "quality" in facets
        assert "region" in facets or "language" in facets

    def test_every_hit_region_has_nonzero_area(self, qapp):
        """A zero-width rect is unhittable — it would pass a "region exists"
        check while being impossible to actually click."""
        delegate = _painted_delegate(qapp)

        for rect, cell in delegate.hit_cells(0):
            assert rect.width() > 0 and rect.height() > 0, (
                f"degenerate hit rect {rect} for {cell.text!r}"
            )

    def test_regions_do_not_accumulate_across_repaints(self, qapp):
        """Repainting the same row must REPLACE its regions.

        Otherwise scrolling grows the list without bound and stale rects from a
        previous scroll position start swallowing clicks.
        """
        model = ChannelListModel()
        model.set_channels(
            [_dto()], provider_icon_map={}, show_provider_icon=False,
            has_more=False, query_params={}, favorite_icon="", unfavorite_icon="",
            get_media_type_icon=lambda mt: "",
        )
        delegate = ChannelRowDelegate()
        delegate._density = DENSITY_COMFY
        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 600, 44)
        pixmap = QPixmap(600, 44)
        painter = QPainter(pixmap)
        try:
            with patch.object(delegate, "_shows_thumbnail", return_value=False):
                delegate.paint(painter, opt, model.index(0))
                first = len(delegate.hit_cells(0))
                delegate.paint(painter, opt, model.index(0))
                second = len(delegate.hit_cells(0))
        finally:
            painter.end()

        assert first == second, (
            f"hit regions accumulated across repaints ({first} → {second})"
        )

    def test_unpainted_row_has_no_regions(self, qapp):
        delegate = ChannelRowDelegate()
        assert delegate.hit_cells(99) == []


class TestChipSemantics:
    """Which chips promise a click, and what each one says on hover."""

    def test_every_recorded_chip_has_hover_text(self, qapp):
        """The owner's actual complaint: hover did nothing."""
        delegate = _painted_delegate(qapp)

        for _rect, cell in delegate.hit_cells(0):
            assert cell.tip, f"chip {cell.text!r} has no hover explanation"

    def test_filterable_chips_name_their_facet_and_value(self, qapp):
        delegate = _painted_delegate(qapp)

        for _rect, cell in delegate.hit_cells(0):
            if cell.facet:
                assert cell.value, (
                    f"chip {cell.text!r} claims facet {cell.facet!r} but carries "
                    f"no value to filter on"
                )

    def test_year_explains_itself_but_promises_no_click(self, qapp):
        """"year" is not a tag facet, so a click could not filter.

        Giving it a facet would render a pointing-hand cursor over a chip whose
        click does nothing — worse than no affordance at all.
        """
        delegate = _painted_delegate(qapp)

        years = [c for _r, c in delegate.hit_cells(0) if c.text == "2024"]
        assert years, "year cell was not recorded"
        assert years[0].tip, "year should still explain itself on hover"
        assert not years[0].facet, "year must not promise a filter it cannot do"

    def test_chip_facets_match_the_tag_decomposer_vocabulary(self):
        """Drift guard: the delegate's facet names must be routable.

        ``_on_row_chip_clicked`` dispatches on these strings; a facet the tag
        system doesn't emit would reach the log-and-drop branch instead of
        filtering, which is a silent dead click.
        """
        import inspect
        import re

        from metatv.core import tag_decomposer
        from metatv.gui import channel_list_delegate

        emitted = set(re.findall(
            r'facet=["\']([a-z_]+)["\']',
            inspect.getsource(channel_list_delegate),
        ))
        known = {"audio", "collection", "genre", "language", "quality", "region"}
        assert emitted, "no chip facets found — did the attribute get renamed?"
        assert emitted <= known, (
            f"delegate emits facets the tag system does not know: "
            f"{sorted(emitted - known)}"
        )
        # Sanity-check the reference set against the real module rather than
        # trusting a hand-copied list.
        src = inspect.getsource(tag_decomposer)
        for facet in emitted:
            assert facet in src, f"{facet!r} never appears in tag_decomposer"


class TestRouting:
    """``_on_row_chip_clicked`` dispatches into the EXISTING filter handlers."""

    def _host(self):
        from metatv.gui.main_window_nav import _NavMixin

        host = _NavMixin.__new__(_NavMixin)
        host._on_genre_filter_requested = MagicMock()
        host._on_tag_filter_requested = MagicMock()
        return host

    def test_genre_uses_the_dedicated_genre_filter(self):
        host = self._host()
        host._on_row_chip_clicked("genre", "Drama")
        host._on_genre_filter_requested.assert_called_once_with("Drama")
        host._on_tag_filter_requested.assert_not_called()

    @pytest.mark.parametrize("facet", ["quality", "region", "language", "collection"])
    def test_other_facets_use_the_tag_filter(self, facet):
        host = self._host()
        host._on_row_chip_clicked(facet, "X")
        host._on_tag_filter_requested.assert_called_once_with(facet, "X")

    def test_blank_input_is_ignored(self):
        host = self._host()
        host._on_row_chip_clicked("", "")
        host._on_row_chip_clicked("quality", "")
        host._on_genre_filter_requested.assert_not_called()
        host._on_tag_filter_requested.assert_not_called()

    def test_unknown_facet_does_not_silently_filter(self):
        host = self._host()
        host._on_row_chip_clicked("nonsense", "X")
        host._on_genre_filter_requested.assert_not_called()
        host._on_tag_filter_requested.assert_not_called()
