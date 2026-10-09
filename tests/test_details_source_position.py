"""Structural test: the details-pane title block's row order (DETAILS-3b).

Provenance ("which of my sources is this from?") used to render directly
under the title/byline, as a plain "Source:" label sharing a row with the
Adult indicator. The redesign (DETAILS-3b) makes it a clickable chip and
moves it to the BOTTOM of the title block — after the genre row and the
rating/TMDb/IMDb row — immediately above "Available in"; the Adult indicator
moves up onto the byline's own row instead.

These tests assert ORDER inside ``_MetadataSection``'s vertical layout, which
is what would silently regress if someone re-inserted the old badge row.
They also guard the width trap: the relocated row must not become a width
forcer (a plain QHBoxLayout's minimum width is the SUM of its children —
docs/DETAILS_PANE_DESIGN.md) — it is built with ``detail_chips.make_flow``,
whose minimum is its widest single chip.
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
    from metatv.gui.details_title import _MetadataSection
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
    ch.raw_data = None
    return ch


def _row_index_of(section, widget) -> int:
    """Index of the section-level row that contains *widget*.

    Rows are either a direct child widget (``title_bar``, ``_rating_row_w``)
    or a nested layout (the byline/source rows), so resolve the widget up to
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


def test_source_row_sits_at_the_bottom_of_the_title_block(qapp):
    """Source comes after the title, byline, genre row and rating row — the
    last row in the block before the recommendation-reason line."""
    section = _section()
    title_idx = _row_index_of(section, section.title_label)
    byline_idx = _row_index_of(section, section._byline_lbl)
    genres_idx = _row_index_of(section, section._genres_container)
    rating_idx = _row_index_of(section, section._rating_row_w)
    source_idx = _row_index_of(section, section._source_chip)

    assert byline_idx == title_idx + 1, "the byline belongs immediately under the title"
    assert genres_idx > byline_idx, "genres must render under the byline"
    assert rating_idx > genres_idx, "the rating row must render under the genres"
    assert source_idx > rating_idx, (
        f"source must be the last row in the block "
        f"(byline {byline_idx}, genres {genres_idx}, rating {rating_idx}, source {source_idx})"
    )


def test_source_row_still_populates_and_stays_clickable(qapp):
    """Moving the row must not break what it shows or its click-to-filter."""
    section = _section()
    provider_map = {"p1": {"icon": "📡", "name": "My Source"}}
    section.load_basic(_channel(id="chan-42"), provider_map)

    assert section._source_chip.isVisibleTo(section)
    assert "My Source" in section._source_chip.text()
    assert "Source:" not in section._source_chip.text(), (
        "the plain 'Source:' label prefix is removed — the chip speaks for itself"
    )

    emitted: list[str] = []
    section.source_filter_requested.connect(emitted.append)
    section._source_chip.click()
    assert emitted == ["p1"]


def test_adult_badge_shares_the_byline_row_not_the_source_row(qapp):
    """The adult indicator moved up onto the byline's row — it no longer
    shares a row with the (relocated) source chip."""
    section = _section()
    section.load_basic(_channel(is_adult=True), {"p1": {"icon": "", "name": "S"}})

    assert section.adult_indicator.isVisibleTo(section)
    byline_idx = _row_index_of(section, section._byline_lbl)
    adult_idx = _row_index_of(section, section.adult_indicator)
    source_idx = _row_index_of(section, section._source_chip)

    assert adult_idx == byline_idx, "the adult indicator must share the byline's row"
    assert adult_idx != source_idx, "the adult indicator no longer shares the source row"


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
