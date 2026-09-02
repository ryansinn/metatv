"""Searching for a title finds the title, instead of everything spelled like it.

Measured on the owner's library, 2026-09-02. Searching **"Tron"**:

    name LIKE '%tron%'  (what search does)   788
    title is exactly "Tron"                   12
    title starts with "Tron"                 124
    "Tron" as a whole word in the title       33
    cast JSON containing "tron"              605   (sample hit: "Trond Fausa")

...ordered by ``ChannelDB.name`` — alphabetically — so
``24/7 THE ASTRONAUT WIVES CLUB`` outranked ``Tron`` and the twelve exact
matches were unreachable. Owner: *"it seems like Tron shows a ton of stuff but
not Tron ... exact matches should be shown first, no?"*

Ranking rather than a title/everything switch: a mode the user picks BEFORE
seeing results makes them guess which one will find the thing.

**Tier 2 is an approximation and this file measures its error rather than
pretending otherwise.** The reference definition of "whole word" lives in
``watchlist_matching`` as ``(?<!\\w)term(?!\\w)``; SQLite here has no ``REGEXP``
(checked), so SQL flattens a measured separator set to spaces instead. The last
test compares the two over a real-shaped corpus and pins the disagreement.
"""

from __future__ import annotations

import re

import pytest

from metatv.core.database import Database
from metatv.core.repositories import RepositoryFactory
from tests.conftest import make_channel

#: Titles chosen from what the owner's library actually contains for "tron".
#: "TRON UPRISING" is uppercase and "tron" is lowercase ON PURPOSE. SQLite's
#: default collation is case-SENSITIVE, so 'T' < 't' and the alphabetical
#: tie-break puts "TRON UPRISING" BEFORE "tron". Without a distinct exact tier
#: the exact match is therefore not first — which is the only way to tell tier
#: 0 from tier 1 at all, because an exact match is a prefix of every one of its
#: own prefix-matches and would otherwise always win on the tie-break. A
#: mutation collapsing tiers 0 and 1 survived the first version of this file.
CORPUS = [
    ("tron", 0),                              # exact, sorts AFTER the prefix
    ("TRON: Legacy", 1),                      # prefix, sorts first
    ("TRON UPRISING", 1),                     # prefix, sorts first
    ("24/7 Tron Rides Again", 2),             # whole word, mid-title
    ("The Legacy of Tron", 2),                # whole word, trailing
    ("24/7 THE ASTRONAUT WIVES CLUB", 3),     # substring only
    ("VOLTRON LEGENDARY DEFENDER", 3),        # substring only
    ("STRONGMAN CHAMPIONS LEAGUE", 3),        # substring only
    ("ARM| KENTRON", 3),                      # substring only
]


@pytest.fixture
def repo(tmp_path):
    """A real Database on a real file — CLAUDE.md, and this is session work."""
    db = Database(f"sqlite:///{tmp_path / 'rank.db'}")
    db.create_tables()
    with db.session_scope() as session:
        for name, _tier in CORPUS:
            make_channel(session, name, media_type="movie",
                         detected_title=name)
        session.flush()
    session = db.SessionLocal()
    yield RepositoryFactory(session).channels
    session.close()


def _titles(rows):
    return [r.name for r in rows]


def test_the_exact_match_is_first(repo):
    """The owner's sentence, as an assertion."""
    rows = repo.get_all(search_query="Tron", limit=50)
    assert rows, "the search returned nothing at all"
    assert rows[0].name == "tron", (
        f"first result is {rows[0].name!r}; the exact match is at position "
        f"{_titles(rows).index('tron') + 1}. Note the corpus is built so the "
        "alphabetical tie-break would NOT put it first — only a distinct exact "
        "tier does."
    )


def test_every_title_match_outranks_every_letters_only_match(repo):
    """Astronaut/Voltron/Strongman/Kentron go BELOW anything Tron-titled."""
    order = _titles(repo.get_all(search_query="Tron", limit=50))
    title_matches = {n for n, t in CORPUS if t <= 2}
    letters_only = {n for n, t in CORPUS if t == 3}

    worst_title = max(order.index(n) for n in title_matches if n in order)
    best_letters = min(order.index(n) for n in letters_only if n in order)
    assert worst_title < best_letters, (
        f"{order[best_letters]!r} (letters only) outranks "
        f"{order[worst_title]!r} (a title match)\norder: {order}"
    )


def test_the_tiers_come_out_in_order(repo):
    """Not just "exact first" — the whole ladder, which is what was asked for."""
    order = _titles(repo.get_all(search_query="Tron", limit=50))
    tier_of = dict(CORPUS)
    seen = [tier_of[n] for n in order if n in tier_of]
    assert seen == sorted(seen), (
        f"tiers are out of order: {list(zip(order, seen))}")


def test_an_unsearched_list_is_still_alphabetical(repo):
    """The ranking must not leak into browsing.

    The name/id tie-break exists so the filter counters cannot see a shuffled
    row as one an axis hid; an un-searched list has to be byte-identical.
    """
    order = _titles(repo.get_all(limit=50))
    assert order == sorted(order)


def test_a_term_with_a_like_wildcard_does_not_rank_everything(repo):
    """"100%" must not make every row an exact match.

    Escaping goes through ``watchlist_matching._escape_like`` — the module that
    DEFINES it — rather than a second copy.
    """
    rows = repo.get_all(search_query="Tro%n", limit=50)
    names = _titles(rows)
    assert "tron" not in names[:1] or len(names) <= 1, (
        "a wildcard term was treated as an exact match")


def test_an_empty_term_ranks_everything_equally(repo):
    """The early return in ``search_relevance_tier``, which nothing else reaches.

    ``get_all`` only applies the tier when there IS a search term, so a mutation
    inside the expression's empty-term guard is invisible from the query path —
    one survived the first version of this file. Asserted directly.
    """
    from sqlalchemy import literal

    from metatv.core.repositories.search_ranking import search_relevance_tier

    for blank in ("", "   ", None):
        expr = search_relevance_tier(blank)
        assert str(expr) == str(literal(0)), (
            f"an empty search term ({blank!r}) produced a ranking expression: "
            f"{str(expr)[:80]}"
        )


def test_a_multi_word_term_matches_across_a_separator(qapp_unused=None):
    """"Tron: Legacy" + "tron legacy" must match. It did not.

    Flattening a separator that sits NEXT TO a space produces two spaces —
    ``"tron  legacy"`` — and the needle carries one, so every multi-word search
    crossing a colon, dash or pipe silently missed. Titles here are full of
    them: "Tron: Legacy", "Spider-Man: No Way Home",
    "MLB 08 | Athletics x Mariners".

    Found by the owner asking what the padding actually does, rather than by
    the tests, which only ever exercised single-word terms.
    """
    from metatv.core.repositories.search_ranking import (
        _SPACE_COLLAPSE_PASSES, _WORD_SEPARATORS,
    )

    def padded(title: str) -> str:
        flat = title.lower()
        for ch in _WORD_SEPARATORS:
            flat = flat.replace(ch, " ")
        for _ in range(_SPACE_COLLAPSE_PASSES):
            flat = flat.replace("  ", " ")
        return f" {flat} "

    cases = [
        ("Tron: Legacy", "tron legacy", True),
        ("Spider-Man: No Way Home", "spider man no way home", True),
        ("MLB 08 | Athletics x Mariners", "athletics x mariners", True),
        ("Leaving Las Vegas", "las vegas", True),
        ("Tron: Legacy", "tron", True),
        # ...and the whole point of the tier survives: a fragment is still not a word.
        ("Astronaut", "tron", False),
        ("Strongman Champions League", "tron", False),
    ]
    for title, term, expected in cases:
        got = f" {term} " in padded(title)
        assert got is expected, (
            f"{title!r} + {term!r}: expected {'match' if expected else 'no match'}, got the other")


def test_the_sql_word_test_agrees_with_the_python_definition(repo):
    """The approximation's ERROR, measured — not an assertion that it is exact.

    ``watchlist_matching`` defines whole-word as ``(?<!\\w)term(?!\\w)``. SQL
    cannot express a lookaround, so ``_word_padded`` flattens a measured
    separator set (99.6% of the separators occurring between word characters
    across 200,000 real titles) to spaces. Where the two disagree, this fails
    loudly with the offending title rather than letting the gap widen quietly.
    """
    from metatv.core.repositories.search_ranking import _WORD_SEPARATORS

    def python_whole_word(title: str, term: str) -> bool:
        return re.search(rf"(?<!\w){re.escape(term)}(?!\w)", title.lower()) is not None

    def sql_whole_word(title: str, term: str) -> bool:
        flat = title.lower()
        for ch in _WORD_SEPARATORS:
            flat = flat.replace(ch, " ")
        return f" {term} " in f" {flat} "

    disagree = [
        name for name, _t in CORPUS
        if python_whole_word(name, "tron") != sql_whole_word(name, "tron")
    ]
    assert not disagree, (
        "the SQL word test and the Python definition disagree on: "
        f"{disagree} — widen _WORD_SEPARATORS or record the exception"
    )
