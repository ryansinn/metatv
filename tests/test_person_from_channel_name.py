"""A row that matched on its NAME still gets named in Cast & Crew.

Owner, searching "nicolas cage": *"no actor title in cast and crew… but wait,
scroll to the VERY bottom, and there's one with 3 titles."* **65 of 68 rows had
no heading.**

Measured on the live library for that term: **182** channels carry it in
``ChannelDB.name``, **8** in ``detected_title``, and only a handful in
``metadata.cast``. Providers put the cast in the title —
``'EN - Arcadian 4K (2024) NICOLAS CAGE'`` parses to ``'Arcadian'`` — and
``8MM 1`` has neither cast nor director yet still matched.

Three pieces disagreed about one row: the predicate matches ``name``,
``section_for_title`` reads ``detected_title`` (so Cast & Crew, which is
RIGHT — the provider is telling us he is in it), and ``matched_persons_map``
reads only metadata, which those rows do not have.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, MetadataDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel_list_rows import rows_to_dtos
from metatv.core.repositories.search_ranking import canonical_person
from tests.conftest import make_channel


@pytest.fixture
def repos(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'names.db'}")
    db.create_tables()
    with db.session_scope() as session:
        session.add(ProviderDB(id="test", name="T", type="xtream",
                               url="http://x.example.com", is_active=True))
        # One row WITH metadata, spelling the name properly.
        md = MetadataDB(id="md-1", title="Leaving Las Vegas",
                        cast=[{"name": "Nicolas Cage", "character": None}])
        session.add(md)
        session.flush()
        meta_row = make_channel(session, "EN - Leaving Las Vegas (1995)",
                                media_type="movie",
                                detected_title="Leaving Las Vegas")
        meta_row.metadata_id = md.id
        # Two rows with NO metadata at all, the actor only in the raw name —
        # exactly the shape 8MM 1 and Arcadian have on the real library.
        name_row = make_channel(session, "EN - Arcadian 4K (2024) NICOLAS CAGE",
                                media_type="movie", detected_title="Arcadian")
        name_row2 = make_channel(session, "EN - 8MM 1 (1999) NICOLAS CAGE",
                                 media_type="movie", detected_title="8MM 1")
        session.flush()
        yield RepositoryFactory(session), [meta_row, name_row, name_row2]


def test_a_name_matched_row_is_headed_by_the_person(repos):
    """The regression: these three arrived as one labelled row and two orphans."""
    factory, rows = repos
    by_title = {d.detected_title: d for d in rows_to_dtos(factory, rows, "nicolas cage")}

    assert by_title["Leaving Las Vegas"].match_person == "Nicolas Cage"
    assert by_title["Arcadian"].match_person == "Nicolas Cage", (
        "a row whose provider put the actor in the TITLE still matched on him "
        "and must say so")
    assert by_title["8MM 1"].match_person == "Nicolas Cage", (
        "8MM 1 has no cast and no director on the real library — the name is "
        "the only evidence there is, and it is evidence")


def test_they_all_land_in_ONE_group(repos):
    """The point of it: one heading, not one plus sixty-five orphans."""
    factory, rows = repos
    people = {d.match_person for d in rows_to_dtos(factory, rows, "nicolas cage")}
    assert people == {"Nicolas Cage"}, people


def test_the_spelling_follows_whatever_metadata_already_uses(repos):
    """Otherwise "NICOLAS CAGE" sits beside "Nicolas Cage" as two groups."""
    assert canonical_person("nicolas cage", {"a": "Nicolas Cage"}) == "Nicolas Cage"
    assert canonical_person("NICOLAS CAGE", {"a": "Nicolas Cage"}) == "Nicolas Cage"
    # No metadata anywhere on the page → title case, which is what the provider
    # blobs and TMDb both produce.
    assert canonical_person("nicolas cage", {}) == "Nicolas Cage"
    assert canonical_person("", {"a": "X"}) is None


def test_a_row_that_did_not_match_on_its_name_is_left_alone(repos):
    """The fallback may not label a row it has no evidence for."""
    factory, rows = repos
    dtos = rows_to_dtos(factory, rows, "arcadian")
    by_title = {d.detected_title: d for d in dtos}
    # "arcadian" is in the title, so this is a Titles match with no person.
    assert by_title["Arcadian"].section == "title"
    assert by_title["Arcadian"].match_person is None
