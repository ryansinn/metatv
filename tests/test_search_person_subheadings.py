"""A matched person is named once above their films, not on every row.

Owner, on a page of eighty "cage" results: *"that way you don't have 10 Nicolas
Cage lines."* Measured on the real library those eighty resolve to 65 Nicolas
Cage, 4 Weston Cage, 3 Finn McCager Higgins, 2 David Beaucage — and that is the
point of the sub-heading, not tidiness: a weak match becomes self-evidently weak
by sitting in a small, NAMED group, instead of being one of eighty rows that
each need explaining.

The rows must be REORDERED for this to be honest. They arrive in relevance order
— tier, then title — which scatters one actor's films across the section, and a
heading over scattered rows is a lie. So the section groups by person first
seen, then by original relevance position inside each run.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.gui.channel_list_roles import (
    CHANNEL_HTML_ROLE, ROW_KIND_ROLE, SECTION_TYPE_ROLE, TITLE_ROLE,
)


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dto(name, section_key=None, media_type="movie", match_person=None):
    return ChannelListDTO(
        id=str(uuid.uuid4()), name=name, media_type=media_type,
        provider_id="p1", is_favorite=False, category=None, quality=None,
        detected_prefix=None, detected_region=None, detected_quality=None,
        detected_year=None, detected_title=name,
        section_key=section_key, match_person=match_person,
    )


def _model(qapp, dtos, search="cage"):
    from metatv.gui.channel_list_model import ChannelListModel
    model = ChannelListModel()
    model.set_channels(
        dtos, provider_icon_map={}, show_provider_icon=False, has_more=False,
        query_params={"search_query": search}, favorite_icon="★",
        unfavorite_icon="☆",
    )
    return model


def _rows(model):
    """``[(kind, label_or_title), …]`` for every display row, top to bottom.

    Channel rows report TITLE_ROLE, not DisplayRole: the latter is the composed
    row text and carries the favourite glyph and separators, which is a
    different assertion than "which rows are under which heading".
    """
    out = []
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        kind = idx.data(ROW_KIND_ROLE)
        if kind == "header":
            out.append(("header", idx.data(SECTION_TYPE_ROLE)))
        elif kind == "person":
            out.append(("person", idx.data(SECTION_TYPE_ROLE)))
        else:
            out.append(("channel", idx.data(TITLE_ROLE)))
    return out


# Deliberately INTERLEAVED, the way relevance order really delivers them:
# Cage, Beaucage, Cage, Beaucage. A layout that trusted arrival order would
# emit four sub-headings.
def _interleaved():
    return [
        _dto("Con Air", "cast", match_person="Nicolas Cage"),
        _dto("Alpha Film", "cast", match_person="David Beaucage"),
        _dto("Face Off", "cast", match_person="Nicolas Cage"),
        _dto("Beta Film", "cast", match_person="David Beaucage"),
    ]


def test_a_person_is_named_once_above_their_own_films(qapp):
    """The owner's requirement, against the order the query really returns."""
    rows = _rows(_model(qapp, _interleaved()))

    assert rows == [
        ("header", "cast"),
        ("person", "Nicolas Cage"),
        ("channel", "Con Air"),
        ("channel", "Face Off"),
        ("person", "David Beaucage"),
        ("channel", "Alpha Film"),
        ("channel", "Beta Film"),
    ], rows


def test_runs_are_ordered_by_first_appearance_not_alphabetically(qapp):
    """The persons are not ranked against each other, so nothing may re-rank them.

    Alphabetical would put David Beaucage — two weak partial matches — above
    Nicolas Cage, who is the reason the search returned anything. First
    appearance preserves the relevance the query already computed.
    """
    people = [label for kind, label in _rows(_model(qapp, _interleaved()))
              if kind == "person"]
    assert people == ["Nicolas Cage", "David Beaucage"], people


def test_rows_with_no_matched_person_are_not_given_a_heading(qapp):
    """Mirror-not-cage: a row nobody can label still gets a row."""
    rows = _rows(_model(qapp, [
        _dto("Cage", "title"),                                  # a title match
        _dto("Unlabelled", "cast", match_person=None),          # cast, no name
        _dto("Con Air", "cast", match_person="Nicolas Cage"),
    ]))

    assert ("person", None) not in rows
    assert ("channel", "Unlabelled") in rows
    # The unlabelled row sorts BEFORE the named runs, so it is never mistaken
    # for one of the named person's films.
    kinds = [k for k, _ in rows]
    assert kinds.index("channel") < kinds.index("person")


def test_a_subheading_is_not_selectable(qapp):
    """Clicking it must not drag the details pane to nothing."""
    from PyQt6.QtCore import Qt
    model = _model(qapp, _interleaved())
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        if idx.data(ROW_KIND_ROLE) == "person":
            assert not (model.flags(idx) & Qt.ItemFlag.ItemIsSelectable), (
                "a sub-heading is selectable")
            return
    pytest.fail("no sub-heading row was produced")


def test_a_subheading_renders_the_html_the_delegate_paints(qapp):
    """Quieter than a section header, and through the delegate's own role.

    The section header is bold ``COLOR_TEXT_HI``; a sub-heading is the second
    level and must not compete with it — two equal headings read as two lists.
    """
    from metatv.gui import theme as _theme
    model = _model(qapp, _interleaved())

    person_html = [model.index(r, 0).data(CHANNEL_HTML_ROLE)
                   for r in range(model.rowCount())
                   if model.index(r, 0).data(ROW_KIND_ROLE) == "person"]
    assert person_html, "no sub-heading rendered"
    for html in person_html:
        # The NAME takes the bright ramp, and that is the same two-tone rule as
        # the section header rather than an exception to it: the emphasis goes
        # on the VARIABLE half, and for a person the name is what varies while
        # the film count is incidental. COLOR_TEXT_LOW is also barred outright —
        # measured 4.15:1, under the 4.5 text floor in four of six palettes.
        assert _theme.COLOR_TEXT_HI in html, (
            f"the person's name is not on the bright ramp: {html}")
        # No assertion about COLOR_TEXT_LOW: it and COLOR_TEXT are the SAME
        # value (#a7b2c0 in this palette), so "not the low ramp" is not a
        # question this can ask. Logged as D30 — two names for one colour.
        assert _theme.COLOR_TEXT in html, (
            f"the count is not on the secondary ramp: {html}")
        assert html.count("<span") == 2, f"a sub-heading is two tones: {html}"


def test_the_section_count_is_results_not_display_rows(qapp):
    """"Cast & Crew (4)" means four films, not four films plus two names."""
    from PyQt6.QtCore import Qt
    model = _model(qapp, _interleaved())
    header = next(model.index(r, 0) for r in range(model.rowCount())
                  if model.index(r, 0).data(ROW_KIND_ROLE) == "header")

    assert "(4)" in header.data(Qt.ItemDataRole.DisplayRole)
    assert model.loaded_count() == 4, "sub-headings are not results"


def test_a_second_page_joins_the_run_it_belongs_to(qapp):
    """Scrolling must not produce a second "Nicolas Cage" heading.

    A row fetched on page 2 for a person who already has a run belongs INSIDE
    that run — which is an insert in the middle, so the naive "append at the end
    of the section" is silently wrong for exactly the section that has runs.
    """
    model = _model(qapp, _interleaved())
    model.append_page(
        [_dto("Raising Arizona", "cast", match_person="Nicolas Cage")],
        has_more=False, generation=model.generation,
    )

    rows = _rows(model)
    assert [label for kind, label in rows if kind == "person"] == [
        "Nicolas Cage", "David Beaucage"], rows
    # It joined the existing run rather than starting a second one.
    titles = [label for kind, label in rows if kind == "channel"]
    assert titles == ["Con Air", "Face Off", "Raising Arizona",
                      "Alpha Film", "Beta Film"], titles


# ── collapsing a person's run ───────────────────────────────────────────────
#
# Owner, watching a "nicholas" search fill the screen: "I can already see we
# need to be able to collapse every cast and crew subheader as well."

def test_a_person_folds_their_own_films_and_keeps_their_name(qapp):
    """The name stays and keeps its count — that is what the count is FOR.

    Straight from the settled GroupHeading grammar: the count is "shown even
    when the group is collapsed — with the rows hidden it is the only thing
    describing what is in there."
    """
    from PyQt6.QtCore import Qt
    model = _model(qapp, _interleaved())
    assert _rows(model).count(("channel", "Con Air")) == 1

    model.toggle_person_collapsed("Nicolas Cage")
    rows = _rows(model)

    assert ("person", "Nicolas Cage") in rows, "the name must survive the fold"
    assert ("channel", "Con Air") not in rows
    assert ("channel", "Face Off") not in rows
    assert ("channel", "Alpha Film") in rows, "it folded somebody else's films"

    header = next(model.index(r, 0) for r in range(model.rowCount())
                  if model.index(r, 0).data(ROW_KIND_ROLE) == "person"
                  and model.index(r, 0).data(SECTION_TYPE_ROLE) == "Nicolas Cage")
    assert "2" in header.data(Qt.ItemDataRole.DisplayRole), (
        "a collapsed run must still say how many films are in it")


def test_unfolding_puts_the_films_back(qapp):
    model = _model(qapp, _interleaved())
    before = _rows(model)
    model.toggle_person_collapsed("Nicolas Cage")
    model.toggle_person_collapsed("Nicolas Cage")
    assert _rows(model) == before


def test_the_section_count_ignores_a_folded_run(qapp):
    """Folding is not filtering — the films are still results."""
    model = _model(qapp, _interleaved())
    model.toggle_person_collapsed("Nicolas Cage")
    assert model.loaded_count() == 4
