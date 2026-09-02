"""The Python tier ladder and the SQL one must give the same answer.

SQL decides the ORDER — the page is chosen in the database, so a Python pass can
only see rows that already came back. Python decides what the ``Whole``/``Part``
control KEEPS, which is a question about rows on screen.

Two implementations of one rule is the shape CLAUDE.md keeps naming, and here it
has a specific symptom: a row would sort into a position the filter then removes
it from, so "Whole" would blank a section that the ranking had just put at the
top. This drives BOTH against a real database and compares them row by row.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from metatv.core.database import ChannelDB, Database
from metatv.core.repositories.search_ranking import (
    search_relevance_tier, tier_for_title,
)
from tests.conftest import make_channel


#: Titles chosen to land on every rung, including the ones that broke earlier:
#: a colon beside a space (the space-collapse case), a term inside a longer word
#: and a term at a title's end.
_TITLES = [
    "Tron",                    # 0 — exact
    "TRON",                    # 0 — exact, case-folded
    "Tron: Legacy",            # 1 — prefix
    "Tron Ares",               # 1 — prefix
    "The Tron Chronicles",     # 2 — whole word, mid-title
    "Legacy of Tron",          # 2 — whole word, at the end
    "Tron: Legacy Reborn",     # 1 — prefix wins over the whole-word rung
    "24/7 Astronaut Wives",    # 3 — inside a longer word
    "Electronic Dreams",       # 3 — inside a longer word
    "Something Else Entirely",  # 4 — no title match at all
]


@pytest.fixture
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'tiers.db'}")
    database.create_tables()
    with database.session_scope() as session:
        for title in _TITLES:
            make_channel(session, title, media_type="movie",
                         detected_title=title)
        session.flush()
        yield database, session


@pytest.mark.parametrize("term", ["tron", "Tron", "TRON", "tron legacy",
                                  "legacy", "astronaut"])
def test_python_and_sql_agree_on_every_row(db, term):
    """Row by row, against a real database — not asserted, measured."""
    _database, session = db
    rows = session.execute(
        select(ChannelDB.detected_title, search_relevance_tier(term))
    ).all()
    assert rows, "the fixture produced no rows"

    disagreements = [
        (title, sql_tier, tier_for_title(title, term))
        for title, sql_tier in rows
        if sql_tier != tier_for_title(title, term)
    ]
    assert not disagreements, (
        "the two ladders disagree — a row would sort into a position the "
        "Whole/Part filter then removes it from:\n  " +
        "\n  ".join(f"{t!r}: SQL says {s}, Python says {p}"
                    for t, s, p in disagreements))


def test_the_ladder_actually_has_rungs(db):
    """A mirror test passes trivially if both sides answer the same constant."""
    _database, session = db
    tiers = {t for _title, t in session.execute(
        select(ChannelDB.detected_title, search_relevance_tier("tron"))).all()}
    assert tiers >= {0, 1, 2, 3}, (
        f"the corpus only exercised tiers {sorted(tiers)} — the agreement "
        "above would hold for a ladder that always returned one number")


def test_a_multi_word_term_matches_across_a_separator(db):
    """The colon-beside-a-space case, which the SQL needed four passes for."""
    assert tier_for_title("Tron: Legacy", "tron legacy") == 2
    assert tier_for_title("Tron - Legacy", "tron legacy") == 2


def test_an_empty_term_ranks_everything_equally(db):
    """Browsing is not a search; nothing may be demoted."""
    assert tier_for_title("Anything At All", "") == 0
    assert tier_for_title("Anything At All", "   ") == 0
