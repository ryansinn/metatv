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
    # A row can match on its NAME rather than on metadata, because providers put
    # the cast in the title. Those rows have no cast row to name them, so the
    # term itself is the honest heading — see canonical_person, and the 182-vs-8
    # measurement behind it.
    from_name = search_ranking.canonical_person(term, persons) if term else None

    def _person(ch, section):
        # Only ever in Cast & Crew. A TITLES row matched on its own title, and
        # the term is in its raw name BECAUSE the title is in its raw name — so
        # the fallback would head "Arcadian" with "Arcadian" when someone
        # searches for the film rather than the actor.
        if section != search_ranking.SECTION_CAST:
            return None
        found = persons.get(ch.id)
        if found:
            return found
        if from_name and term.lower() in (ch.name or "").lower():
            return from_name
        return None

    def _dto(c):
        section = (search_ranking.section_for_title(
            c.detected_title or c.name, term) if term else None)
        person = _person(c, section)
        return ChannelListDTO.from_orm(
            c,
            user_rating=ratings_map.get(c.id, 0),
            reliability_state=reliability_map.get(c.id, "ok"),
            section_key=section,
            match_person=person,
            # The rung this row sits on IN ITS OWN SECTION — the title in
            # Titles, the matched person in Cast & Crew. Scoring both on the
            # title made every cast row tier 4 and emptied that section the
            # moment anyone pressed Whole.
            match_tier=(search_ranking.tier_for_row(
                c.detected_title or c.name, person, section, term)
                if term else 0),
        )

    return [_dto(c) for c in rows]
