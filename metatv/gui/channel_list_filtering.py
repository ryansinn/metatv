"""Narrowing the rows already on screen, without going back to the database.

The search box asks the DATABASE a question — 785,551 rows, in SQL. This asks a
question of the ANSWER: type a few characters and keep only the rows that carry
them somewhere. Owner: *"a text field that the user can just enter in a simple
set of characters to pattern match within the search results … the way it works
on Discover and Recipe."*

Copied from ``discover_view``'s shelf filter, including the part that is easy to
get wrong: it is **not persisted**. That module's own note — "a filter restored
at launch would present an almost-empty Discover with no obvious cause, which
reads as a broken app rather than a saved preference" — applies here with more
force, because an empty result list looks exactly like a broken search.

**What it matches** is every field the row shows, not just the title: the owner
picked that over title-only, and the reason is that a row's year, genre,
category and matched person are all on screen and all things a person will
reasonably type. The cost is that "2024" and "drama" filter too, which is
surprising only until you have done it once.

**What it does NOT do** is re-query, so it can only narrow what is loaded. With
a search active that is the whole result set. Browsing with an empty box it is
one page of many, and the field says so rather than pretending otherwise.
"""

from __future__ import annotations

from metatv.core.repositories.dtos import ChannelListDTO


def haystack(dto: ChannelListDTO) -> str:
    """Everything about *dto* a person can see, lowercased, as one string.

    Built from the DTO's own fields rather than the delegate's composed row: the
    delegate's string carries glyphs and separators, so matching it would let a
    stray "·" or a favourite star answer a filter.
    """
    parts = (
        dto.detected_title, dto.name, dto.match_person, dto.category,
        dto.detected_year, dto.detected_region, dto.detected_quality,
        dto.detected_prefix, dto.media_type,
    )
    extra = getattr(dto, "detected_genres", None) or ()
    if isinstance(extra, str):
        extra = (extra,)
    return " ".join(str(p) for p in (*parts, *extra) if p).lower()


def matches(dto: ChannelListDTO, needle: str) -> bool:
    """Whether *dto* survives the sub-filter.

    Every whitespace-separated token must appear somewhere, in any order — so
    "cage 2024" finds a 2024 Cage film without the user having to guess which
    field comes first. An empty needle keeps everything.
    """
    tokens = (needle or "").casefold().split()
    if not tokens:
        return True
    hay = haystack(dto)
    return all(t in hay for t in tokens)


def visible_indices(dtos, needle: str) -> list[int]:
    """Indices of the rows that survive — the one list both display modes use.

    Flat mode reads it directly; grouped mode buckets from it. One definition,
    so a row cannot be filtered out of the list and still counted by a heading.
    """
    if not (needle or "").strip():
        return list(range(len(dtos)))
    return [i for i, d in enumerate(dtos) if matches(d, needle)]
