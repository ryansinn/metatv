"""ORM rows to list DTOs — the one place a channel crosses the worker boundary.

Lifted out of ``gui/main_window_channels`` because it never belonged there:
it takes a ``RepositoryFactory`` and returns frozen DTOs, touches no widget, no
signal and no Qt type at all. CLAUDE.md's layering rule is one-way — engine ←
control ← view — and a pure ORM-to-DTO mapping is engine work that had drifted
into the view.

The move also settles what the code-health ratchet was pointing at: the file it
came from is 2,240 lines and every search feature grows it, while this is 50
lines with one job.
"""

from __future__ import annotations

from metatv.core.repositories import search_ranking

def rows_to_dtos(repos, rows: list, search_query: str | None) -> list:
    """ORM rows → DTOs: the one place a channel crosses the worker boundary.

    The first-page query and its pagination sibling each built this list, and
    they drifted the moment search sections arrived — page 2 of a search came
    back with no ``section_key``, so every row appended on scroll fell into a
    MEDIA-TYPE bucket and grew a stray "Movies" heading underneath the Titles
    and Cast & Crew it should have joined. Two copies of a mapping is how that
    happens; one is how it stops.

    ``search_query`` is None when just browsing, and the section and person
    lookups are then skipped entirely rather than run against an empty term.
    """
    from metatv.core.repositories.dtos import ChannelListDTO

    term = (search_query or "").strip()
    ratings_map = repos.ratings.get_all_map()
    reliability_map = repos.stream_retry.get_reliability_map()
    # One batch query for the whole page, never N+1, and skipped without a term.
    persons = search_ranking.matched_persons_map(
        repos.session, [c.id for c in rows], term) if term else {}
    return [
        ChannelListDTO.from_orm(
            c,
            user_rating=ratings_map.get(c.id, 0),
            reliability_state=reliability_map.get(c.id, "ok"),
            section_key=(search_ranking.section_for_title(
                c.detected_title or c.name, term) if term else None),
            match_person=persons.get(c.id),
            # The rung this row sits on — what a Whole/Part control filters.
            match_tier=(search_ranking.tier_for_title(
                c.detected_title or c.name, term) if term else 0),
        )
        for c in rows
    ]
