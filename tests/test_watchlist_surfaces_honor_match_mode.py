"""WL-1: the two surfaces that RENDER matches must honor the stored rule.

The migration and the matcher (``core/watchlist_matching.py``) shipped
correctly, and so did the rule editor's own trust line — but the trust line
reads ``count_for_watchlist(watchlist.rules(config))``, while the LIVE and
UPCOMING rows on both surfaces (Watch Alerts sidebar, EPG Watchlist tab) were
built from ``watchlist.patterns(config)`` — bare strings — passed into
``get_live_for_watchlist``/``get_upcoming_for_watchlist``. Those call
``as_rules()``, which promotes a bare string to the SETTLED DEFAULT rule:
whole-word, Phrase, no excludes, description search off — silently discarding
whatever match_mode/excludes the user actually set on the row.

So a rule set to "Any word" showed the RIGHT count in its own summary line
("18 matches in the next 7 days") while the list of matches directly below it
kept showing only consecutive-phrase hits — exactly the owner's report,
"Watch Alert Matches without consecutive word matching." Both surfaces now
pass ``watchlist.rules(config)`` — the actual WatchRule objects — into the
row-populating queries, the same object the trust line already used.

Docstring quote from ``core/watchlist.py``'s own ``rules()``: "The rule is
what both surfaces are supposed to share (Q4: 'one list, two surfaces'), so
this — not patterns — is what a matching caller wants." Both call sites now
follow their own module's stated contract.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from metatv.core import watchlist
from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.epg_utils import now_utc
from metatv.core.watchlist_matching import ANY_WORD


class _Cfg:
    epg_watchlist_patterns: list = []


def _bound_db(tmp_path, name: str) -> Database:
    db = Database(f"sqlite:///{tmp_path / name}")
    db.create_tables()
    return db


def _seed_any_word_rule(db, *, exclude=()) -> None:
    """One stored rule, "Denver, Broncos", set to Any word (+ optional excludes)."""
    watchlist.bind(db)
    watchlist.add(_Cfg(), "Denver, Broncos")
    watchlist.flush()
    ok = watchlist.update(_Cfg(), "Denver, Broncos", match_mode=ANY_WORD,
                          exclude=tuple(exclude))
    assert ok, "seeding the rule fields failed — the test proves nothing"
    watchlist.flush()


def _add_channel_and_programme(db, title: str, *, minutes_ahead: int = 30) -> None:
    """One active, EPG-active provider ("p1"), one channel on it, one
    upcoming programme. ``get_epg_active_provider_ids()`` (the sidebar's own
    source gate) requires a real ``urls`` entry, seeded whenever ``epg_url``
    is truthy — same shape as ``tests/test_scoping_provenance.py``'s
    ``_add_provider``.
    """
    now = now_utc()
    with db.session_scope() as s:
        s.merge(ProviderDB(
            id="p1", name="p1", type="xtream", url="http://e.com",
            username="u", password="p",
            urls=[{"url": "http://e.com", "priority": 0}],
            is_active=True, epg_url="http://e/xmltv.php",
        ))
        s.merge(ChannelDB(id="c1", source_id="c1", provider_id="p1", name="Chan"))
        s.add(EpgProgramDB(
            channel_db_id="c1", channel_epg_id="e", provider_id="p1",
            title=title, description="",
            start_time=now + timedelta(minutes=minutes_ahead),
            stop_time=now + timedelta(minutes=minutes_ahead + 60),
        ))


# ---------------------------------------------------------------------------
# Surface 1 — the Watch Alerts sidebar (alerts_epg.EpgGroupMixin._load_rows)
# ---------------------------------------------------------------------------

def test_sidebar_upcoming_matches_honor_any_word_mode(tmp_path):
    """A title with the terms SEPARATED (not the adjacent phrase) must appear
    once the rule is set to Any word — PHRASE mode would reject it.
    """
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _bound_db(tmp_path, "sidebar_any.db")
    try:
        _seed_any_word_rule(db)
        _add_channel_and_programme(db, "Broncos beat the Vikings in Denver")

        obj = WatchAlertsSection.__new__(WatchAlertsSection)
        obj.db = db
        obj.config = _Cfg()

        result = obj._load_rows()

        all_titles = {
            grp["title"] for grp in result["upcoming_only"].values()
        }
        assert "Broncos beat the Vikings in Denver" in all_titles, (
            "Any-word mode must surface a title whose terms are not adjacent; "
            "the sidebar defaulted every rule to Phrase before this fix"
        )
    finally:
        watchlist.unbind()
        db.close()


def test_sidebar_upcoming_matches_honor_exclude_terms(tmp_path):
    """A programme matching an ANY_WORD rule but ALSO an exclude term must be
    suppressed on the sidebar, exactly as the rule row's own count promises.
    """
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    db = _bound_db(tmp_path, "sidebar_exclude.db")
    try:
        _seed_any_word_rule(db, exclude=("pregame",))
        _add_channel_and_programme(db, "Denver Broncos Pregame")

        obj = WatchAlertsSection.__new__(WatchAlertsSection)
        obj.db = db
        obj.config = _Cfg()

        result = obj._load_rows()

        all_titles = {
            grp["title"] for grp in result["upcoming_only"].values()
        }
        assert "Denver Broncos Pregame" not in all_titles, (
            "the exclude term must suppress this row on the sidebar, not "
            "just in the rule editor's own count"
        )
    finally:
        watchlist.unbind()
        db.close()


# ---------------------------------------------------------------------------
# Surface 2 — the EPG Watchlist tab (epg_watchlist_mixin._fetch_watchlist)
# ---------------------------------------------------------------------------

def test_watchlist_tab_upcoming_rows_honor_any_word_mode(tmp_path):
    """Same defect, same fix, the other surface (Q4: one list, two surfaces).

    Exercises ``_reload_watchlist`` itself, not just ``_fetch_watchlist`` —
    the regression was in what ``_reload_watchlist`` BUILDS before handing it
    off (``watchlist.patterns()`` bare strings vs ``watchlist.rules()``), and
    ``_fetch_watchlist`` alone cannot see that: ``as_rules()`` already accepts
    a list of real ``WatchRule`` objects correctly, so calling it directly
    with hand-built rules would pass even on the unfixed code. The executor is
    replaced with a synchronous stand-in (the same bound-method technique
    ``tests/conftest.py``'s ``wire_watchlist_card_host`` uses) so the submitted
    call runs inline instead of on a real thread.
    """
    from metatv.gui.epg_watchlist_mixin import _EpgWatchlistMixin

    db = _bound_db(tmp_path, "tab_any.db")
    try:
        _seed_any_word_rule(db)
        _add_channel_and_programme(db, "Broncos beat the Vikings in Denver")

        cfg = SimpleNamespace(
            epg_watchlist_patterns=[],
            epg_dismissed_channels={},
            epg_watchlist_channels=[],
        )
        payloads = []

        class _SyncExecutor:
            def submit(self, fn, *args, **kwargs):
                fn(*args, **kwargs)

        host = SimpleNamespace(
            db=db,
            config=cfg,
            _channel_name_map={},
            _build_name_map=lambda session, wl, live: {},
            _data_loaded=SimpleNamespace(emit=payloads.append),
            _executor=_SyncExecutor(),
            _filtered_provider_ids=lambda: ["p1"],
            _show_watchlist_loading=lambda: None,
        )
        host._fetch_watchlist = _EpgWatchlistMixin._fetch_watchlist.__get__(host)

        _EpgWatchlistMixin._reload_watchlist(host)

        assert payloads, "no payload was emitted — _fetch_watchlist raised internally"
        titles = {
            prog.title
            for progs in payloads[0]["watchlist_data"].values()
            for prog in progs
        }
        assert "Broncos beat the Vikings in Denver" in titles, (
            "Any-word mode must surface a title whose terms are not adjacent; "
            "the Watchlist tab defaulted every rule to Phrase before this fix "
            "even though its own summary line already counted it correctly"
        )
    finally:
        watchlist.unbind()
        db.close()
