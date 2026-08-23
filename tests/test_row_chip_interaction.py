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
        from metatv.gui import channel_list_delegate, channel_row_cells

        # Both halves of the row, so the guard cannot be dodged by moving a
        # builder between them — which is exactly what happened when the cell
        # builders were split out of the delegate.
        emitted = set()
        for module in (channel_list_delegate, channel_row_cells):
            emitted |= set(re.findall(
                r'facet=["\']([a-z_]+)["\']',
                inspect.getsource(module),
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

    @pytest.mark.parametrize("facet,chip_value,tag_value", [
        ("quality", "4K", "4K / UHD"),   # chip shows the token, tag stores the group
        ("language", "EN", "English"),   # chip shows the code, tag stores the name
        ("region", "FR", "FR"),          # these two happen to coincide
    ])
    def test_facets_are_translated_to_tag_vocabulary(self, facet, chip_value, tag_value):
        """The chip's displayed value is NOT always the tag's stored value."""
        host = self._host()
        host._on_row_chip_clicked(facet, chip_value)
        host._on_tag_filter_requested.assert_called_once_with(facet, tag_value)

    def test_untranslatable_value_does_not_filter(self):
        """Better to do nothing than to filter on a value no tag has — that
        empties the list and reads as a broken filter."""
        host = self._host()
        host._on_row_chip_clicked("quality", "NONSENSE")
        host._on_tag_filter_requested.assert_not_called()

    def test_collection_filters_by_the_CLICKED_chip_not_the_selection(self):
        """_on_tag_filter_requested's collection branch resolves the SELECTED
        channel's category and ignores the value handed to it. That is right for
        a details-pane click but wrong for a row chip, which deliberately does
        not change the selection — it would filter by whatever was selected
        before. So collection takes its own path.
        """
        host = self._host()
        host._reset_context_filters = MagicMock()
        host._context_filter_label = MagicMock()
        host._context_filter_chip = MagicMock()
        host._save_search_state = MagicMock()
        host.switch_to_list_view = MagicMock()
        host.load_channels = MagicMock()

        host._on_row_chip_clicked("collection", "AMAZON PRIME")

        assert host._details_category_filter == "AMAZON PRIME"
        host._on_tag_filter_requested.assert_not_called()
        host.load_channels.assert_called_once()

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


# ---------------------------------------------------------------------------
# Display vocabulary vs TAG vocabulary — the bug that shipped in #270
# ---------------------------------------------------------------------------

class TestTagValueTranslation:
    """A chip displays a CODE; the tag table stores a resolved NAME or GROUP.

    Shipped broken: clicking a 4K chip filtered on ``"4K"`` while the tag stores
    ``"4K / UHD"``, and a language chip filtered on ``"EN"`` while the tag stores
    ``"English"`` — both emptied the list. Region and genre coincide by accident,
    which is what made the mismatch look like it worked (the owner's "FR filters
    seem to work" was a REGION chip, not a language one).
    """

    def test_quality_token_resolves_to_its_group(self):
        from metatv.core.channel_name_utils import tag_value_for

        assert tag_value_for("quality", "4K") == "4K / UHD"
        assert tag_value_for("quality", "UHD") == "4K / UHD"
        assert tag_value_for("quality", "HD") == "HD"

    def test_quality_group_name_passes_through(self):
        """Idempotent — a value already in tag vocabulary must not be re-mapped."""
        from metatv.core.channel_name_utils import tag_value_for

        assert tag_value_for("quality", "4K / UHD") == "4K / UHD"

    def test_language_code_resolves_to_its_name(self):
        from metatv.core.channel_name_utils import tag_value_for

        assert tag_value_for("language", "EN") == "English"
        assert tag_value_for("language", "FR") == "French"

    def test_region_codes_are_already_tag_values(self):
        from metatv.core.channel_name_utils import tag_value_for

        assert tag_value_for("region", "FR") == "FR"
        assert tag_value_for("region", "US") == "US"

    def test_unmappable_token_returns_none_rather_than_the_raw_value(self):
        """Returning the raw token is what produced the empty list.

        None means "don't filter"; the caller must not substitute the input.
        """
        from metatv.core.channel_name_utils import tag_value_for

        assert tag_value_for("quality", "NOPE") is None
        assert tag_value_for("language", "ZZ") is None

    def test_resolved_values_actually_exist_in_the_tag_vocabulary(self):
        """End-to-end: every quality group this resolves to must be a real
        group name, not something invented here."""
        from metatv.core.channel_name_utils import tag_value_for
        from metatv.core.config import BASE_QUALITY_GROUPS

        for members in BASE_QUALITY_GROUPS.values():
            for token in members:
                resolved = tag_value_for("quality", token)
                assert resolved in BASE_QUALITY_GROUPS, (
                    f"{token!r} resolved to {resolved!r}, which is not a group"
                )


class TestContextFilterUnification:
    """Every context-filter entry point goes through one applier.

    Owner: "whatever filter path those use should be unified so we're not making
    multiple hand-rolled functions that duplicate the same behavior." That was a
    direct response to this session adding an eighth copy of the reset/set/label/
    show/save/switch/reload ritual — one that set the right state var from the
    WRONG column and silently filtered nothing.
    """

    def _host(self):
        from metatv.gui.main_window_nav import _NavMixin

        host = _NavMixin.__new__(_NavMixin)
        host._reset_context_filters = MagicMock()
        host._context_filter_label = MagicMock()
        host._context_filter_chip = MagicMock()
        host._save_search_state = MagicMock()
        host.switch_to_list_view = MagicMock()
        host.load_channels = MagicMock()
        return host

    def test_applier_performs_the_whole_ritual(self):
        host = self._host()

        host._activate_context_filter("Genre: Drama", _details_genre_filter="Drama")

        host._reset_context_filters.assert_called_once()
        assert host._details_genre_filter == "Drama"
        host._context_filter_label.setText.assert_called_once_with("Genre: Drama")
        host._context_filter_chip.show.assert_called_once()
        host._save_search_state.assert_called_once()
        host.switch_to_list_view.assert_called_once()
        host.load_channels.assert_called_once()

    def test_row_and_details_collection_clicks_are_indistinguishable(self):
        """Both paths must produce the SAME filter state — that is the point of
        unifying them."""
        from_row = self._host()
        from_row._on_row_chip_clicked("collection", "AMAZON PRIME")

        from_details = self._host()
        from_details._resolve_current_channel_category = lambda: "AMAZON PRIME"
        from_details._on_tag_filter_requested("collection", "ignored-by-design")

        assert from_row._details_category_filter == "AMAZON PRIME"
        assert from_details._details_category_filter == "AMAZON PRIME"
        for host in (from_row, from_details):
            host._context_filter_label.setText.assert_called_once_with(
                "Collection: AMAZON PRIME"
            )
            host.load_channels.assert_called_once()

    def test_empty_category_does_not_apply_a_filter(self):
        """A channel with no curated category must leave the list untouched
        rather than filter on '' and show nothing."""
        host = self._host()
        host._on_category_filter_requested("")
        host.load_channels.assert_not_called()
        host._context_filter_chip.show.assert_not_called()

    def test_handlers_do_not_reimplement_the_ritual(self):
        """Structural guard: the per-filter handlers must DELEGATE.

        If a future handler inlines load_channels()/_context_filter_chip.show()
        again, it has forked the behaviour — which is exactly what produced the
        broken collection path.
        """
        import inspect

        from metatv.gui.main_window_nav import _NavMixin

        for name in ("_on_genre_filter_requested", "_on_person_filter_requested",
                     "_on_category_filter_requested", "_on_tag_filter_requested"):
            src = inspect.getsource(getattr(_NavMixin, name))
            assert "load_channels()" not in src, (
                f"{name} calls load_channels() directly instead of going through "
                f"_activate_context_filter"
            )
            assert "_context_filter_chip.show()" not in src, (
                f"{name} shows the chip directly instead of delegating"
            )

    def test_collection_chip_filters_on_category_not_the_displayed_collection(self, qapp):
        """The chip DISPLAYS detected_collection but must FILTER on category.

        These are different columns; filtering on the displayed string matches
        nothing. Asserted on a real painted row.
        """
        dto = _dto(category="RAW PROVIDER CAT", detected_collection="Clean Collection")
        delegate = _painted_delegate(qapp, dto)

        collection = [c for _r, c in delegate.hit_cells(0) if c.facet == "collection"]
        assert collection, "collection chip was not painted"
        assert collection[0].value == "RAW PROVIDER CAT", (
            f"collection chip filters on {collection[0].value!r} — it must carry "
            f"the curated category, not the displayed collection"
        )
        assert "Clean Collection" in collection[0].text


class TestNoDeadAffordances:
    """A chip that shows a pointing-hand cursor must actually filter.

    Two shipped this way already: the quality/language chips filtered on a value
    the tag table doesn't store (empty list), and the sub/dub marker claimed the
    language facet even though "AR-SUB" resolves to nothing and the audio facet
    is empty in practice. Both rendered a clickable cursor over a click that did
    nothing useful — the exact failure the year chip was deliberately spared.
    """

    def test_every_filterable_chip_resolves_to_a_tag_value(self, qapp):
        from metatv.core.channel_name_utils import tag_value_for

        dto = _dto(
            detected_prefix="EN", detected_region="US", detected_quality="4K",
            detected_collection="Some Collection", category="SOME CATEGORY",
            detected_collection_subdub="AR-SUB", detected_collection_language="FR",
        )
        delegate = _painted_delegate(qapp, dto)

        offenders = []
        for _rect, cell in delegate.hit_cells(0):
            if not cell.facet:
                continue
            if cell.facet in ("genre", "collection"):
                # These filter on a stored column directly, not via the code
                # translation, so a non-empty value is the whole requirement.
                if not cell.value:
                    offenders.append(f"{cell.facet}:{cell.text!r} has no value")
                continue
            if tag_value_for(cell.facet, cell.value) is None:
                offenders.append(
                    f"{cell.facet}:{cell.text!r} (value={cell.value!r}) claims to "
                    f"be clickable but resolves to no tag value"
                )
        assert not offenders, (
            "chips promise a filter they cannot deliver:\n  " + "\n  ".join(offenders)
        )

    def test_subdub_marker_explains_itself_without_claiming_a_filter(self, qapp):
        dto = _dto(detected_collection_subdub="AR-SUB")
        delegate = _painted_delegate(qapp, dto)

        subdub = [c for _r, c in delegate.hit_cells(0) if c.text == "AR-SUB"]
        assert subdub, "sub/dub marker chip was not painted"
        assert subdub[0].tip, "it should still explain itself on hover"
        assert not subdub[0].facet, (
            "AR-SUB is not a language tag and the audio facet is empty — it must "
            "not render a clickable cursor"
        )
