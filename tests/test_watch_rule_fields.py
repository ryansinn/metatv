"""WL-1 slice 2 — match modes, description scope, and the Option B rule row.

Settled in "Catch, Keep, Record" (2026-08-30), sequencing row 2: match modes
(phrase / all / any) + live-only + a description toggle off by default
everywhere, plus the rule's ``action`` field carrying only Notify for now.

The point of the slice is the SHAPE. Q3: Option B is built on an engine that can
express Option C's syntax later as a parser onto these fields rather than a
second matcher. The artifact is explicit that this is only free if the rule is
stored as fields with an action from the first slice — bolting an action onto a
rule that shipped as "a pattern that notifies" means migrating every stored
rule.

One measured deviation, recorded here because it contradicts the artifact:
``live_only`` is NOT surfaced in the UI. See
``test_live_only_is_built_but_deliberately_unsurfaced``.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

import pytest

from metatv.core.watchlist_matching import (
    ACTIONS, ALL_WORDS, ANY_WORD, MATCH_MODES, NOTIFY, PHRASE, WatchRule,
    matches, sql_prefilter,
)


# ---------------------------------------------------------------------------
# Match modes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode, adjacent, only_first, either", [
    (PHRASE,    True,  False, False),
    (ALL_WORDS, True,  False, False),
    (ANY_WORD,  True,  True,  True),
])
def test_the_three_modes_combine_terms_differently(mode, adjacent, only_first, either):
    rule = WatchRule(term="Denver, Broncos", match_mode=mode)
    assert matches("Vikings @ Denver Broncos", rule) is adjacent
    assert matches("Denver Nuggets", rule) is only_first
    assert matches("Broncos v Storm", rule) is either


def test_all_words_differs_from_phrase_on_separated_terms():
    """The case that makes ALL_WORDS its own mode rather than a synonym.

    Both require every term; only PHRASE requires them adjacent and in order.
    Without a title that separates them the two modes are indistinguishable,
    which is how a mode dropdown ships doing nothing.
    """
    separated = "Broncos beat the Vikings in Denver"
    assert matches(separated, WatchRule(term="Denver, Broncos", match_mode=ALL_WORDS))
    assert not matches(separated, WatchRule(term="Denver, Broncos", match_mode=PHRASE))


def test_a_one_term_rule_means_the_same_thing_in_every_mode():
    """Changing the dropdown must not change what an existing rule matches.

    Every rule stored before this slice has one term, and the migration stamps
    them ``phrase``. If the modes disagreed on a single term, that stamp would
    silently be a behaviour change.
    """
    for mode in MATCH_MODES:
        rule = WatchRule(term="ATP/WTA Cincinnati", match_mode=mode)
        assert matches("Live: ATP/WTA Cincinnati final", rule)
        assert not matches("ATP Cincinnati", rule)


def test_an_unrecognised_stored_mode_falls_back_to_phrase():
    """A typo in the column must not decide what a rule matches."""
    assert matches("Denver Broncos", WatchRule(term="Denver, Broncos",
                                               match_mode="nonsense"))


def test_a_phrase_survives_the_whitespace_real_guide_titles_carry():
    assert matches("Vikings @ Denver  Broncos", WatchRule(term="Denver Broncos"))
    assert matches("Denver\tBroncos", WatchRule(term="Denver, Broncos"))


# ---------------------------------------------------------------------------
# Description scope
# ---------------------------------------------------------------------------

def test_description_search_is_off_by_default_for_every_rule():
    """Q2, and the reasoning matters: the artifact's author proposed off-for-old
    and on-for-new, then called that "the tell that it was wrong" — two defaults
    for one setting means the checkbox can never be predicted from the setting.
    """
    assert WatchRule(term="Broncos").search_description is False
    desc = "Brisbane Broncos v Storm"
    assert not matches("NRL Premiership", WatchRule(term="Broncos"), description=desc)
    assert matches("NRL Premiership",
                   WatchRule(term="Broncos", search_description=True), description=desc)


def test_excludes_reach_the_description_when_it_is_being_searched():
    rule = WatchRule(term="Broncos", exclude=("highlights",), search_description=True)
    assert not matches("NRL Premiership", rule, description="Broncos highlights")
    assert matches("NRL Premiership", rule, description="Broncos v Storm")


def test_a_phrase_cannot_match_across_the_title_description_seam():
    """Fields are tested separately, not concatenated.

    A title ending "Denver" beside a description starting "Broncos" is not a
    programme about the Broncos, and joining the two would say it was.
    """
    rule = WatchRule(term="Denver Broncos", search_description=True)
    assert not matches("Game ends in Denver", rule, description="Broncos won")


# ---------------------------------------------------------------------------
# live_only — built, and deliberately not surfaced
# ---------------------------------------------------------------------------

def test_live_only_is_built_but_deliberately_unsurfaced():
    """The settled design called this "free — the column already exists". It is not.

    Measured on the owner's library: ``is_live`` is 0 for all 264,047
    programmes, because it is only ever set from a superscript ``ᴸᶦᵛᵉ`` badge
    in the title (``xmltv_parser._strip_badges``) and their feeds do not use
    one. A "Live broadcasts only" checkbox would therefore make every rule
    match nothing — a control that silently empties a list.

    So the FIELD works and the gate is ready, and the editor does not offer it.
    This test pins both halves: if the column ever starts being populated, the
    matcher is correct; and until then nobody re-adds the checkbox by reading
    the artifact without the measurement.
    """
    from metatv.gui import watch_rule_editor

    rule = WatchRule(term="NFL", live_only=True)
    assert matches("NFL Live", rule, is_live=True)
    assert not matches("NFL Live", rule, is_live=False)
    assert not matches("NFL Live", rule), "unknown live-ness must not count as live"

    src = watch_rule_editor.__file__
    with open(src, encoding="utf-8") as fh:
        body = fh.read()
    assert "live_only_check" not in body, (
        "a live-only control reappeared — is_live is 0 on every programme in "
        "the owner's guide, so this would make every rule match nothing")


# ---------------------------------------------------------------------------
# The action field — shape for slices 3-7
# ---------------------------------------------------------------------------

def test_the_action_field_defaults_to_notify_and_knows_the_other_two():
    assert WatchRule(term="x").action == NOTIFY
    assert set(ACTIONS) == {"notify", "download", "record"}


# ---------------------------------------------------------------------------
# The SQL prefilter narrows with the mode
# ---------------------------------------------------------------------------

def _sql(predicate) -> str:
    return str(predicate.compile(compile_kwargs={"literal_binds": True})).lower()


def test_the_prefilter_ands_terms_for_phrase_and_all_but_ors_for_any():
    """Not cosmetic: PHRASE and ALL both require every term, so a row holding
    only one of them can be excluded in SQL instead of being read and rejected
    in Python. ANY is the one case that must OR."""
    from metatv.core.database import EpgProgramDB

    for mode in (PHRASE, ALL_WORDS):
        sql = _sql(sql_prefilter(WatchRule(term="Denver, Broncos", match_mode=mode),
                                 EpgProgramDB.title))
        assert " and " in sql and " or " not in sql, f"{mode}: {sql}"

    sql = _sql(sql_prefilter(WatchRule(term="Denver, Broncos", match_mode=ANY_WORD),
                             EpgProgramDB.title))
    assert " or " in sql


def test_the_prefilter_reaches_the_description_only_when_asked():
    from metatv.core.database import EpgProgramDB

    plain = _sql(sql_prefilter(WatchRule(term="Broncos"),
                               EpgProgramDB.title, EpgProgramDB.description))
    assert "description" not in plain

    wide = _sql(sql_prefilter(WatchRule(term="Broncos", search_description=True),
                              EpgProgramDB.title, EpgProgramDB.description))
    assert "description" in wide


def test_a_blank_rule_prefilters_to_nothing_not_everything():
    from metatv.core.database import EpgProgramDB

    predicate = sql_prefilter(WatchRule(term="   "), EpgProgramDB.title)
    assert predicate is not None
    sql = _sql(predicate)
    assert "is null" in sql and "is not null" in sql


# ---------------------------------------------------------------------------
# Schema upgrade — the path no fresh-DB test runs
# ---------------------------------------------------------------------------

def test_an_existing_database_gains_all_four_new_columns(tmp_path):
    from metatv.core.database import Database

    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE alert_patterns (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
        pattern_type TEXT NOT NULL, pattern_value TEXT NOT NULL,
        applies_to TEXT, is_enabled BOOLEAN, last_checked DATETIME,
        created_at DATETIME, updated_at DATETIME)""")
    con.execute("INSERT INTO alert_patterns (id,name,pattern_type,pattern_value)"
                " VALUES ('1','NFL','keyword','NFL')")
    con.commit()
    con.close()

    Database(f"sqlite:///{path}").create_tables()

    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(alert_patterns)")}
    assert {"match_mode", "search_description", "live_only", "action"} <= cols
    mode, desc, live, action = con.execute(
        "SELECT match_mode, search_description, live_only, action "
        "FROM alert_patterns").fetchone()
    assert (mode, desc, live, action) == ("phrase", 0, 0, "notify"), (
        "an existing rule must carry the settled defaults EXPLICITLY")
    con.close()


# ---------------------------------------------------------------------------
# The write path
# ---------------------------------------------------------------------------

def _bound_db(tmp_path):
    from metatv.core.database import Database

    db = Database(f"sqlite:///{tmp_path / 'rules.db'}")
    db.create_tables()
    return db


class _Cfg:
    epg_watchlist_patterns: list[str] = []


def test_update_writes_rule_fields_and_a_read_never_shows_a_stale_answer(tmp_path):
    from metatv.core import watchlist

    db = _bound_db(tmp_path)
    watchlist.bind(db)
    try:
        watchlist.add(_Cfg(), "Denver")
        watchlist.flush()
        assert watchlist.update(_Cfg(), "Denver", match_mode=ANY_WORD,
                                exclude=("news",), search_description=True)
        # BEFORE the writer thread lands it: the queue overlay must already
        # show the new values, the same promise add/remove make.
        queued = watchlist.rules(_Cfg())[0]
        assert (queued.match_mode, queued.exclude, queued.search_description) == \
            (ANY_WORD, ("news",), True)

        watchlist.flush()
        stored = watchlist.rules(_Cfg())[0]
        assert (stored.match_mode, stored.exclude, stored.search_description) == \
            (ANY_WORD, ("news",), True)
    finally:
        watchlist.unbind()


def test_update_rejects_a_field_that_is_not_a_rule_field(tmp_path):
    from metatv.core import watchlist

    db = _bound_db(tmp_path)
    watchlist.bind(db)
    try:
        with pytest.raises(ValueError):
            watchlist.update(_Cfg(), "Denver", nonsense=1)
    finally:
        watchlist.unbind()


def test_update_reports_failure_on_the_config_store_rather_than_pretending():
    """There is nowhere to put rule fields in the config fallback.

    Returning True there would silently drop the edit — worse than a caller
    that can see it did not take.
    """
    from metatv.core import watchlist

    class _WithPatterns:
        epg_watchlist_patterns = ["Denver"]

    assert watchlist.update(_WithPatterns(), "Denver", match_mode=ANY_WORD) is False


# ---------------------------------------------------------------------------
# The counts that make an exclude list trustworthy
# ---------------------------------------------------------------------------

def test_counts_report_matches_and_what_the_excludes_ate(tmp_path):
    from metatv.core.database import ChannelDB, Database, EpgProgramDB
    from metatv.core.epg_utils import now_utc
    from metatv.core.repositories.epg import EpgRepository

    db = Database(f"sqlite:///{tmp_path / 'counts.db'}")
    db.create_tables()
    now = now_utc()
    titles = ["Denver Broncos v KC", "Denver Broncos Pregame",
              "Denver Broncos Highlights", "Denver News", "Inflammation"]
    with db.session_scope() as s:
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="Chan"))
        for i, title in enumerate(titles):
            s.add(EpgProgramDB(id=100 + i, channel_db_id="c1", channel_epg_id="e",
                               provider_id="p1", title=title, description="",
                               start_time=now + timedelta(hours=1 + i),
                               stop_time=now + timedelta(hours=2 + i)))

    rule = WatchRule(term="Denver Broncos", exclude=("pregame", "highlights"))
    with db.session_scope(commit=False) as s:
        counts = EpgRepository(s).count_for_watchlist([rule])

    matched, suppressed, capped, description_gain = counts["Denver Broncos"]
    assert (matched, suppressed, capped) == (1, 2, False), (
        "three titles carry the phrase and two are excluded — a suppressed "
        "count of 0 here is what 'my exclusions are working' looks like when "
        "it is a lie")
    assert description_gain == 0, (
        "no programme here carries the phrase only in its (empty) "
        "description, so there is nothing for the toggle to gain")


def test_description_gain_reports_what_turning_the_toggle_on_would_find(tmp_path):
    """Q2 ("Catch, Keep, Record"): "the count next to it says what turning it
    on would find" — the fourth number beside matched/suppressed/capped.

    A programme carrying the phrase ONLY in its description is invisible to a
    title-only rule; the gain is exactly the count of those, and drops to 0
    once the rule already searches descriptions — there is nothing left to
    gain from a toggle that is already on.
    """
    from metatv.core.database import ChannelDB, Database, EpgProgramDB
    from metatv.core.epg_utils import now_utc
    from metatv.core.repositories.epg import EpgRepository

    db = Database(f"sqlite:///{tmp_path / 'gain.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as s:
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="Chan"))
        s.add(EpgProgramDB(id=200, channel_db_id="c1", channel_epg_id="e",
                           provider_id="p1", title="Sunday Night Football",
                           description="The Denver Broncos host the Chiefs.",
                           start_time=now + timedelta(hours=1),
                           stop_time=now + timedelta(hours=2)))
        s.add(EpgProgramDB(id=201, channel_db_id="c1", channel_epg_id="e",
                           provider_id="p1", title="Denver Broncos Pregame",
                           description="",
                           start_time=now + timedelta(hours=3),
                           stop_time=now + timedelta(hours=4)))

    off_rule = WatchRule(term="Denver Broncos")
    with db.session_scope(commit=False) as s:
        counts = EpgRepository(s).count_for_watchlist([off_rule])
    matched, _suppressed, _capped, gain = counts["Denver Broncos"]
    assert matched == 1, "only the title match is visible with the toggle off"
    assert gain == 1, (
        "one more programme carries the phrase in its description only — "
        "that is exactly what turning the toggle on would find")

    on_rule = WatchRule(term="Denver Broncos", search_description=True)
    with db.session_scope(commit=False) as s:
        counts = EpgRepository(s).count_for_watchlist([on_rule])
    matched_on, _suppressed_on, _capped_on, gain_on = counts["Denver Broncos"]
    assert matched_on == 2, "both programmes are visible with the toggle on"
    assert gain_on == 0, "nothing left to gain once the toggle is already on"
