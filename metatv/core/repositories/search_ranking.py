"""How well a row matches a search term — the ORDER BY, not the WHERE.

Its own module because ``repositories/channel.py`` is baselined at 3,033 lines
and shrink-only; adding this to it blew the ratchet by 106 lines. The split is
also the honest one: the predicate decides WHICH rows match and lives beside
the query builders, while this decides what ORDER they come back in and is
pure expression-building with no session and no repository.

Measured on the owner's library, 2026-09-02. Searching "Tron" returned 788
channels ordered by ``ChannelDB.name`` — alphabetically — so
``24/7 THE ASTRONAUT WIVES CLUB`` outranked ``Tron`` and the 12 rows whose
title is exactly "Tron" were unreachable. Owner: *"it seems like Tron shows a
ton of stuff but not Tron ... exact matches should be shown first, no?"*
"""

from __future__ import annotations

from sqlalchemy import case, func, literal

from metatv.core.database import ChannelDB
from metatv.core.watchlist_matching import _escape_like


#: Characters that end a word for the purposes of search ranking.
#:
#: MEASURED, not guessed: scanning 200,000 real titles for every non-word
#: character sitting BETWEEN two word characters, this set covers **99.6%** of
#: them. Space dominates (409,611), then ``-`` (7,501), ``'`` (5,597),
#: ``:`` (4,853), ``/`` (3,232) and ``.`` (2,374).
#:
#: It exists because SQLite here has no ``REGEXP`` (checked), so the reference
#: definition in :mod:`metatv.core.watchlist_matching` — ``(?<!\w)term(?!\w)``,
#: "no word character butts up against this" — cannot be expressed in SQL. This
#: is the approximation, and ``tests/test_search_relevance_ranking.py`` measures
#: its disagreement with the Python definition over a real title corpus rather
#: than asserting they are identical, which they are not.
_WORD_SEPARATORS = " -':/.`\u2019&+,\u2026|()!?"

#: How many times to halve runs of spaces after flattening separators.
#: Four handles up to sixteen consecutive separators; real titles have at most
#: two or three (``"Tron: Legacy"``, ``"MLB 08 | Athletics x ..."``).
_SPACE_COLLAPSE_PASSES = 4


def _search_title_expr():
    """The title search ranks against: the stored title, else the raw name.

    Same expression ``get_keyword_counts`` already uses — the detected title is
    computed at ingestion (CLAUDE.md), so ranking reads it rather than parsing.
    """
    return func.coalesce(ChannelDB.detected_title, ChannelDB.name)


def _word_padded(expr):
    """``expr`` with separators flattened to spaces, space-padded and lowered.

    So ``'Tron: Legacy'`` becomes ``' tron  legacy '`` and a whole-word test is
    a plain ``LIKE '% tron %'`` — the only way to ask the question without
    ``REGEXP``.
    """
    out = func.lower(expr)
    for ch in _WORD_SEPARATORS:
        out = func.replace(out, ch, " ")

    # Collapse runs of spaces, or a multi-word term never matches across a
    # separator. "Tron: Legacy" flattens to "tron  legacy" — the colon becomes a
    # space NEXT TO the space already there — and a search for "tron legacy"
    # carries a single space, so it misses. Found by asking what the padding
    # actually does rather than trusting that it worked.
    #
    # Each pass halves a run, so _SPACE_COLLAPSE_PASSES handles runs up to
    # 2**passes. Four covers sixteen consecutive separators, which no real title
    # has; the alternative is REGEXP, which this SQLite does not have.
    #
    # The Python reference does the same thing a different way: watchlist_matching
    # joins a phrase's tokens with ``\s+`` so internal whitespace is elastic.
    for _ in range(_SPACE_COLLAPSE_PASSES):
        out = func.replace(out, "  ", " ")
    return " " + out + " "


def search_relevance_tier(search_term: str):
    """How well a row matches *search_term* — LOWER IS BETTER, for ``ORDER BY``.

    Measured on the owner's library, 2026-09-02. Searching "Tron" returned
    **788** channels ordered by ``ChannelDB.name`` — alphabetically — so
    ``24/7 THE ASTRONAUT WIVES CLUB`` outranked ``Tron``, and the **12** rows
    whose title is exactly "Tron" were unreachable. Owner: *"it seems that
    exact matches should be shown first, no?"*

    The tiers, and what each held for that search:

    ========  ==========================================  =======
    Tier      Meaning                                     "Tron"
    ========  ==========================================  =======
    0         the title IS the term                            12
    1         the title starts with it                        124
    2         it appears as a whole word in the title          33
    3         it appears anywhere in the title            the Astronauts
    4         the title does not match; something else    the Tronds
              did — cast, director, or an id
    ========  ==========================================  =======

    Tier 4 is where the cast/director arm of
    :func:`_channel_text_search_predicate` lands. That arm matches a substring
    of the serialized JSON, which is why "Trond Fausa Aurvåg" answers a search
    for "tron" — demoting it does not fix that, but it stops it burying the
    film.

    Ranking rather than a title/everything switch, deliberately: a mode the
    user picks before seeing results makes them guess which one will find the
    thing. Every search worth copying ranks instead.

    Args:
        search_term: Raw user text. Wildcards are neutralised here.

    Returns:
        A SQLAlchemy ``CASE`` yielding a small int, for ``order_by``.
    """
    term = (search_term or "").strip()
    if not term:
        return literal(0)

    # LIKE wildcards are neutralised through watchlist_matching's own escaper —
    # the module that DEFINES it. Without this a search for "100%" ranks every
    # row as an exact match. (The search PREDICATE has the same gap; it is a
    # separate fix and is logged, not silently widened here.)
    safe = _escape_like(term).lower()
    title = func.lower(_search_title_expr())
    padded = _word_padded(_search_title_expr())

    return case(
        (title == term.lower(), 0),
        (title.like(f"{safe}%", escape="\\"), 1),
        (padded.like(f"% {safe} %", escape="\\"), 2),
        (title.like(f"%{safe}%", escape="\\"), 3),
        else_=4,
    )
