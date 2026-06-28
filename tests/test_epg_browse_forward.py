"""Behavioral tests for the forward-looking EPG Browse model (Phase 1).

Browse retired the calendar-day × bounded-time-slot picker in favour of a single
forward START ANCHOR (Now / Tonight / Tomorrow / …): the list runs chronologically
forward from the anchor, never shows the past, and pages in via keyset pagination.

Two layers are pinned:

1. Repository — ``EpgRepository.get_schedule_forward`` (real ``Database`` on a
   ``tmp_path`` file, per the tests rule): never returns ``start_time < now``,
   orders ascending, paginates across a page boundary, honours the max-age floor,
   and respects ``excluded_channel_provider_ids`` + ``search_query``.
2. UI wiring — ``_EpgBrowseMixin``/``_EpgWatchlistMixin``: selecting an anchor
   fetches forward from that anchor (page 1), "load more" advances the keyset
   cursor, and a stale page (older reload generation) is dropped.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB, ProviderDB
from metatv.core.repositories.epg import EpgRepository
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin
from metatv.gui.epg_watchlist_mixin import _EpgWatchlistMixin


# ---------------------------------------------------------------------------
# Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# DB fixture — file-backed, programmes spanning past→future across two providers.
# p1 = visible feed (channel c1); p2 = hidden provider (channel c2, cross-matched
# by the p1 feed). One future row is UNMATCHED (channel_db_id NULL).
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 28, 12, 0, 0)  # UTC-naive reference "now"


@pytest.fixture()
def forward_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'epg_forward.db'}")
    db.create_tables()
    with db.session_scope() as s:
        s.add(ProviderDB(id="p1", name="Visible", type="xtream", url="http://a",
                         username="u", password="p", is_active=True))
        s.add(ProviderDB(id="p2", name="Hidden", type="xtream", url="http://b",
                         username="u", password="p", is_active=False))
        s.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN HD",
                        detected_title="ESPN"))
        s.add(ChannelDB(id="c2", source_id="s2", provider_id="p2", name="FOX HD",
                        detected_title="FOX"))

        def _prog(cid, title, start, *, matched=True):
            s.add(EpgProgramDB(
                provider_id="p1",
                channel_epg_id=f"{cid}.epg",
                channel_db_id=(cid if matched else None),
                channel_name=cid,
                title=title,
                description="",
                start_time=start,
                stop_time=start + timedelta(hours=1),
            ))

        # Past — must NEVER appear in a forward query.
        _prog("c1", "Past Show", _NOW - timedelta(hours=2))
        # Unmatched future — excluded by the channel_db_id IS NOT NULL filter.
        _prog("c1", "Unmatched", _NOW + timedelta(minutes=30), matched=False)
        # Future, matched (ascending). Note Hidden Match interleaves by start time.
        _prog("c1", "Show 1",      _NOW + timedelta(hours=1))
        _prog("c2", "Hidden Match", _NOW + timedelta(minutes=90))
        _prog("c1", "Show 2",      _NOW + timedelta(hours=2))
        _prog("c1", "Big Match",   _NOW + timedelta(hours=3))
        _prog("c1", "Show 3",      _NOW + timedelta(hours=4))
    return db


def _repo(db):
    return EpgRepository(db.get_session())


# ===========================================================================
# 1. Repository — get_schedule_forward
# ===========================================================================

def test_forward_never_returns_the_past(forward_db):
    """(a) No programme with start_time < now is ever returned."""
    session = forward_db.get_session()
    try:
        progs = EpgRepository(session).get_schedule_forward(["p1"], _now=_NOW)
        assert progs, "expected upcoming programmes"
        assert all(p.start_time >= _NOW for p in progs), "past programme leaked"
        titles = {p.title for p in progs}
        assert "Past Show" not in titles
        assert "Unmatched" not in titles  # channel_db_id IS NOT NULL filter
    finally:
        session.close()


def test_forward_orders_ascending(forward_db):
    """(b) Results are ordered ascending by start_time."""
    session = forward_db.get_session()
    try:
        progs = EpgRepository(session).get_schedule_forward(["p1"], _now=_NOW)
        starts = [p.start_time for p in progs]
        assert starts == sorted(starts), "forward list must be chronological"
        # The expected matched-future order (Hidden Match interleaves at +90m).
        assert [p.title for p in progs] == [
            "Show 1", "Hidden Match", "Show 2", "Big Match", "Show 3",
        ]
    finally:
        session.close()


def test_forward_paginates_across_page_boundary(forward_db):
    """(c) Keyset pagination returns successive, non-overlapping ascending pages."""
    session = forward_db.get_session()
    try:
        repo = EpgRepository(session)
        full = repo.get_schedule_forward(["p1"], _now=_NOW)

        page1 = repo.get_schedule_forward(["p1"], _now=_NOW, limit=2)
        assert [p.title for p in page1] == ["Show 1", "Hidden Match"]

        cursor = (page1[-1].start_time, page1[-1].id)
        page2 = repo.get_schedule_forward(["p1"], _now=_NOW, limit=2, after=cursor)
        assert [p.title for p in page2] == ["Show 2", "Big Match"]

        cursor = (page2[-1].start_time, page2[-1].id)
        page3 = repo.get_schedule_forward(["p1"], _now=_NOW, limit=2, after=cursor)
        assert [p.title for p in page3] == ["Show 3"]
        assert len(page3) < 2, "short final page signals exhaustion"

        # Pages concatenate to the full ordered list with no gaps or overlaps.
        paged_ids = [p.id for p in (page1 + page2 + page3)]
        assert paged_ids == [p.id for p in full]
        assert len(paged_ids) == len(set(paged_ids)), "no row returned twice"
    finally:
        session.close()


def test_forward_honors_max_age_floor(forward_db):
    """(d) Max-age floor is wired; the >= now floor dominates so a far-past anchor
    with a tight max_age still returns only future rows (never the past)."""
    session = forward_db.get_session()
    try:
        repo = EpgRepository(session)
        progs = repo.get_schedule_forward(
            ["p1"],
            anchor=_NOW - timedelta(hours=100),  # far in the past
            max_age=timedelta(hours=1),
            _now=_NOW,
        )
        assert progs, "future rows should still be returned"
        assert all(p.start_time >= _NOW for p in progs), (
            "max-age floor must not loosen the forward (>= now) floor"
        )
    finally:
        session.close()


def test_forward_respects_exclusion_and_search(forward_db):
    """(e) excluded_channel_provider_ids drops hidden-provider channels and
    search_query narrows within the forward window."""
    session = forward_db.get_session()
    try:
        repo = EpgRepository(session)

        # Exclusion only: c2 (hidden p2) drops out entirely.
        scoped = repo.get_schedule_forward(
            ["p1"], _now=_NOW, excluded_channel_provider_ids={"p2"},
        )
        assert "Hidden Match" not in {p.title for p in scoped}
        assert {p.channel_db_id for p in scoped} == {"c1"}

        # Search without exclusion matches both "Match" titles (ascending).
        both = repo.get_schedule_forward(["p1"], _now=_NOW, search_query="Match")
        assert [p.title for p in both] == ["Hidden Match", "Big Match"]

        # Search + exclusion → only the visible channel's match.
        narrowed = repo.get_schedule_forward(
            ["p1"], _now=_NOW, search_query="Match",
            excluded_channel_provider_ids={"p2"},
        )
        assert [p.title for p in narrowed] == ["Big Match"]
    finally:
        session.close()


def test_forward_floors_past_anchor_to_now(forward_db):
    """A past anchor behaves like 'Now' — it never moves the window backward."""
    session = forward_db.get_session()
    try:
        repo = EpgRepository(session)
        at_now = repo.get_schedule_forward(["p1"], _now=_NOW)
        past = repo.get_schedule_forward(
            ["p1"], anchor=_NOW - timedelta(days=1), _now=_NOW,
        )
        assert [p.id for p in past] == [p.id for p in at_now]
    finally:
        session.close()


def test_forward_future_anchor_skips_earlier_rows(forward_db):
    """A future anchor starts the list at that point (earlier upcoming rows drop)."""
    session = forward_db.get_session()
    try:
        repo = EpgRepository(session)
        progs = repo.get_schedule_forward(
            ["p1"], anchor=_NOW + timedelta(hours=2, minutes=30), _now=_NOW,
        )
        # Only rows starting at/after now+2h30m: Big Match (+3h), Show 3 (+4h).
        assert [p.title for p in progs] == ["Big Match", "Show 3"]
    finally:
        session.close()


# ===========================================================================
# 2. UI wiring — anchor reload, keyset load-more, stale-page guard
# ===========================================================================

def _make_browse_host(*, anchor, provider_ids=("p1",), search=""):
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: search)
    host.anchor_combo = SimpleNamespace(currentData=lambda: anchor)
    host.hide_filler_btn = SimpleNamespace(isChecked=lambda: False)
    host.submitted = []
    host._executor = SimpleNamespace(submit=lambda fn, *a: host.submitted.append((fn, a)))
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda p: host.emitted.append(p))
    return host


def test_reload_browse_fetches_forward_from_anchor():
    """Selecting an anchor submits a page-1 forward fetch from that anchor."""
    anchor = datetime(2026, 6, 28, 18, 0)
    host = _make_browse_host(anchor=anchor)
    _EpgBrowseMixin._reload_browse(host)
    assert len(host.submitted) == 1
    fn, args = host.submitted[0]
    assert fn == host._fetch_browse
    provider_ids, got_anchor, search, hide_filler, after, append, gen = args
    assert got_anchor == anchor
    assert after is None and append is False
    assert gen == host._browse_gen == 1
    assert host._browse_cursor is None and host._browse_exhausted is False


def test_load_more_advances_cursor():
    """'Load more' submits an append fetch with the stored keyset cursor."""
    anchor = datetime(2026, 6, 28, 18, 0)
    host = _make_browse_host(anchor=anchor)
    cursor = (datetime(2026, 6, 28, 19, 0), 42)
    host._browse_gen = 3
    host._browse_loading = False
    host._browse_exhausted = False
    host._browse_cursor = cursor
    _EpgBrowseMixin._load_more_browse(host)
    assert len(host.submitted) == 1
    fn, args = host.submitted[0]
    _provider_ids, _anchor, _search, _hide, after, append, gen = args
    assert after == cursor, "load-more must page from the keyset cursor"
    assert append is True
    assert gen == 3, "load-more keeps the current reload generation"


def test_load_more_noop_when_exhausted():
    """No fetch is issued once the forward list is exhausted."""
    host = _make_browse_host(anchor=None)
    host._browse_loading = False
    host._browse_exhausted = True
    host._browse_cursor = (datetime(2026, 6, 28, 19, 0), 42)
    _EpgBrowseMixin._load_more_browse(host)
    assert host.submitted == []


def test_load_more_noop_when_already_loading():
    """No duplicate fetch while a page is in flight."""
    host = _make_browse_host(anchor=None)
    host._browse_loading = True
    host._browse_exhausted = False
    host._browse_cursor = (datetime(2026, 6, 28, 19, 0), 42)
    _EpgBrowseMixin._load_more_browse(host)
    assert host.submitted == []


def _make_dispatch_host(*, gen):
    host = _EpgWatchlistMixin.__new__(_EpgWatchlistMixin)
    host.search_input = SimpleNamespace(text=lambda: "")
    host._browse_gen = gen
    host._render_browse = MagicMock()
    return host


def test_dispatch_advances_cursor_and_renders_append():
    """A current-generation page updates the cursor/exhausted state and renders
    in append mode."""
    host = _make_dispatch_host(gen=5)
    cursor = (datetime(2026, 6, 28, 19, 0), 7)
    payload = {
        "tab": "browse", "programs": ["row"], "append": True, "gen": 5,
        "cursor": cursor, "exhausted": False, "search": "",
    }
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_called_once()
    # append flag forwarded as the 4th positional arg.
    assert host._render_browse.call_args[0][3] is True
    assert host._browse_cursor == cursor
    assert host._browse_exhausted is False
    assert host._browse_loading is False


def test_dispatch_drops_stale_generation_page():
    """A page from an older reload generation (user changed the anchor) is dropped
    so it can't append onto the freshly-cleared list."""
    host = _make_dispatch_host(gen=9)
    payload = {
        "tab": "browse", "programs": ["stale"], "append": True, "gen": 4,
        "cursor": (datetime(2026, 6, 28, 19, 0), 1), "exhausted": False, "search": "",
    }
    _EpgWatchlistMixin._on_data_loaded(host, payload)
    host._render_browse.assert_not_called()
