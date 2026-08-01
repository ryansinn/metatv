"""Structural test: the details-pane "Source:" line sits under the TITLE.

Provenance ("which of my sources is this from?") is header information.  It used
to render below the whole metadata block — under the media-type / runtime / IMDb /
rating row and the tagline — so on a title with rich metadata you had to read past
several rows to find it.  It now sits directly beneath the title/year line.

These tests assert ORDER inside ``_MetadataSection``'s vertical layout, which is
what would silently regress if someone re-appended the badge row.  They also guard
the width trap: the relocated row must not become a width forcer (a plain
QHBoxLayout's minimum width is the SUM of its children — docs/DETAILS_PANE_DESIGN.md).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _section():
    from metatv.core.config import Config
    from metatv.gui.details_sections import _MetadataSection
    return _MetadataSection(Config())


def _channel(**kw):
    ch = MagicMock()
    ch.id = kw.get("id", "c1")
    ch.name = kw.get("name", "Some Movie")
    ch.media_type = kw.get("media_type", "movie")
    ch.is_adult = kw.get("is_adult", False)
    ch.detected_title = kw.get("detected_title", "Some Movie")
    ch.detected_year = kw.get("detected_year", "1999")
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.provider_id = kw.get("provider_id", "p1")
    return ch


def _row_index_of(section, widget) -> int:
    """Index of the section-level row that contains *widget*.

    Rows are either a direct child widget (``title_bar``, ``_media_row``) or a
    nested QHBoxLayout (the source/adult badge row), so resolve the widget up to
    the section's direct child first, then match either form.
    """
    layout = section.layout()
    node = widget
    while node is not None and node.parentWidget() is not section:
        node = node.parentWidget()

    for i in range(layout.count()):
        item = layout.itemAt(i)
        if node is not None and item.widget() is node:
            return i
        sub = item.layout()
        if sub is not None:
            for j in range(sub.count()):
                if sub.itemAt(j).widget() is widget:
                    return i
    raise AssertionError(f"{widget!r} not found in the section layout")


def test_source_row_sits_directly_below_the_title_row(qapp):
    section = _section()
    title_idx = _row_index_of(section, section.title_label)
    source_idx = _row_index_of(section, section.source_label)

    assert source_idx == title_idx + 1, (
        f"Source row must be the row right after the title bar "
        f"(title at {title_idx}, source at {source_idx})"
    )


def test_source_row_is_above_the_media_type_row(qapp):
    """The regression this fixes: Source used to render BELOW the metadata block."""
    section = _section()
    source_idx = _row_index_of(section, section.source_label)
    media_idx = _row_index_of(section, section._media_type_lbl)
    tagline_idx = _row_index_of(section, section._tagline_lbl)

    assert source_idx < media_idx, "Source must render above the media-type/rating row"
    assert source_idx < tagline_idx, "Source must render above the tagline"


def test_source_row_still_populates_and_stays_clickable_to_copy(qapp):
    """Moving the row must not break what it shows or its click-to-copy id."""
    section = _section()
    provider_map = {"p1": {"icon": "📡", "name": "My Source"}}
    section.load_basic(_channel(id="chan-42"), provider_map)

    assert section.source_label.isVisibleTo(section)
    assert "My Source" in section.source_label.text()
    assert section.source_label.text().startswith("Source:")
    # click-to-copy payload survives the move
    assert section.source_label.channel_id == "chan-42"
    assert "chan-42" in section.source_label.toolTip()


def test_adult_badge_moved_with_the_source_row(qapp):
    """The adult indicator shares the row — it must move with it, not be orphaned."""
    section = _section()
    section.load_basic(_channel(is_adult=True), {"p1": {"icon": "", "name": "S"}})

    assert section.adult_indicator.isVisibleTo(section)
    assert _row_index_of(section, section.adult_indicator) == _row_index_of(
        section, section.source_label
    )


def test_relocated_row_does_not_force_the_pane_wider(qapp):
    """Width trap: the section must still shrink to the 300px pane minimum."""
    section = _section()
    section.load_basic(
        _channel(name="A Very Long Movie Title That Goes On"),
        {"p1": {"icon": "📡", "name": "A Rather Long Source Name Here"}},
    )
    assert section.minimumSizeHint().width() <= 300, (
        f"_MetadataSection floors the pane at "
        f"{section.minimumSizeHint().width()}px (max 300)"
    )
