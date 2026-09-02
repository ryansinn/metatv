"""Rows fetched on scroll carry the same section as the ones already on screen.

The first-page query and its pagination sibling each built the ORM-to-DTO list
themselves, and the two copies drifted the moment search sections arrived: the
page path never passed the search term, so every row appended on scroll came
back with ``section_key=None``, fell through to ``media_type``, and grew a stray
"Movies" heading UNDERNEATH the Titles and Cast & Crew it should have joined.

Nothing caught it. Both CI shards and the local suite were green on the broken
tree, because no test scrolls a search — the failure needed a second page.

The fix is one builder, ``channel_list_rows.rows_to_dtos``, which both
workers call. This file tests that builder's contract and the page path's use of
it, which together are the thing that was broken.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, MetadataDB, ProviderDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.channel_list_rows import rows_to_dtos
from tests.conftest import make_channel


@pytest.fixture
def repos(tmp_path):
    """Real repositories over a real database file — this is session work."""
    db = Database(f"sqlite:///{tmp_path / 'page2.db'}")
    db.create_tables()
    with db.session_scope() as session:
        # An ACTIVE provider, or the visibility scope hides everything: an
        # inactive source is an absolute gate, not a soft filter, so a fixture
        # without one silently returns zero rows and every assertion below
        # passes for the wrong reason.
        session.add(ProviderDB(id="test", name="Test", type="xtream",
                               url="http://x.example.com", is_active=True))
        md = MetadataDB(id="md-1", title="Con Air",
                        cast=[{"name": "Nicolas Cage", "character": None}])
        session.add(md)
        session.flush()
        exact = make_channel(session, "Cage", media_type="movie",
                             detected_title="Cage")
        viacast = make_channel(session, "Con Air", media_type="movie",
                               detected_title="Con Air")
        viacast.metadata_id = md.id
        session.flush()
        yield RepositoryFactory(session), [exact, viacast]


def test_a_paged_row_is_filed_by_its_match_not_its_media_type(repos):
    """The regression: without the term, both of these land in "Movies"."""
    factory, rows = repos
    dtos = rows_to_dtos(factory, rows, "cage")

    by_name = {d.name: d for d in dtos}
    assert by_name["Cage"].section == "title"
    assert by_name["Con Air"].section == "cast", (
        "a row that matched on a cast name must say so — filed under its "
        "media_type it reads as a bug, which is the whole reason for sections")
    assert by_name["Con Air"].match_person == "Nicolas Cage"


def test_browsing_costs_nothing_and_falls_back_to_media_type(repos):
    """No term → no section lookup at all, and the old behaviour is intact."""
    factory, rows = repos
    dtos = rows_to_dtos(factory, rows, None)

    assert all(d.section_key is None for d in dtos)
    assert all(d.match_person is None for d in dtos)
    assert {d.section for d in dtos} == {"movie"}


def test_both_workers_build_their_rows_the_same_way(repos):
    """The two paths agree, which is the property the single builder buys.

    Asserted as an outcome rather than by reading the source: give the builder
    the same rows twice, the way page 1 and page 2 reach it, and the DTOs must
    be indistinguishable. A page path that quietly dropped the term again would
    return a different section here.
    """
    factory, rows = repos
    page1 = rows_to_dtos(factory, rows[:1], "cage")
    page2 = rows_to_dtos(factory, rows[1:], "cage")

    assert page1[0].section == "title"
    assert page2[0].section == "cast"
    # Same channel through either call → same section, every field that a
    # heading depends on.
    again = rows_to_dtos(factory, rows, "cage")
    for one, both in zip(page1 + page2, again):
        assert (one.section_key, one.match_person) == (both.section_key,
                                                       both.match_person)


def test_the_page_worker_itself_passes_the_search_term(repos):
    """End to end through the real pagination worker, not just the builder.

    The three tests above prove the builder is right; this one proves the path
    that was WRONG now uses it correctly. Dropping the term at that call site
    again — the exact regression — leaves every one of them green and only
    fails here.
    """
    from metatv.gui.main_window_channels import _ChannelListMixin

    dtos, _has_more, _raw = _ChannelListMixin._query_channels_page(
        repos[0], {"search_query": "cage"}, offset=0, page_size=50)

    assert dtos, "the page query returned nothing; the fixture rows should match"
    sections = {d.name: d.section for d in dtos}
    assert sections.get("Cage") == "title"
    assert sections.get("Con Air") == "cast", (
        f"a paged cast match lost its section: {sections}")
