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
    from metatv.gui.flow_layout import FlowLayout as _FlowLayout

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


# ---------------------------------------------------------------------------
# BUG 1 — genre/facet chips must escape "&" (mnemonic) for DISPLAY but keep the
# raw value for the tooltip + emitted signal (so filtering still matches).
# A QPushButton treats a lone "&" as a keyboard accelerator, so an un-escaped
# "Action & Adventure" renders as "Action _Adventure" (stray underscore).
# ---------------------------------------------------------------------------


def test_genre_chip_escapes_ampersand_for_display(qapp):
    """A genre containing "&" renders as the escaped "&&" form on the button —
    Qt then draws one literal "&" instead of eating it as a mnemonic."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    section._populate_genre_chips(["Action & Adventure", "Drama"])

    first = section._genres_layout.itemAt(0).widget()
    assert first.text() == "Action && Adventure", (
        f"genre chip must escape '&' as '&&' for display, got {first.text()!r} — "
        "an un-escaped '&' renders as a stray underscore mnemonic"
    )


def test_genre_chip_click_emits_raw_unescaped_value(qapp):
    """Clicking a genre chip emits the ORIGINAL "Action & Adventure" (not the
    escaped "&&" form) so the downstream genre filter still matches."""
    from metatv.gui.details_sections import _MetadataSection

    section = _MetadataSection(_make_config())
    emitted: list[str] = []
    section.genre_clicked.connect(emitted.append)
    section._populate_genre_chips(["Action & Adventure", "Drama"])

    section._genres_layout.itemAt(0).widget().click()
    assert emitted == ["Action & Adventure"], (
        f"clicking must emit the raw genre, got {emitted!r} — the escaped form "
        "would break the genre filter lookup"
    )


def test_tag_chip_escapes_ampersand_but_emits_raw(qapp):
    """The Tags-section facet chips follow the same rule: display escapes "&",
    the emitted filter value stays raw."""
    from metatv.core.repositories.dtos import ChannelTagDTO
    from metatv.gui.details_sections import _TagsSection

    section = _TagsSection(_make_config())
    tag = ChannelTagDTO(
        facet_type="collection",
        value="Fast & Furious",
        source_given=True,
        confidence=1.0,
        feeders=("provider_category",),
    )
    chip = section._make_chip(tag)
    assert "Fast && Furious" in chip.text() and "Fast & Furious" not in chip.text().replace("&&", ""), (
        f"tag chip must escape '&' as '&&' for display, got {chip.text()!r}"
    )

    emitted: list[tuple[str, str]] = []
    section.tag_filter_clicked.connect(lambda ft, v: emitted.append((ft, v)))
    chip.click()
    assert emitted == [("collection", "Fast & Furious")], (
        f"clicking must emit the raw facet value, got {emitted!r}"
    )


def test_tags_facet_row_wraps_not_crushes(qapp):
    """Each Tags-section facet sub-row (GENRE, LANGUAGE, …) lays its chips in a
    WRAPPING _FlowLayout, not a crushing QHBoxLayout.  A long GENRE list must wrap
    to more rows at a narrow width — a QHBoxLayout would keep one row and squeeze
    every chip below its text width (center-elided "tion & Adver")."""
    from metatv.core.repositories.dtos import ChannelTagDTO
    from metatv.gui.details_sections import _TagsSection
    from metatv.gui.flow_layout import FlowLayout as _FlowLayout

    genres = [
        "Action & Adventure", "Sci-Fi & Fantasy", "Animation", "Comedy", "Drama",
        "Documentary", "Family", "Kids", "War & Politics", "Reality",
    ]
    section = _TagsSection(_make_config())
    section.load([
        ChannelTagDTO(facet_type="genre", value=g, source_given=True,
                      confidence=1.0, feeders=("genre",))
        for g in genres
    ])

    # Locate the facet chip row — the widget whose layout is a _FlowLayout.
    layout = section._content_layout
    flow_rows = [
        layout.itemAt(i).widget().layout()
        for i in range(layout.count())
        if layout.itemAt(i).widget() is not None
        and isinstance(layout.itemAt(i).widget().layout(), _FlowLayout)
    ]
    assert flow_rows, (
        "the GENRE sub-row must use a wrapping _FlowLayout, not a QHBoxLayout that "
        "crushes/truncates each chip"
    )
    flow = flow_rows[0]
    assert flow.count() == len(genres)
    narrow = flow.heightForWidth(150)
    wide = flow.heightForWidth(2000)
    assert narrow > wide, (
        f"GENRE chips must wrap to more rows when narrow (narrow={narrow}, wide={wide})"
    )


# ---------------------------------------------------------------------------
# BUG 2 — genre chips must WRAP at the pane width and never truncate, even when
# a SIBLING section (here: a version chip with a very long unbreakable label)
# tries to force the details content column wider than the viewport.  The pane's
# width authority (_sync_content_width caps content to the viewport) plus the
# wrapping _FlowLayout keep the genres inside the viewport; without either, the
# genres would lay out in the over-wide column and clip off the right edge.
# ---------------------------------------------------------------------------

_FORCING_PREFIX = "SuperLongUnbreakableCategoryNameThatForcesWidthXXXXXXXXXXXXXXXX"


def _full_pane(qapp, tmp_path):
    from metatv.core.image_cache import ImageCache
    from metatv.gui.details_pane import DetailsPaneWidget

    ic = ImageCache(cache_dir=str(tmp_path / "imgcache"))
    pane = DetailsPaneWidget(_make_config(), ic, None)  # db=None → no EPG agenda
    for sec in (pane._poster, pane._meta, pane._plot, pane._cast, pane._tech):
        if hasattr(sec, "set_mode"):
            sec.set_mode(False)
    return pane


def test_genres_wrap_within_viewport_despite_forcing_sibling(qapp, tmp_path):
    """Full-composition repro: genres + a width-forcing version chip inside the
    real details pane.  The genre chips must wrap WITHIN the viewport (never run
    off the right edge) and each chip must render at its full content width (no
    per-button truncation)."""
    from metatv.gui.details_versions import ChannelVersion

    pane = _full_pane(qapp, tmp_path)
    pane._meta._populate_genre_chips([
        "Action & Adventure", "Sci-Fi & Fantasy", "Animation", "Comedy",
        "Drama", "Documentary", "Family", "Kids", "War & Politics",
    ])
    # A sibling section that WOULD force the column wider than the pane.
    pane._versions.load(
        [ChannelVersion(channel_id="v1", name="v1", in_queue=False,
                        detected_prefix=_FORCING_PREFIX, detected_quality="4K")],
        provider_map={},
    )

    pane.resize(320, 1200)
    pane.show()
    qapp.processEvents()
    qapp.processEvents()

    viewport_w = pane._scroll.viewport().width()
    container = pane._meta._genres_container

    # Width authority holds: content (and therefore the genre row) stays within
    # the viewport — the forcing sibling cannot drag it wider.
    assert pane._content.width() <= viewport_w + 1, (
        f"content width {pane._content.width()} exceeds viewport {viewport_w} — the "
        "forcing sibling widened the column; genres would clip off the right edge"
    )
    assert container.width() <= viewport_w + 1, (
        f"genres container {container.width()} exceeds viewport {viewport_w}"
    )

    # Every genre chip renders at full content width (no squeeze/elision) and sits
    # entirely within the container (no off-edge clipping).
    layout = pane._meta._genres_layout
    assert layout.count() == 9
    for i in range(layout.count()):
        chip = layout.itemAt(i).widget()
        geom = chip.geometry()
        assert geom.width() >= chip.sizeHint().width(), (
            f"chip {chip.text()!r} truncated: geom width {geom.width()} < content "
            f"width {chip.sizeHint().width()}"
        )
        assert geom.right() <= container.width() + 1, (
            f"chip {chip.text()!r} runs off the right edge "
            f"(right={geom.right()}, container={container.width()})"
        )

    # And the flow genuinely wraps to more rows when narrower.
    assert layout.heightForWidth(150) > layout.heightForWidth(2000), (
        "genre flow must add rows as it narrows (wrap), not truncate on one row"
    )
