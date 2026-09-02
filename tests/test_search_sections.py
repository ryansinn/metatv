"""Search results are grouped by the field that matched, and the person is named once.

Two decisions this pins, both settled with the owner on 2026-09-02:

* **A row appears once, in its BEST section.** A Nicolas Cage film called *Cage*
  matches both; Titles wins because it renders first and a title match is the
  stronger claim. Without this a film shows up twice and the counts stop adding
  up.
* **The sub-heading prints a person once per group**, not on every row — owner:
  *"that way you don't have 10 Nicolas Cage lines."* Measured on the real
  library, a page of 80 cast-matching rows for "cage" resolves to 65 Nicolas
  Cage, 4 Weston Cage, 3 Finn McCager Higgins, 2 David Beaucage — where the weak
  matches are self-evidently weak because their group is small and named.

``matched_persons_map`` reads the real ``"name"`` values through ``json_each``
rather than a substring of the serialized JSON blob, which is the difference
between naming *Trond Fausa Aurvåg* as the reason a search for "tron" returned a
row and that row looking like a bug.
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, MetadataDB
from metatv.core.repositories.search_ranking import (
    SECTION_CAST, SECTION_ORDER, SECTION_TITLE, matched_persons_map,
    search_section_expr,
)
from tests.conftest import make_channel


@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — CLAUDE.md; this is session work."""
    database = Database(f"sqlite:///{tmp_path / 'sections.db'}")
    database.create_tables()
    return database


def _with_cast(session, name, cast_names, director=None, title=None):
    md = MetadataDB(
        id=f"md-{name}",
        title=name,                 # NOT NULL on MetadataDB
        cast=[{"name": n, "character": None} for n in cast_names],
        director=director,
    )
    session.add(md)
    session.flush()
    ch = make_channel(session, name, media_type="movie",
                      detected_title=title or name)
    ch.metadata_id = md.id
    session.flush()
    return ch


def test_a_row_lands_in_one_section_and_titles_wins(db):
    """The double-match case: a Nicolas Cage film literally called "Cage"."""
    with db.session_scope() as session:
        both = _with_cast(session, "Cage", ["Nicolas Cage"])
        cast_only = _with_cast(session, "Leaving Las Vegas", ["Nicolas Cage"])
        session.flush()

        expr = search_section_expr("cage")
        from metatv.core.database import ChannelDB
        rows = dict(session.query(ChannelDB.id, expr).all())

        assert rows[both.id] == SECTION_TITLE, (
            "a row matching BOTH must land in Titles, not appear twice")
        assert rows[cast_only.id] == SECTION_CAST


def test_an_empty_term_does_not_section_anything(db):
    """Browsing is not a search; nothing should be tagged."""
    with db.session_scope() as session:
        _with_cast(session, "Leaving Las Vegas", ["Nicolas Cage"])
        session.flush()
        got = session.query(search_section_expr("")).limit(1).scalar()
        assert got == SECTION_TITLE, "an empty term must not push rows into Cast"
        assert SECTION_ORDER == (SECTION_TITLE, SECTION_CAST), (
            "section order is FIXED — Titles first — and must not be re-sorted")


def test_the_person_named_is_the_best_match_not_the_first(db):
    """Exact beats whole-word beats partial; shortest wins inside a tier."""
    with db.session_scope() as session:
        # "David Beaucage" sorts first alphabetically and is a PARTIAL match;
        # "Nicolas Cage" is the whole-word one and must be the name shown.
        row = _with_cast(session, "Some Film", ["David Beaucage", "Nicolas Cage"])
        exact = _with_cast(session, "Another Film", ["Cage", "Nicolas Cage"])
        session.flush()
        ids = [row.id, exact.id]

        got = matched_persons_map(session, ids, "cage")

        assert got[row.id] == "Nicolas Cage", (
            f"named {got.get(row.id)!r} — a partial match beat a whole-word one")
        assert got[exact.id] == "Cage", "an exact name must win over a whole-word one"


def test_a_director_match_names_the_director(db):
    """director is a plain TEXT column, not JSON — its own arm, not a special case."""
    with db.session_scope() as session:
        row = _with_cast(session, "Directed Thing", ["Someone Else"],
                         director="Nicolas Cage")
        session.flush()
        got = matched_persons_map(session, [row.id], "cage")
        assert got.get(row.id) == "Nicolas Cage"


def test_a_partial_name_is_still_named_so_the_row_is_not_a_mystery(db):
    """"Trond" answering "tron" must SAY so — that is the whole point of E."""
    with db.session_scope() as session:
        row = _with_cast(session, "Norwegian Thing", ["Trond Fausa Aurvåg"])
        session.flush()
        got = matched_persons_map(session, [row.id], "tron")
        assert got.get(row.id) == "Trond Fausa Aurvåg"


def test_no_ids_and_no_term_run_no_query(db):
    """The page-enrich shape: an empty page must not hit the database at all."""
    assert matched_persons_map(None, [], "cage") == {}
    assert matched_persons_map(None, ["x"], "") == {}
    assert matched_persons_map(None, None, None) == {}


def test_every_like_escape_is_a_single_character():
    """SQLite rejects a multi-character ESCAPE at RUNTIME, not at import.

    One of these was written as ``"\\\\\\\\"`` — two characters — and the module
    imported, ruff passed, and the failure only appeared when a query actually
    ran. Guarded as a class rather than an instance: it is invisible to reading
    and every future ``escape=`` gets it for free.
    """
    import pathlib
    import re

    from metatv.core.repositories import search_ranking

    src = pathlib.Path(search_ranking.__file__).read_text(encoding="utf-8")
    bad = [m.group(1) for m in re.finditer(r'escape=("(?:[^"\\]|\\.)*")', src)
           if len(eval(m.group(1))) != 1]
    assert not bad, f"ESCAPE must be exactly one character; found {bad}"
