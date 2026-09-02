"""A watch rule matches whole words, and one matcher decides that everywhere.

Settled in "Catch, Keep, Record" (2026-08-30) Q1. The failures it names are not
near-misses — the term genuinely is not in the title:

    "NFL"    matched  Inflammation, Börsenflash
    "Dragon" matched  Dragonfly

Before this slice the answer was open-coded in seven places, split across two
grains that could disagree with each other: two ``ilike('%term%')`` filters
decided what was IN the watchlist, and three ``pat in title.lower()`` re-checks
decided what got HIGHLIGHTED or raised a toast. This file pins both grains to
the same definition, and the drift guard at the bottom is what stops an eighth
site from growing back.
"""
from __future__ import annotations

import pathlib
import sqlite3
import uuid
from datetime import timedelta

import pytest

from metatv.core.watchlist_matching import (
    WatchRule, as_rules, matches, matches_any, refine, rule_for,
)

_ROOT = pathlib.Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------
# The matcher itself
# --------------------------------------------------------------------------

@pytest.mark.parametrize("title, expected", [
    ("NFL Live", True),
    ("Tonight: NFL.", True),          # trailing punctuation is still a boundary
    ("nfl redzone", True),            # casefolded both sides
    ("Inflammation Today", False),    # the case the owner hit
    ("Börsenflash", False),           # ...and its unicode twin
    ("Superbowl", False),
])
def test_whole_word_is_the_default(title, expected):
    assert matches(title, WatchRule(term="NFL")) is expected


def test_the_escape_hatch_restores_contains_anywhere():
    """``whole_word=False`` must reproduce the OLD behaviour exactly.

    Not decoration: it is the documented escape hatch, and if it did anything
    other than plain substring matching a user turning it on would get a third
    behaviour nobody specified.
    """
    rule = WatchRule(term="NFL", whole_word=False)
    for title in ("NFL Live", "Inflammation Today", "Börsenflash"):
        assert matches(title, rule) is ("nfl" in title.casefold())


def test_a_multi_word_term_is_a_phrase():
    rule = WatchRule(term="Denver Broncos")
    assert matches("Vikings @ Denver Broncos", rule)
    assert not matches("Denver v Broncos", rule)     # not adjacent
    assert not matches("Denver Nuggets", rule)


def test_exclude_terms_suppress_a_real_match():
    rule = WatchRule(term="Denver", exclude=("news", "pregame"))
    assert matches("Denver @ SF", rule)
    assert not matches("Denver News at Nine", rule)
    assert not matches("Denver Pregame Show", rule)


def test_excludes_obey_the_rules_own_whole_word_setting():
    """One toggle, one behaviour — so the row can honestly say "whole words only".

    With whole-word on, an exclude of "new" must NOT suppress "News"; with the
    escape hatch on, it must. If excludes had their own fixed mode, the label
    on the rule row would be a lie for half the rule.
    """
    strict = WatchRule(term="Denver", exclude=("new",))
    assert matches("Denver News at Nine", strict)

    loose = WatchRule(term="Denver", exclude=("new",), whole_word=False)
    assert not matches("Denver News at Nine", loose)


def test_a_blank_term_matches_nothing():
    """``"" in anything`` is True — a blank rule row would light up the guide."""
    for term in ("", "   ", "\t"):
        assert matches("literally any programme", WatchRule(term=term)) is False


def test_a_wildcard_in_a_term_is_not_a_wildcard():
    """A rule for "100%" is a rule for the characters, not "match everything"."""
    assert matches("Chart Show 100% Hits", WatchRule(term="100%", whole_word=False))
    assert not matches("Nothing relevant", WatchRule(term="100%", whole_word=False))


def test_matches_any_and_as_rules_skip_blanks():
    rules = as_rules(["NFL", "", "   ", WatchRule(term="Dragon", whole_word=False)])
    assert [r.term for r in rules] == ["NFL", "Dragon"]
    assert matches_any("Dragonfly", rules)        # escape hatch on that rule
    assert not matches_any("Inflammation", rules)


def test_refine_applies_the_limit_after_matching_not_before():
    """The ordering bug this helper exists to prevent.

    Nine rows come back from the coarse prefilter and only the last two really
    match. Cutting to 2 first yields nothing; refining first yields both.
    """
    rows = [f"Inflammation {i}" for i in range(7)] + ["NFL Live", "NFL Late"]
    kept = refine(rows, rule_for("NFL"), text_of=lambda r: r, limit=2)
    assert kept == ["NFL Live", "NFL Late"]
    assert rows[:2] == ["Inflammation 0", "Inflammation 1"]   # what SQL would have cut to


# --------------------------------------------------------------------------
# The SQL grain — a real database file, per the project's DB-session rule
# --------------------------------------------------------------------------

def _seeded_db(tmp_path):
    from metatv.core.database import Database, ChannelDB, EpgProgramDB
    from metatv.core.epg_utils import now_utc

    db = Database(f"sqlite:///{tmp_path / 'epg.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="Chan"))
        for i, title in enumerate(
                ["NFL Live", "Inflammation Today", "Börsenflash",
                 "NFL Pregame Show", "Dragonfly"]):
            s.add(EpgProgramDB(id=100 + i, channel_db_id="c1", channel_epg_id="e1",
                               provider_id="p1", title=title,
                               start_time=now + timedelta(hours=1 + i),
                               stop_time=now + timedelta(hours=2 + i)))
        s.add(EpgProgramDB(id=200, channel_db_id="c1", channel_epg_id="e1",
                           provider_id="p1", title="NFL RedZone",
                           start_time=now - timedelta(minutes=10),
                           stop_time=now + timedelta(hours=1)))
        s.add(EpgProgramDB(id=201, channel_db_id="c1", channel_epg_id="e1",
                           provider_id="p1", title="Inflammation Hour",
                           start_time=now - timedelta(minutes=10),
                           stop_time=now + timedelta(hours=1)))
    return db


def test_the_watchlist_queries_return_only_whole_word_matches(tmp_path):
    from metatv.core.repositories.epg import EpgRepository

    db = _seeded_db(tmp_path)
    with db.session_scope(commit=False) as s:
        repo = EpgRepository(s)
        assert [p.title for p in repo.get_upcoming_for_watchlist(["NFL"])["NFL"]] == [
            "NFL Live", "NFL Pregame Show"]
        assert [p.title for p in repo.get_live_for_watchlist(["NFL"])["NFL"]] == [
            "NFL RedZone"]


def test_the_queries_accept_a_stored_rule_and_honour_its_excludes(tmp_path):
    from metatv.core.repositories.epg import EpgRepository

    db = _seeded_db(tmp_path)
    rule = WatchRule(term="NFL", exclude=("pregame",))
    with db.session_scope(commit=False) as s:
        repo = EpgRepository(s)
        assert [p.title for p in repo.get_upcoming_for_watchlist([rule])["NFL"]] == [
            "NFL Live"]


def test_the_escape_hatch_reproduces_the_pre_fix_result_set(tmp_path):
    """Proof the change is the change: with whole_word off, every previously
    returned row comes back — including the three this slice exists to drop."""
    from metatv.core.repositories.epg import EpgRepository

    db = _seeded_db(tmp_path)
    rule = WatchRule(term="NFL", whole_word=False)
    with db.session_scope(commit=False) as s:
        titles = [p.title for p in
                  EpgRepository(s).get_upcoming_for_watchlist([rule])["NFL"]]
    assert set(titles) == {"NFL Live", "Inflammation Today", "Börsenflash",
                           "NFL Pregame Show", "Dragonfly"}


# --------------------------------------------------------------------------
# The upgrade path — the one path no fresh-DB test runs
# --------------------------------------------------------------------------

def test_an_existing_database_gains_the_columns_and_keeps_its_rules(tmp_path):
    """``create_all`` adds TABLES, never a COLUMN to a table that exists.

    This shipped broken twice in one day (#617, #648) past a green suite,
    because every other test builds its database from scratch where the column
    exists by construction. So this one builds the OLD table by hand.
    """
    from metatv.core.database import Database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE alert_patterns (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
        pattern_type TEXT NOT NULL, pattern_value TEXT NOT NULL,
        applies_to TEXT, is_enabled BOOLEAN, last_checked DATETIME,
        created_at DATETIME, updated_at DATETIME)""")
    con.execute(
        "INSERT INTO alert_patterns (id,name,pattern_type,pattern_value,applies_to,is_enabled)"
        " VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), "NFL", "keyword", "NFL", "all", 1))
    con.commit()
    con.close()

    Database(f"sqlite:///{path}").create_tables()

    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(alert_patterns)")}
    assert {"whole_word", "exclude_terms"} <= cols, (
        "the ALTER TABLE entries are missing — an upgraded database will raise "
        "on every watch-rule query while a fresh one stays green")

    value, whole_word = con.execute(
        "SELECT pattern_value, whole_word FROM alert_patterns").fetchone()
    assert (value, whole_word) == ("NFL", 1), (
        "an existing rule must carry the new default EXPLICITLY, not inherit it")
    con.close()


def test_the_migration_heals_a_null_whole_word_on_the_next_start(tmp_path):
    """The explicit UPDATE, tested on the case it actually exists for.

    Mutation-checked: deleting the UPDATE while keeping ``DEFAULT 1`` left the
    upgrade test above GREEN, because the column default already fills rows
    that exist when the ALTER runs. The stamp earns its place on rows that are
    NULL for some OTHER reason — written by a build that added the column
    without a default, or inserted mid-upgrade. ``_migrate`` runs on every
    startup, so it is a self-healing pass, and this is what that means.
    """
    from metatv.core.database import AlertPatternDB, Database

    path = tmp_path / "heal.db"
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(AlertPatternDB(id="a", name="NFL", pattern_type="keyword",
                             pattern_value="NFL", applies_to="all", is_enabled=True))
    con = sqlite3.connect(path)
    con.execute("UPDATE alert_patterns SET whole_word = NULL")
    con.commit()
    assert con.execute(
        "SELECT whole_word FROM alert_patterns").fetchone()[0] is None
    con.close()

    Database(f"sqlite:///{path}").create_tables()      # the next app start

    con = sqlite3.connect(path)
    assert con.execute("SELECT whole_word FROM alert_patterns").fetchone()[0] == 1, (
        "a rule left with no stored opinion was not stamped with the settled "
        "default — the value it matches by stays unrecorded")
    con.close()


def test_rules_reads_the_stored_flags(tmp_path):
    from metatv.core import watchlist
    from metatv.core.database import AlertPatternDB, Database

    db = Database(f"sqlite:///{tmp_path / 'rules.db'}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(AlertPatternDB(id="a", name="NFL", pattern_type="keyword",
                             pattern_value="NFL", applies_to="all", is_enabled=True,
                             whole_word=True, exclude_terms=["pregame"]))
        s.add(AlertPatternDB(id="b", name="Dragon", pattern_type="keyword",
                             pattern_value="Dragon", applies_to="all",
                             is_enabled=True, whole_word=False))

    class _Cfg:
        epg_watchlist_patterns: list[str] = []

    watchlist.bind(db)
    try:
        by_term = {r.term: r for r in watchlist.rules(_Cfg())}
    finally:
        watchlist.unbind()

    assert by_term["NFL"].whole_word is True
    assert by_term["NFL"].exclude == ("pregame",)
    assert by_term["Dragon"].whole_word is False


def test_a_null_whole_word_reads_as_the_settled_default(tmp_path):
    """A row written between the ALTER and the stamp has no opinion; the
    default is the one to apply, not "contains anywhere"."""
    from metatv.core import watchlist
    from metatv.core.database import AlertPatternDB, Database

    path = tmp_path / "null.db"
    db = Database(f"sqlite:///{path}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(AlertPatternDB(id="a", name="NFL", pattern_type="keyword",
                             pattern_value="NFL", applies_to="all", is_enabled=True))
    con = sqlite3.connect(path)
    con.execute("UPDATE alert_patterns SET whole_word = NULL")
    con.commit()
    con.close()

    class _Cfg:
        epg_watchlist_patterns: list[str] = []

    watchlist.bind(db)
    try:
        rules = watchlist.rules(_Cfg())
    finally:
        watchlist.unbind()
    assert rules[0].whole_word is True


# --------------------------------------------------------------------------
# Drift guard — an eighth site must not grow back
# --------------------------------------------------------------------------

def test_lowered_has_no_production_callers():
    """``watchlist.lowered()`` exists only to feed an open-coded matcher.

    It hands out casefolded pattern strings, which is useful for exactly one
    thing: writing ``pat in title.lower()`` by hand. Both of its callers — On
    Now and Browse — now take :func:`watchlist.rules` instead, so the invariant
    that keeps them honest is that nothing in ``metatv/`` calls it again.

    A narrower guard than the one this replaced, and deliberately so: the first
    draft flagged every ``x in y.lower()`` mentioning a title and caught two
    Discover SEARCH BOXES, where contains-anywhere is the correct behaviour for
    a free-text field. A guard that fires on correct code gets deleted.
    """
    offenders = [
        f"{path.relative_to(_ROOT)}:{i}"
        for path in sorted((_ROOT / "metatv").rglob("*.py"))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "watchlist.lowered" in line or "from metatv.core.watchlist import lowered" in line
    ]
    assert not offenders, (
        "casefolded watchlist patterns are being handed to production code, "
        "which is how the seven open-coded matchers were written in the first "
        "place — take watchlist.rules() and matches_any() instead:\n  "
        + "\n  ".join(offenders))


def test_the_matching_surfaces_route_through_the_shared_matcher():
    """Each surface that decides "is this a watchlist hit" imports the matcher.

    Named individually rather than swept, because these four are the whole
    population and a sweep that finds none would pass silently if the files
    were renamed.
    """
    surfaces = [
        "metatv/gui/epg_on_now_mixin.py",
        "metatv/gui/epg_browse_mixin.py",
        "metatv/core/epg_manager.py",
        "metatv/core/repositories/epg.py",
        "metatv/core/alerts.py",
    ]
    for rel in surfaces:
        src = (_ROOT / rel).read_text(encoding="utf-8")
        assert "watchlist_matching import" in src, (
            f"{rel} decides watchlist matches without the shared matcher")
