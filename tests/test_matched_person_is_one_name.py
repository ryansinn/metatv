"""A matched director value is reduced to the name that actually matched.

Owner, from a search for "Strong": *"it's clearly matching Carley Armstrong for
Kraven the Hunter … but listing the entire cast."* The heading read
``Paula Casarin, Carley Armstrong, Andrea Trigo, Martina Vazzoler, J.C. Chandor``.

``metadata.director`` is a plain TEXT column, not JSON, so ``LIKE '%strong%'``
matches the whole VALUE and the whole value was then returned as "the person".

Measured on the live library: **74,462** populated director rows, **25,573
(34.3%)** containing a comma — and many are not people at all:
``"Anna Sanders Films, Burning Blue, Illuminations Films, ZDF, ARTE"``.
Separators counted in that column: comma 13,909 · ``&`` 36 · ``/`` 27 · Arabic
comma 7.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, MetadataDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel_list_rows import rows_to_dtos
from metatv.core.repositories.search_ranking import (
    best_person_part, matched_persons_map,
)
from tests.conftest import make_channel

#: The exact value from the owner's screenshot.
KRAVEN = ("Paula Casarin, Carley Armstrong, Andrea Trigo, "
          "Martina Vazzoler, J.C. Chandor")


def test_the_owners_case_returns_one_name(qapp=None):
    """Not the list. This is the whole bug, in one assertion."""
    assert best_person_part(KRAVEN, "strong") == "Carley Armstrong"


def test_a_production_company_list_is_reduced_the_same_way():
    """These are not even people, and one of them still has to be the answer."""
    value = ("Anna Sanders Films, Burning Blue, Illuminations Films, "
             "Kick the Machine, Piano, The Match Factory, ZDF, ARTE")
    assert best_person_part(value, "match") == "The Match Factory"


@pytest.mark.parametrize("sep", [",", "&", "/", ";", "،"])
def test_every_measured_separator_splits(sep):
    """The set is measured from the real column, not guessed."""
    value = f"Ana Lily Amirpour{sep} Mark Strong{sep} Jane Doe"
    assert best_person_part(value, "strong") == "Mark Strong"


def test_an_exact_name_beats_a_longer_one_containing_it():
    """"Strong" prefers Mark Strong over Armstrong when a value holds both."""
    assert best_person_part("Carley Armstrong, Mark Strong", "strong") == "Mark Strong"
    # Whole word beats substring even when the substring match is shorter.
    assert best_person_part("Strongman, Mark Strong", "strong") == "Mark Strong"


def test_a_single_name_passes_through_untouched():
    """Cast names arrive already separated from json_each."""
    assert best_person_part("Nicolas Cage", "cage") == "Nicolas Cage"


def test_a_value_with_no_matching_part_is_rejected():
    """So the caller can fall through to the next candidate instead of lying."""
    assert best_person_part("Alice Smith, Bob Jones", "strong") is None
    assert best_person_part("", "strong") is None
    assert best_person_part("Mark Strong", "") is None


@pytest.fixture
def repos(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'director.db'}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ProviderDB(id="test", name="T", type="xtream",
                               url="http://x.example.com", is_active=True))
        md = MetadataDB(id="md-1", title="Kraven the Hunter", director=KRAVEN)
        session.add(md)
        session.flush()
        ch = make_channel(session, "EN - Kraven the Hunter (2024)",
                          media_type="movie", detected_title="Kraven the Hunter")
        ch.metadata_id = md.id
        session.flush()
        yield RepositoryFactory(session), [ch]


def test_end_to_end_through_the_real_query(repos):
    """Driven through matched_persons_map, not just the helper."""
    factory, rows = repos
    found = matched_persons_map(factory.session, [rows[0].id], "strong")
    assert found == {rows[0].id: "Carley Armstrong"}, found


def test_the_row_reaches_the_list_with_one_name_on_it(repos):
    """And the DTO the list renders carries that, not the list."""
    factory, rows = repos
    dto = rows_to_dtos(factory, rows, "strong")[0]
    assert dto.match_person == "Carley Armstrong"
    assert "," not in (dto.match_person or ""), (
        "the heading is a person, not a credits roll")
