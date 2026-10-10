"""Behavioral tests for DETAILS-3b — the details-pane title block redesign.

Genres move to a chip row right under the title, the rating renders as a
plain "8.0 / 10" (never a star), TMDb/IMDb become clickable id chips, and the
source + this copy's collection render as one row of chips with no label.
Each assertion is on RENDERED appearance (CLAUDE.md: UI slices must assert
rendered appearance) — chip stylesheets, plain text, clipboard content and
emitted signals — and every one of these is new surface the pre-redesign
``_MetadataSection`` (stars, boxed region chip, plain "Source:" label) could
not satisfy.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from metatv.core.config import Config
from metatv.core.repositories.dtos import ChannelTagDTO
from metatv.gui.detail_chips import chip_sheet
from metatv.gui.details_title import _MetadataSection
from metatv.metadata_providers.base import MetadataResult


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _make_config():
    return Config()


def _stub_movie(**kw):
    ch = MagicMock()
    ch.name = kw.get("name", "Spider-Man No Way Home")
    ch.media_type = kw.get("media_type", "movie")
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = kw.get("detected_title", "Spider-Man No Way Home")
    ch.detected_year = kw.get("detected_year", "2021")
    ch.detected_prefix = kw.get("detected_prefix", "EN")
    ch.detected_quality = kw.get("detected_quality", "4K")
    ch.detected_region = None
    ch.raw_data = kw.get("raw_data", None)
    ch.provider_id = kw.get("provider_id", "prov-1")
    ch.id = kw.get("id", "chan-1")
    ch.watch_completed = False
    ch.watch_progress = 0
    return ch


def _all_texts(section) -> list[str]:
    out = [w.text() for w in section.findChildren(QLabel)]
    out += [w.text() for w in section.findChildren(QPushButton)]
    return out


def _genre_chips(section) -> dict[str, QPushButton]:
    out = {}
    for i in range(section._genres_layout.count()):
        w = section._genres_layout.itemAt(i).widget()
        if isinstance(w, QPushButton):
            out[w.text()] = w
    return out


def test_rating_has_no_star_and_plain_text_is_number_over_ten(qapp):
    section = _MetadataSection(_make_config())
    section.load_basic(_stub_movie())
    section.load_metadata(MetadataResult(rating=8.0))

    assert not any("★" in t for t in _all_texts(section)), (
        "no widget in the title block may show a star glyph for the rating"
    )
    plain = re.sub(r"<[^>]+>", "", section.rating_label.text())
    assert plain == "8.0 / 10", f"expected plain rating text '8.0 / 10', got {plain!r}"


def test_byline_includes_runtime_and_content_rating(qapp):
    section = _MetadataSection(_make_config())
    section.load_basic(_stub_movie(detected_year="2021"))
    section.load_metadata(MetadataResult(runtime=148, content_rating="PG-13"))

    assert section._byline_lbl.text() == "Movie · 2021 · 2h 28m · PG-13"


def test_byline_runtime_under_an_hour_has_no_hours_segment(qapp):
    section = _MetadataSection(_make_config())
    section.load_basic(_stub_movie(detected_year=None))
    section.load_metadata(MetadataResult(runtime=48))

    assert section._byline_lbl.text() == "Movie · 48m"


def test_genre_chips_use_the_facet_genre_chip_sheet(qapp):
    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action", "Adventure"]))

    chips = _genre_chips(section)
    assert chips, "expected at least one genre chip"
    expected = chip_sheet("COLOR_FACET_GENRE")
    for chip in chips.values():
        assert chip.styleSheet() == expected


def test_guessed_tag_genre_renders_dashed_with_guessed_tooltip(qapp):
    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(genres=["Action"]))
    section.set_genre_tags([
        ChannelTagDTO(facet_type="genre", value="Thriller", source_given=False,
                      confidence=0.2, feeders=("name_parse",)),
    ])

    chips = _genre_chips(section)
    assert "Thriller" in chips, f"expected a merged-in tag genre chip; got {list(chips)}"
    assert "dashed" in chips["Thriller"].styleSheet(), (
        "a guessed tag genre must render as a dashed chip"
    )
    assert chips["Thriller"].toolTip().startswith("Guessed "), (
        f"expected a 'Guessed ...' tooltip, got {chips['Thriller'].toolTip()!r}"
    )
    # The metadata genre stays solid (not dashed) — only the guessed one is.
    assert "dashed" not in chips["Action"].styleSheet()


def test_source_row_shows_provider_then_collection_after_set_collection(qapp):
    section = _MetadataSection(_make_config())
    provider_map = {"prov-1": {"icon": "📡", "name": "My Source"}}
    section.load_basic(_stub_movie(provider_id="prov-1"), provider_map)

    assert "My Source" in section._source_chip.text()
    assert section._collection_chip.isHidden(), "no collection chip until set_collection"

    section.set_collection("Marvel Universe")

    assert not section._collection_chip.isHidden()
    assert section._collection_chip.text() == "Marvel Universe"


def test_source_chip_click_copies_the_channel_id(qapp):
    from PyQt6.QtWidgets import QApplication
    section = _MetadataSection(_make_config())
    provider_map = {"prov-1": {"icon": "", "name": "My Source"}}
    movie = _stub_movie(provider_id="prov-1")
    movie.id = "chan-1"            # a MagicMock id would not be a clipboard string
    section.load_basic(movie, provider_map)

    said: list[str] = []
    section.status_message.connect(said.append)
    section._source_chip.click()

    assert QApplication.clipboard().text() == movie.id
    assert said and movie.id in said[0]


def test_collection_chip_click_emits_collection_clicked(qapp):
    section = _MetadataSection(_make_config())
    provider_map = {"prov-1": {"icon": "", "name": "My Source"}}
    section.load_basic(_stub_movie(provider_id="prov-1"), provider_map)
    section.set_collection("Marvel Universe")

    emitted: list[str] = []
    section.collection_clicked.connect(emitted.append)
    section._collection_chip.click()

    assert emitted == ["Marvel Universe"]


def test_tmdb_chip_click_copies_id_to_clipboard_and_reports_status(qapp):
    section = _MetadataSection(_make_config())
    section.load_metadata(MetadataResult(tmdb_id="634649"))

    statuses: list[str] = []
    section.status_message.connect(statuses.append)
    section._tmdb_chip.click()

    assert QApplication.clipboard().text() == "634649"
    assert statuses and "634649" in statuses[0]


def test_no_boxed_region_chip_in_the_title_block(qapp):
    section = _MetadataSection(_make_config())
    section.load_basic(_stub_movie(detected_prefix="EN"))

    assert "English (EN)" not in _all_texts(section), (
        "the boxed region/prefix chip is removed from the title block (DETAILS-3b)"
    )
