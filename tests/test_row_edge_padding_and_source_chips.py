"""Rendered-appearance tests for the 2026-08-02 UX-pass batch (#266).

Two owner reports, both about things that LOOK wrong rather than compute wrong,
so per CLAUDE.md's "UI slices must assert rendered appearance" rule these assert
painted geometry and rendered label text — not parsed data, not cell order, not
token existence.

1. **Results-list rows ran flush to both edges.** Right-aligned cells anchor to
   ``container.right()``, so with no horizontal inset they painted under the
   vertical scrollbar. ``ChannelRowDelegate.paint`` now insets the content rect
   by ``_ROW_H_PAD`` on BOTH sides (matching left inset so the row reads
   balanced rather than merely shifted).

   Pre-fix these fail: the content rect handed to the density painter was
   ``SE_ItemViewItemText`` verbatim, so ``left == text_rect.left()`` and
   ``right == text_rect.right()`` — zero inset on either side.

2. **"Other versions" chips carried a source glyph with only one source.** The
   tester has a single source and every chip repeated the same symbol, crowding
   out the region/quality labels that actually differ. The glyph now renders
   only when the versions genuinely span >1 source.

   Pre-fix the single-source case fails: ``_chip_label`` prepended the glyph
   whenever ``v.provider_id`` resolved in the provider map, regardless of how
   many distinct sources were on screen.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtCore import QRect
from PyQt6.QtGui import QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QStyleOptionViewItem

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_delegate import (
    DENSITY_COMFY,
    DENSITY_COMPACT,
    ChannelRowDelegate,
    _ROW_H_PAD,
)
from metatv.gui.channel_list_model import ChannelListModel


@pytest.fixture()
def qapp():
    return QApplication.instance() or QApplication([])


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
        detected_region="US",
        detected_quality="4K",
        detected_year="2024",
        detected_title="My Great Show",
        user_rating=0,
        detected_collection=None,
        detected_collection_language=None,
        detected_collection_subdub=None,
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


# ---------------------------------------------------------------------------
# 1. Row edge padding — painted geometry
# ---------------------------------------------------------------------------

class TestRowEdgePadding:
    """The content rect handed to the density painter must be inset from the
    row rect on both sides. Asserting the RECT, not the presence of a constant:
    a defined-but-unapplied ``_ROW_H_PAD`` passes a token check and still
    renders under the scrollbar."""

    def _captured_content_rect(self, qapp, density) -> tuple[QRect, QRect]:
        """Return (row_rect_used_by_qt, content_rect_passed_to_painter)."""
        model = _model([_dto()])
        idx = model.index(0)
        delegate = ChannelRowDelegate()
        delegate._density = density

        painter_name = {
            DENSITY_COMFY: "_paint_comfy",
            DENSITY_COMPACT: "_paint_compact",
        }[density]

        captured: list[QRect] = []

        def _capture(painter, rect, index, color, font, **kwargs):
            captured.append(QRect(rect))

        opt = QStyleOptionViewItem()
        opt.rect = QRect(0, 0, 600, 40)

        # A REAL QPainter on a real device: style.drawControl() rejects a mock,
        # and the whole point is to measure what the real paint path produces.
        pixmap = QPixmap(600, 40)
        painter = QPainter(pixmap)
        try:
            with patch.object(delegate, painter_name, side_effect=_capture), \
                 patch.object(delegate, "_shows_thumbnail", return_value=False):
                delegate.paint(painter, opt, idx)
        finally:
            painter.end()

        assert captured, f"{painter_name} was never called"
        return opt.rect, captured[0]

    @pytest.mark.parametrize("density", [DENSITY_COMFY, DENSITY_COMPACT])
    def test_content_rect_is_inset_from_both_edges(self, qapp, density):
        row_rect, content_rect = self._captured_content_rect(qapp, density)

        left_gap = content_rect.left() - row_rect.left()
        right_gap = row_rect.right() - content_rect.right()

        assert left_gap >= _ROW_H_PAD, (
            f"{density}: content starts {left_gap}px from the row's left edge, "
            f"expected at least {_ROW_H_PAD}px"
        )
        assert right_gap >= _ROW_H_PAD, (
            f"{density}: content ends {right_gap}px from the row's right edge, "
            f"expected at least {_ROW_H_PAD}px — right-aligned cells anchor "
            f"here and the vertical scrollbar paints over anything flush"
        )

    @pytest.mark.parametrize("density", [DENSITY_COMFY, DENSITY_COMPACT])
    def test_left_and_right_insets_are_equal_and_nonzero(self, qapp, density):
        """The owner asked for matching padding so the row reads balanced, not
        just shifted away from the scrollbar.

        The non-zero half is not redundant: equality ALONE is satisfied by the
        pre-fix code, where both gaps were 0 — a "padding is symmetric" test
        that passes on a row with no padding is the spec-named-but-wrong shape
        CLAUDE.md calls out. Verified: with the non-zero assertion this fails
        pre-fix; without it, it passed.
        """
        row_rect, content_rect = self._captured_content_rect(qapp, density)

        left_gap = content_rect.left() - row_rect.left()
        right_gap = row_rect.right() - content_rect.right()

        assert left_gap > 0 and right_gap > 0, (
            f"{density}: row has no horizontal padding at all "
            f"({left_gap}px left, {right_gap}px right)"
        )
        assert left_gap == right_gap, (
            f"{density}: asymmetric row padding — {left_gap}px left vs "
            f"{right_gap}px right"
        )


# ---------------------------------------------------------------------------
# 2. Version chips — source glyph only when it distinguishes something
# ---------------------------------------------------------------------------

_GLYPH = "🦖"


class _Version:
    """Minimal stand-in for ChannelVersion carrying only what _chip_label reads."""

    def __init__(self, provider_id, prefix, quality=None):
        self.provider_id = provider_id
        self.detected_prefix = prefix
        self.detected_quality = quality
        self.is_filtered = False
        self.is_hidden = False
        self.is_preferred = False
        self.in_queue = False
        self.is_favorite = False
        self.in_history = False
        self.name = f"{prefix} version"
        self.channel_id = str(uuid.uuid4())
        self.provider_name = "Test Source"


def _label_for(versions, active_flags=None):
    """Render the first version's chip label under the given version set.

    Drives the REAL ``_chip_label`` through the same ``_show_source_icons``
    decision ``load()`` makes, rather than asserting on a helper's return value.
    """
    from metatv.gui.details_versions import _VersionSection

    section = _VersionSection.__new__(_VersionSection)
    section.config = MagicMock()
    section._provider_map = {
        v.provider_id: {"icon": _GLYPH} for v in versions
    }
    active = [v for v in versions if not v.is_filtered and not v.is_hidden]
    filtered = [v for v in versions if v.is_filtered and not v.is_hidden]
    section._show_source_icons = len({
        v.provider_id for v in (active + filtered) if v.provider_id
    }) > 1

    with patch("metatv.gui.details_versions.resolve_category_name",
               side_effect=lambda p, c: p), \
         patch("metatv.gui.details_versions.quality_display",
               side_effect=lambda q: q):
        return section._chip_label(versions[0])


class TestVersionChipSourceGlyph:

    def test_single_source_renders_no_glyph(self, qapp):
        """The tester's case: one source, so the glyph repeats down the whole
        list and distinguishes nothing."""
        versions = [
            _Version("p1", "English"),
            _Version("p1", "Spain"),
            _Version("p1", "France"),
        ]
        label = _label_for(versions)

        assert _GLYPH not in label, (
            f"source glyph rendered with only one source: {label!r}"
        )
        assert "English" in label

    def test_multiple_sources_still_render_the_glyph(self, qapp):
        """Guard against over-correcting: with two sources the glyph is the
        only thing telling the chips apart, so it must survive."""
        versions = [
            _Version("p1", "English"),
            _Version("p2", "English"),
        ]
        label = _label_for(versions)

        assert _GLYPH in label, (
            f"source glyph suppressed even though versions span two sources: "
            f"{label!r}"
        )

    def test_filtered_variants_count_toward_the_decision(self, qapp):
        """A second source that appears only among the collapsed "Filtered
        variants" still makes the glyph meaningful — otherwise expanding that
        section would change the rule mid-render."""
        hidden_sibling = _Version("p2", "Germany")
        hidden_sibling.is_filtered = True
        versions = [_Version("p1", "English"), hidden_sibling]

        label = _label_for(versions)

        assert _GLYPH in label, (
            f"filtered-variant source ignored when deciding glyph visibility: "
            f"{label!r}"
        )
