"""Typing in the sub-filter narrows the rows on screen, without a re-query.

Owner: *"maybe there almost needs to be a sub-filter/search that appears to sub
filter the search of the search results — the way it works on Discover and
Recipe. A text field that the user can just enter in a simple set of characters
to pattern match within the search results."*

It matches EVERYTHING on the row, which the owner chose over title-only: the
year, genre, category and matched person are all visible and all things someone
will reasonably type. It never re-queries, so it narrows loaded rows only — and
the field's placeholder says "these results" rather than "channels" for exactly
that reason.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui import channel_list_filtering as filt
from metatv.gui.channel_list_roles import ROW_KIND_ROLE


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dto(name, *, section_key=None, person=None, year=None, category=None,
         media_type="movie"):
    return ChannelListDTO(
        id=str(uuid.uuid4()), name=name, media_type=media_type, provider_id="p1",
        is_favorite=False, category=category, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=year,
        detected_title=name, section_key=section_key, match_person=person,
    )


def _model(qapp, dtos, search=None):
    from metatv.gui.channel_list_model import ChannelListModel
    m = ChannelListModel()
    m.set_channels(dtos, provider_icon_map={}, show_provider_icon=False,
                   has_more=False, query_params={"search_query": search},
                   favorite_icon="★", unfavorite_icon="☆")
    return m


def _titles(model):
    from metatv.gui.channel_list_roles import TITLE_ROLE
    return [model.index(r, 0).data(TITLE_ROLE)
            for r in range(model.rowCount())
            if model.index(r, 0).data(ROW_KIND_ROLE) not in ("header", "person")]


CORPUS = [
    _dto("Low Winter Sun", year="2013", category="Crime / Drama"),
    _dto("The Long Firm", year="2004", category="Drama"),
    _dto("Kingsman", year="2014", category="Action"),
]


# ── the matcher ────────────────────────────────────────────────────────────

def test_it_matches_any_field_on_the_row():
    """The owner's choice over title-only."""
    row = _dto("Low Winter Sun", person="Mark Strong", year="2013",
               category="Crime / Drama")
    for needle in ("winter", "mark", "strong", "2013", "crime", "drama"):
        assert filt.matches(row, needle), needle
    assert not filt.matches(row, "kingsman")


def test_tokens_match_in_any_order():
    """"cage 2024" finds a 2024 Cage film without guessing which field leads."""
    row = _dto("Arcadian", person="Nicolas Cage", year="2024")
    assert filt.matches(row, "cage 2024")
    assert filt.matches(row, "2024 cage")
    assert not filt.matches(row, "cage 1999"), "every token must match"


def test_an_empty_filter_keeps_everything():
    assert filt.matches(_dto("Anything"), "")
    assert filt.matches(_dto("Anything"), "   ")
    assert filt.visible_indices(CORPUS, "") == [0, 1, 2]


def test_it_matches_no_glyphs_or_separators():
    """Built from the DTO's fields, not the delegate's composed row string.

    Matching the rendered text would let a stray "·" or the favourite star
    answer a filter, which is a filter that appears to do nothing.
    """
    hay = filt.haystack(_dto("Low Winter Sun", year="2013"))
    for junk in ("·", "★", "☆", "▶", "✓"):
        assert junk not in hay, hay


# ── the model ──────────────────────────────────────────────────────────────

def test_it_narrows_a_flat_list(qapp):
    model = _model(qapp, CORPUS)
    assert len(_titles(model)) == 3

    model.set_result_filter("drama")
    assert sorted(_titles(model)) == ["Low Winter Sun", "The Long Firm"]

    model.set_result_filter("")
    assert len(_titles(model)) == 3


def test_it_narrows_inside_sections_and_keeps_the_grouping(qapp):
    model = _model(qapp, [
        _dto("Strongman", section_key="title"),
        _dto("Low Winter Sun", section_key="cast", person="Mark Strong",
             category="Crime"),
        _dto("Kingsman", section_key="cast", person="Mark Strong",
             category="Action"),
    ], search="strong")

    model.set_result_filter("crime")
    assert _titles(model) == ["Low Winter Sun"]
    # The Titles section had nothing left, so its heading goes with it — an
    # empty heading is a heading that lies about having content.
    labels = [model.index(r, 0).data(ROW_KIND_ROLE)
              for r in range(model.rowCount())]
    assert labels.count("header") == 1


def test_the_count_follows_the_filter(qapp):
    """A number beside a filter that disagrees with the list under it is why
    people stop trusting counts."""
    model = _model(qapp, CORPUS)
    assert model.loaded_count() == 3
    model.set_result_filter("drama")
    assert model.loaded_count() == 2


def test_setting_the_same_text_twice_is_a_no_op(qapp):
    """It resets the model, so a keystroke that changes nothing must not."""
    model = _model(qapp, CORPUS)
    resets = []
    model.modelReset.connect(lambda: resets.append(1))
    model.set_result_filter("drama")
    model.set_result_filter("drama")
    assert len(resets) == 1


# ── the field ──────────────────────────────────────────────────────────────

def test_the_field_has_a_clear_button_and_says_what_it_filters(qapp):
    from metatv.gui.filter_chip_bar import FilterChipBar
    bar = FilterChipBar()
    field = bar._results_filter

    assert field.isClearButtonEnabled(), "the project's clear-button standard"
    # "these results", not "channels": it can only reach LOADED rows.
    assert "results" in field.placeholderText().lower()
    assert field.toolTip(), "every control carries a tooltip"


def test_typing_in_the_field_emits_the_text(qapp):
    from metatv.gui.filter_chip_bar import FilterChipBar
    bar = FilterChipBar()
    seen = []
    bar.results_filter_changed.connect(seen.append)
    bar._results_filter.setText("crime")
    assert seen == ["crime"]
