"""A search groups itself — Titles above Cast & Crew — and clearing it restores
whatever the user had.

The data half (which section a row belongs in, and who matched) is
``tests/test_search_sections.py``. This is the render half: given rows that
already carry a ``section_key``, does the list actually project them into two
labelled sections, in the right order, without touching the user's Group-by-type
checkbox?

Three things are pinned here, and each is a bug that was live before this file:

* **Order.** ``title`` and ``cast`` used to fall through to the alphabetically
  sorted "extras" branch, which renders *Cast & Crew* ABOVE *Titles* — exactly
  backwards, since a title match is the stronger claim and the reason the row is
  on screen at all.
* **A search groups on its own.** Grouping was opt-in only, so the sections
  existed and nobody ever saw them.
* **It is not a preference change.** Searching must not silently tick
  Group-by-type, and clearing the search must put the list back the way the user
  left it — including back to a FLAT list, which is the default.
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO


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


def _model(qapp):
    from metatv.gui.channel_list_model import ChannelListModel
    return ChannelListModel()


def _load(model, dtos, *, search=None):
    model.set_channels(
        dtos, provider_icon_map={}, show_provider_icon=False, has_more=False,
        query_params={"search_query": search}, favorite_icon="★",
        unfavorite_icon="☆",
    )


def _headers(model):
    """The (display text, section_key) of every header row, top to bottom.

    The text is the FULL rendered header — glyph, label and count — so a
    label assertion below also proves the count is being composed.
    """
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE, SECTION_TYPE_ROLE
    out = []
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        if idx.data(ROW_KIND_ROLE) == "header":
            out.append((idx.data(Qt.ItemDataRole.DisplayRole),
                        idx.data(SECTION_TYPE_ROLE)))
    return out


# The corpus every ordering test uses: cast rows are given FIRST, so a test that
# passes on load order rather than on SECTION_ORDER fails here.
def _mixed():
    return [
        _dto("Leaving Las Vegas", "cast", match_person="Nicolas Cage"),
        _dto("Con Air", "cast", match_person="Nicolas Cage"),
        _dto("Cage", "title"),
    ]


def _mixed_by_id(model):
    """The DTOs the model is holding — its own record of what it was given."""
    return list(model._channels)


def test_a_search_groups_without_the_checkbox(qapp):
    """Grouping is opt-in; a search opts in for you, for this query only."""
    model = _model(qapp)
    _load(model, _mixed(), search="cage")

    assert model.is_grouped, "a search must group its results"
    assert [t for t, _ in _headers(model)] == ["⌄ Titles (1)", "⌄ Cast & Crew (2)"]


def test_titles_render_above_cast_and_crew(qapp):
    """The regression that made this file: alphabetical order reverses these."""
    model = _model(qapp)
    _load(model, _mixed(), search="cage")

    keys = [key for _, key in _headers(model)]
    assert keys == ["title", "cast"], (
        "Titles must render first — it is the stronger match and the reason "
        f"the row is on screen. Got {keys}."
    )
    # And each row sits under its OWN header, not merely in the right order —
    # walk the list carrying the last header forward, the way an eye does, and
    # compare against the section the row itself claims.
    from PyQt6.QtCore import Qt
    from metatv.gui.channel_list_model import ROW_KIND_ROLE, SECTION_TYPE_ROLE
    by_id = {d.id: d.section for d in _mixed_by_id(model)}
    heading, seen = None, []
    for r in range(model.rowCount()):
        idx = model.index(r, 0)
        if idx.data(ROW_KIND_ROLE) == "header":
            heading = idx.data(SECTION_TYPE_ROLE)
            continue
        seen.append((heading, by_id[idx.data(Qt.ItemDataRole.UserRole)]))
    assert seen == [("title", "title"), ("cast", "cast"), ("cast", "cast")], (
        f"a row is filed under the wrong heading: {seen}")


def test_clearing_the_search_restores_a_flat_list(qapp):
    """Flat is the default, so the search must hand it back."""
    model = _model(qapp)
    _load(model, _mixed(), search="cage")
    assert model.is_grouped

    _load(model, [_dto("Anything")], search=None)
    assert not model.is_grouped, "clearing the search left grouping stuck on"
    assert _headers(model) == []


def test_clearing_the_search_restores_group_by_type(qapp):
    """And when the user DID tick the box, they get their sections back."""
    model = _model(qapp)
    model.set_grouped(True)
    _load(model, _mixed(), search="cage")
    assert [k for _, k in _headers(model)] == ["title", "cast"]

    _load(model, [_dto("A Film", media_type="movie"),
                  _dto("A Show", media_type="series")], search=None)
    assert [k for _, k in _headers(model)] == ["movie", "series"]


def test_searching_does_not_tick_the_users_checkbox(qapp):
    """The preference is theirs; a search borrows the view, it does not set it.

    Asserted on the attribute the host persists from, because the visible
    symptom — Group-by-type silently checked after a search — only appears one
    restart later, when the model is built from a config that was written wrong.
    """
    model = _model(qapp)
    _load(model, _mixed(), search="cage")

    assert model._group_by_type is False


def test_the_count_a_user_sees_does_not_include_the_headers(qapp):
    """The bug the sections created, and the reason for ``loaded_count()``.

    ``rowCount()`` is Qt's DISPLAY count — it has to include the header rows,
    because Qt paints them. Every "Showing N channels" in the app read it, on a
    comment that said in so many words *"rowCount() equals the number of real
    channel rows"*. That was true while grouping was an opt-in checkbox almost
    nobody ticked. The moment a search groups, three results start reporting as
    five, and it is the search box — the most-used control in the app — that
    does it.
    """
    model = _model(qapp)
    _load(model, _mixed(), search="cage")

    assert model.rowCount() == 5, "3 channels + 2 headers is what Qt paints"
    assert model.loaded_count() == 3, (
        "the count shown to a user must exclude section headers")

    # And it stays honest ungrouped, so the two are interchangeable there —
    # which is exactly why the wrong one went unnoticed for so long.
    _load(model, _mixed(), search=None)
    assert model.rowCount() == model.loaded_count() == 3
