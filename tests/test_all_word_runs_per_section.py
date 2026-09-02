"""The All/Word ladder runs on the field that put the row in its section.

The artifact is explicit: *"the ladder runs inside each section, so Nicolas Cage
beats Beaucage within Cast & Crew, just as Tron beats Astronaut within Titles."*

Scoring every row on its TITLE instead made every Cast & Crew row tier 4 —
a cast row's title never contains the term — so pressing ``Word`` on that
section **emptied it**. Found by the owner asking whether the control should be
``All | Whole | Part``; it should not, and this is why it looked like it might
need a third state.

``All`` is a SUPERSET of ``Word`` (tiers 0-3 against 0-2), which is the other
half of that answer and also why the halves are named as they are. They were
``Whole | Part`` first, and "Part" said the opposite of what it does — it reads
as "only partial matches" while meaning whole AND partial. Owner: *"Part
basically includes Whole, and Whole is more restrictive, right? … so Part
should be All and Whole should be Word."*
"""

from __future__ import annotations

import uuid

import pytest

from metatv.core.repositories.dtos import ChannelListDTO
from metatv.core.repositories.search_ranking import (
    SECTION_CAST, SECTION_TITLE, WORD_TIERS, tier_for_row,
)
from metatv.gui.channel_list_roles import ROW_KIND_ROLE, TITLE_ROLE


@pytest.fixture()
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _dto(title, section, person=None, term="cage"):
    return ChannelListDTO(
        id=str(uuid.uuid4()), name=title, media_type="movie", provider_id="p",
        is_favorite=False, category=None, quality=None, detected_prefix=None,
        detected_region=None, detected_quality=None, detected_year=None,
        detected_title=title, section_key=section, match_person=person,
        match_tier=tier_for_row(title, person, section, term),
    )


def _corpus():
    return [
        _dto("The Cage", SECTION_TITLE),               # whole word in title
        _dto("Birdcage", SECTION_TITLE),               # inside a longer word
        _dto("Con Air", SECTION_CAST, "Nicolas Cage"),   # whole word in the NAME
        _dto("Bon Cop Bad Cop", SECTION_CAST, "David Beaucage"),  # inside a name
    ]


def _model(qapp, dtos):
    from metatv.gui.channel_list_model import ChannelListModel
    m = ChannelListModel()
    m.set_channels(dtos, provider_icon_map={}, show_provider_icon=False,
                   has_more=False, query_params={"search_query": "cage"},
                   favorite_icon="*", unfavorite_icon="o")
    return m


def _titles(model):
    return [model.index(r, 0).data(TITLE_ROLE)
            for r in range(model.rowCount())
            if model.index(r, 0).data(ROW_KIND_ROLE) not in ("header", "person")]


def test_a_cast_row_is_ranked_on_the_PERSON_not_the_title():
    """The bug, at its source. "Con Air" contains no "cage"; Nicolas Cage does."""
    assert tier_for_row("Con Air", "Nicolas Cage", SECTION_CAST, "cage") == 2
    assert tier_for_row("Bon Cop Bad Cop", "David Beaucage", SECTION_CAST,
                        "cage") == 3
    # Scoring it on the title is what produced 4, and 4 is in no rung the
    # control offers.
    assert tier_for_row("Con Air", None, SECTION_TITLE, "cage") == 4


def test_a_title_row_is_still_ranked_on_the_title():
    assert tier_for_row("The Cage", None, SECTION_TITLE, "cage") == 2
    assert tier_for_row("Birdcage", None, SECTION_TITLE, "cage") == 3


def test_an_unrankable_cast_row_is_kept_as_the_loosest_match():
    """Mirror, never cage: a row nobody can rank still gets a row.

    These are real — a row whose provider put the actor in the channel NAME has
    no metadata person to rank, and dropping it from Whole would hide a genuine
    result behind a control that says it only tightens word matching.
    """
    assert tier_for_row("8MM 1", None, SECTION_CAST, "cage") == 3


def test_word_no_longer_empties_the_cast_section(qapp):
    """The regression, end to end. It returned an empty section."""
    model = _model(qapp, _corpus())
    model.set_section_word_only("cast", True)

    kept = _titles(model)
    assert "Con Air" in kept, (
        "Word emptied Cast & Crew — every row scored 4 because the ladder ran "
        "on the title, which a cast row's title can never satisfy")
    assert "Bon Cop Bad Cop" not in kept, "Beaucage is a partial match"


def test_each_section_narrows_independently(qapp):
    """Whole on one leaves the other exactly as it was."""
    model = _model(qapp, _corpus())
    model.set_section_word_only("title", True)
    kept = _titles(model)

    assert kept.count("The Cage") == 1 and "Birdcage" not in kept
    assert "Con Air" in kept and "Bon Cop Bad Cop" in kept, (
        "narrowing Titles changed Cast & Crew")


def test_all_is_a_superset_of_word(qapp):
    """The property that makes a third state redundant — and named the halves."""
    model = _model(qapp, _corpus())
    all_matches = set(_titles(model))               # default: All
    model.set_section_word_only("title", True)
    model.set_section_word_only("cast", True)
    word = set(_titles(model))

    assert word < all_matches, (
        f"Word must be strictly narrower than All: {word} vs {all_matches}")
    assert 3 not in WORD_TIERS and {0, 1, 2} == set(WORD_TIERS)
