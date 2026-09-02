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

from sqlalchemy import bindparam, case, func, literal, text

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


#: The two search sections, in the order they render. FIXED, not sorted by best
#: match: ordering them dynamically reshuffles the list mid-keystroke and
#: presumes what an ambiguous term meant ("Cage" — the film or the actor?).
#: Fixed is learnable; you always know where to look.
SECTION_TITLE = "title"
SECTION_CAST = "cast"
SECTION_ORDER = (SECTION_TITLE, SECTION_CAST)


def search_section_expr(search_term: str):
    """Which section a row belongs to — ``title`` when the TITLE matched at all.

    A row can match both (a Nicolas Cage film called *Cage*), so it is assigned
    its BEST section rather than appearing twice. Titles wins because it renders
    first and because a title match is the stronger claim.

    Deliberately cheap — a plain ``LIKE`` on the title, no JSON. The person's
    name, needed only for the sub-heading, is fetched for one PAGE of rows by
    :func:`matched_persons_map`: the batch-enrich shape
    ``RatingRepository.get_all_map`` already uses to keep the list off N+1.

    Args:
        search_term: Raw user text.

    Returns:
        A SQLAlchemy ``CASE`` yielding ``"title"`` or ``"cast"``.
    """
    term = (search_term or "").strip()
    if not term:
        return literal(SECTION_TITLE)
    safe = _escape_like(term).lower()
    title = func.lower(_search_title_expr())
    return case((title.like(f"%{safe}%", escape="\\"), literal(SECTION_TITLE)),
                else_=literal(SECTION_CAST))


def search_order_terms(search_term: str, channel_cls):
    """The ORDER BY for a search, as a tuple — one definition, two call sites.

    Section, then relevance inside it, then the existing alphabetical
    tie-break. Relevance alone would interleave a strong cast match with weak
    title ones; a FIXED section order means a boundary can never move while the
    user is typing.

    Both the flat path and the collapsed one need it — the collapsed path picks
    its representative page in SQL, so ordering only what came back would rank
    page 1 against page 1 and an exact match on page 6 would never arrive.
    Spelling it out twice is how those two drift.

    Args:
        search_term: Raw user text. Empty yields constants, so an un-searched
            list orders exactly as it always did.
        channel_cls: ``ChannelDB`` or a subquery's ``.c`` — whichever the
            caller is ordering.

    Returns:
        A tuple for ``order_by(*terms)``.
    """
    return (search_section_expr(search_term),
            search_relevance_tier(search_term),
            channel_cls.name, channel_cls.id)


def section_for_title(title: str | None, search_term: str) -> str:
    """The Python half of :func:`search_section_expr` — the SAME rule.

    The SQL expression decides the ORDER (it has to, because the page is chosen
    in SQL); this decides the TAG on the DTO the GUI builds from the rows that
    came back. Two expressions of one rule, so
    ``test_search_sections`` asserts they agree over a corpus rather than
    trusting that they do — the approximation-measuring habit
    ``test_search_relevance_ranking`` established.

    Args:
        title: ``detected_title`` or the raw name.
        search_term: Raw user text.

    Returns:
        ``"title"`` when the title contains the term, else ``"cast"``.
    """
    term = (search_term or "").strip().lower()
    if not term:
        return SECTION_TITLE
    return SECTION_TITLE if term in (title or "").lower() else SECTION_CAST


#: Tiers a "Whole" section keeps: the title IS the term, starts with it, or
#: contains it as a whole word. "Part" adds tier 3 — the term appears somewhere
#: inside a longer word, which is where Astronaut answers a search for "tron".
#: Tier 4 (matched on cast or an id, not the title) belongs to the Cast & Crew
#: section and is never filtered by this control.
WHOLE_TIERS = frozenset({0, 1, 2})


def tier_for_title(title: str | None, search_term: str) -> int:
    """The Python half of :func:`search_relevance_tier` — the SAME ladder.

    SQL decides the ORDER, because the page is chosen in the database and a
    Python pass can only see the rows that came back. This decides what a
    ``Whole``/``Part`` toggle KEEPS, which is a question about rows already on
    screen — so it has to give the same answer or a row would sort into a
    position the filter then removes it from.

    Written against the same separator data as the SQL, not a second guess at
    it: :data:`_WORD_SEPARATORS` and the space-collapse both come from there.

    Args:
        title: ``detected_title`` or the raw name.
        search_term: Raw user text.

    Returns:
        0 exact · 1 prefix · 2 whole word · 3 substring · 4 matched elsewhere.
    """
    term = (search_term or "").strip().lower()
    if not term:
        return 0
    low = (title or "").lower()
    if low == term:
        return 0
    if low.startswith(term):
        return 1

    flat = low
    for ch in _WORD_SEPARATORS:
        flat = flat.replace(ch, " ")
    flat = " " + " ".join(flat.split()) + " "
    if f" {term} " in flat:
        return 2
    return 3 if term in low else 4


#: What separates two names inside ONE ``metadata.director`` value. It is plain
#: TEXT, not JSON, and 34.3% of the 74,462 populated rows on the owner's library
#: hold a LIST — often not even of people: "Anna Sanders Films, Burning Blue,
#: Illuminations Films, ZDF, ARTE". Measured in that column: comma 13,909,
#: ``&`` 36, ``/`` 27, Arabic comma 7.
_PERSON_SEPARATORS = ",&/;\u060c"


def best_person_part(person: str, search_term: str) -> str | None:
    """The single name inside *person* that answers the search, or None.

    ``LIKE '%strong%'`` against a whole director value matches the VALUE, not a
    name in it — so a search for "Strong" named *"Paula Casarin, Carley
    Armstrong, Andrea Trigo, Martina Vazzoler, J.C. Chandor"* as the reason
    *Kraven the Hunter* was on screen. Owner: *"it's clearly matching Carley
    Armstrong ... but listing the entire cast."*

    Cast names arrive from ``json_each`` already separated and pass through
    unchanged; this exists for the director column, which has no structure.

    Ranked the way the query ranks whole values — exact, then whole word, then
    substring, shortest first — so "Strong" prefers *Mark Strong* over
    *Armstrong* when one value holds both.

    Args:
        person: One ``cast`` name, or a whole ``director`` value.
        search_term: Raw user text.

    Returns:
        The best matching part, trimmed; None when no part matches.
    """
    term = (search_term or "").strip().lower()
    if not term or not person:
        return None

    flat = person
    for ch in _PERSON_SEPARATORS:
        flat = flat.replace(ch, ",")

    best, best_key = None, None
    for part in (p.strip() for p in flat.split(",")):
        low = part.lower()
        if not part or term not in low:
            continue
        tier = 0 if low == term else (1 if f" {term} " in f" {low} " else 2)
        key = (tier, len(part))
        if best_key is None or key < best_key:
            best, best_key = part, key
    return best


def canonical_person(search_term: str, known: dict) -> str | None:
    """The name to show when the term matched a channel's NAME, not its metadata.

    Providers put the cast in the title. Measured on the owner's library for
    "nicolas cage": **182** channels carry it in ``ChannelDB.name`` and only
    **8** in ``detected_title`` —
    ``'EN - Arcadian 4K (2024) NICOLAS CAGE'`` parses to ``'Arcadian'``. Those
    rows have no ``metadata.cast`` at all (``8MM 1`` has neither cast nor
    director) yet the search predicate matched them on the name, so they landed
    in Cast & Crew with nothing to head them: **65 of 68 rows unlabelled, and
    the one real group of 3 stranded at the bottom**.

    The row genuinely IS a cast match — the provider is telling us he is in it —
    so the honest heading is the term itself. Returned in the SAME spelling any
    metadata row on the page already uses, so the two merge into one group
    rather than "NICOLAS CAGE" sitting beside "Nicolas Cage"; failing that,
    title case, which is what the provider blobs and TMDb both produce.

    Args:
        search_term: Raw user text.
        known: The metadata-derived ``{channel_id: person}`` for this page.

    Returns:
        The display name, or None when the term is empty.
    """
    term = (search_term or "").strip()
    if not term:
        return None
    low = term.lower()
    for person in known.values():
        if person and person.lower() == low:
            return person        # match the spelling already on screen
    return term.title()


def matched_persons_map(session, channel_ids, search_term: str) -> dict:
    """``{channel_id: person}`` for the rows whose CAST matched — one query.

    The sub-heading prints a person once for the whole group instead of on every
    row (85 Nicolas Cage films should say his name once), so this returns the
    single best-matching name per channel:

    * exact name beats whole-word beats partial, and
    * within a tier the shortest name wins, which prefers "Nicolas Cage" over
      "Nicolas Cage Jr." without needing a second rule.

    Reads the real ``"name"`` values through ``json_each`` rather than a
    substring of the serialized blob — which is why "Trond Fausa Aurvåg" can be
    NAMED as the reason a search for "tron" returned a row, instead of the row
    looking like a bug. Checked: this SQLite has JSON1 (3.53.4).

    Args:
        session: An open session — the caller's, inside its own scope.
        channel_ids: The page of ids to enrich. Empty is a no-op with no query.
        search_term: Raw user text.

    Returns:
        ``{channel_id: name}``; ids with no cast match are simply absent.
    """
    ids = [i for i in (channel_ids or []) if i]
    term = (search_term or "").strip().lower()
    if not ids or not term:
        return {}

    safe = _escape_like(term)
    params = {"ids": ids, "exact": term,
              "padded": f"% {safe} %", "like": f"%{safe}%"}

    # metadata is reached through ChannelDB.metadata_id — an FK on the CHANNEL,
    # not metadata pointing back. (I had it the other way and the query returned
    # nothing; channel_lens.metadata_person_exists is where the join is defined.)
    #
    # Cast is JSON and read through json_each; director is a plain TEXT column
    # and has no names to split, so it is a second arm rather than a special
    # case inside one. Both are what the details pane displays, which is the
    # rule metadata_person_exists states: a filter over "who is in this" must
    # match what is shown, not the raw provider blob.
    sql = """
        SELECT cid, person, tier, namelen FROM (
            SELECT ch.id AS cid,
                   json_extract(j.value, '$.name') AS person,
                   CASE WHEN lower(json_extract(j.value, '$.name')) = :exact THEN 0
                        WHEN ' ' || lower(json_extract(j.value, '$.name')) || ' '
                             LIKE :padded ESCAPE '\\' THEN 1
                        ELSE 2 END AS tier,
                   length(json_extract(j.value, '$.name')) AS namelen
            FROM channels ch
            JOIN metadata m ON m.id = ch.metadata_id
            JOIN json_each(m."cast") j
            WHERE ch.id IN :ids
              AND lower(json_extract(j.value, '$.name')) LIKE :like ESCAPE '\\'
            UNION ALL
            SELECT ch.id AS cid,
                   m.director AS person,
                   CASE WHEN lower(m.director) = :exact THEN 0
                        WHEN ' ' || lower(m.director) || ' '
                             LIKE :padded ESCAPE '\\' THEN 1
                        ELSE 2 END AS tier,
                   length(m.director) AS namelen
            FROM channels ch
            JOIN metadata m ON m.id = ch.metadata_id
            WHERE ch.id IN :ids
              AND m.director IS NOT NULL
              AND lower(m.director) LIKE :like ESCAPE '\\'
        )
        ORDER BY cid, tier, namelen
    """
    rows = session.execute(
        text(sql).bindparams(bindparam("ids", expanding=True)), params
    ).fetchall()

    # ORDER BY put the best VALUE first, but a director value can hold several
    # names, so the winner still has to be reduced to the name that actually
    # matched. A value whose match was an artefact of the whole string is
    # skipped and the next candidate used.
    best: dict = {}
    for cid, person, _tier, _namelen in rows:
        if cid in best or not person:
            continue
        part = best_person_part(person, search_term)
        if part:
            best[cid] = part
    return best
