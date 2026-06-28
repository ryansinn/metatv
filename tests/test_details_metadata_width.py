"""Behavioral tests for the _MetadataSection wrapping fix (details refinements #0103).

Root cause of the "genres run off the right edge" bug: the media/badge row (rating +
IMDb/TMDb + content-rating + runtime) was a non-wrapping QHBoxLayout whose minimum
width was the SUM of its labels.  That pushed the whole _MetadataSection past the
~500px details viewport (which has the horizontal scrollbar off), so the genre flow
below was handed a too-wide rectangle and laid out in a single overflowing row.

Fix: the media row is a wrapping _FlowLayout, whose minimum width is its widest single
chip — so the section stays within the viewport and both the badges and the genres wrap.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


_PANE_MAX_WIDTH = 500  # DetailsPaneWidget.setMaximumWidth(500)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _stub_movie():
    ch = MagicMock()
    ch.name = "Cowboy Bebop"
    ch.media_type = "movie"
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = "Cowboy Bebop"
    ch.detected_year = "1998"
    ch.detected_prefix = "EN"
    ch.detected_quality = "HD"
    ch.detected_region = None
    ch.raw_data = {"rating": "8.9"}
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    return ch


def _rich_metadata():
    from metatv.metadata_providers.base import MetadataResult
    return MetadataResult(
        rating=8.9,
        rating_count=123456,
        content_rating="TV-14",
        runtime=150,
        imdb_id="tt0213338",
        tmdb_id="30991",
        genres=["Action, Adventure, Science Fiction, Drama, Thriller, Mystery, Crime"],
    )


def test_media_row_uses_wrapping_flow_layout(qapp):
    """The media/badge row must be a wrapping _FlowLayout, never a QHBoxLayout —
    that's what keeps its minimum width to a single chip instead of the sum."""
    from metatv.gui.details_sections import _MetadataSection
    from metatv.gui.details_versions import _FlowLayout

    section = _MetadataSection(_make_config())
    assert isinstance(section._media_row.layout(), _FlowLayout), (
        "the media/badge row must use _FlowLayout so it wraps instead of forcing a wide row"
    )


def test_metadata_section_width_within_pane(qapp):
    """With a full set of badges + many genres, the section's minimum width stays within
    the ~500px details viewport (it would exceed it with the old non-wrapping row)."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    section.set_mode(is_live=False)
    section.load_basic(_stub_movie())
    section.load_metadata(_rich_metadata())

    width = section.minimumSizeHint().width()
    assert width <= _PANE_MAX_WIDTH, (
        f"_MetadataSection min width {width}px must fit the {_PANE_MAX_WIDTH}px pane "
        "so the genres wrap instead of clipping off the right edge"
    )


def test_genres_flow_actually_wraps_when_narrow(qapp):
    """The genre flow lays out taller when narrow than when wide — i.e. it really wraps."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    section.set_mode(is_live=False)
    section.load_basic(_stub_movie())
    section.load_metadata(_rich_metadata())

    layout = section._genres_layout
    assert layout.count() >= 4, "expected several genre chips for a meaningful wrap test"
    narrow = layout.heightForWidth(120)
    wide = layout.heightForWidth(2000)
    assert narrow > wide, (
        f"genre flow must wrap to more rows when narrow (narrow={narrow}, wide={wide})"
    )
