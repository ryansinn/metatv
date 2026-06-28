"""Behavioral tests for the EPG Browse tab's date/time schedule browser.

Regression context
------------------
Browse is a date/time-driven schedule browser: choosing a day + time slot should
list every programme in that window (``EpgRepository.get_schedule``); a text search
*narrows* to matching upcoming programmes (``search_programs``).

Commit ``dd576bf`` added an ``if not search: emit(placeholder); return`` gate to the
``_EpgBrowseMixin._reload_browse`` trigger. That gate made ``_fetch_browse`` — and
therefore the entire ``get_schedule`` branch — **unreachable whenever the search box
is empty**, which is the default state. Result: the Browse tab showed only its
"Search for a programme…" placeholder and the date/time/hide-filler controls did
nothing — "the Browse interface doesn't work at all anymore." Only typing a search
term produced any rows.

These tests pin the fixed behavior:

1. Data layer — ``get_schedule`` returns the day's programmes (the branch Browse
   relies on for its primary, no-search mode).
2. Trigger layer (the regressing half) — ``_reload_browse`` with an EMPTY search box
   reaches ``_fetch_browse``/``get_schedule`` instead of short-circuiting to the
   placeholder. This is the assertion that fails against the bug.
3. Render layer — ``_render_browse`` shows the schedule rows when present and falls
   back to the empty-state placeholder (not a bare empty tree) when there are none.
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB
from metatv.core.epg_utils import now_utc, to_local
from metatv.core.repositories.epg import EpgRepository
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin


# ---------------------------------------------------------------------------
# Qt fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------------------
# DB fixture — file-backed (NOT :memory:, whose pooled connections each get an
# empty DB), seeded with one channel + one upcoming programme today.
# ---------------------------------------------------------------------------

@pytest.fixture()
def seeded_db(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'epg_browse.db'}")
    db.create_tables()
    now = now_utc()
    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN HD"))
        session.add(
            EpgProgramDB(
                provider_id="p1",
                channel_epg_id="espn.us",
                channel_db_id="c1",
                channel_name="ESPN HD",
                title="Premier League: Arsenal vs Chelsea",
                description="Football match",
                start_time=now + timedelta(hours=1),
                stop_time=now + timedelta(hours=3),
                is_live=True,
                is_new=False,
            )
        )
    return db, now


# ---------------------------------------------------------------------------
# 1. Data layer — get_schedule returns the day's programmes (no search).
# ---------------------------------------------------------------------------

def test_get_schedule_returns_day_programmes_without_search(seeded_db):
    db, now = seeded_db
    session = db.get_session()
    try:
        # get_schedule windows by LOCAL day (its contract); convert the UTC `now`
        # to the local date so the seeded programme falls in the window regardless
        # of the run-time UTC offset (CLAUDE.md: never `.date()` UTC-anchored).
        progs = EpgRepository(session).get_schedule(
            target_date=to_local(now).date(), provider_ids=["p1"]
        )
        assert len(progs) == 1
        assert progs[0].title.startswith("Premier League")
    finally:
        session.close()


def test_get_schedule_empty_provider_ids_returns_nothing(seeded_db):
    """Guards the other half: an empty provider include-list yields no rows, which is
    why ``_reload_browse`` must short-circuit only on empty providers — not on empty
    search."""
    db, _ = seeded_db
    session = db.get_session()
    try:
        progs = EpgRepository(session).get_schedule(
            target_date=now_utc().date(), provider_ids=[]
        )
        assert progs == []
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Trigger-layer host: a lightweight _EpgBrowseMixin instance whose executor and
# data-signal are captured so we can see which path _reload_browse takes.
# ---------------------------------------------------------------------------

def _make_trigger_host(*, search_text: str, provider_ids):
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    # Search box + filter widgets the trigger reads.
    host.search_input = SimpleNamespace(text=lambda: search_text)
    host.date_combo = SimpleNamespace(currentData=lambda: now_utc().date())
    host.time_combo = SimpleNamespace(currentData=lambda: "all")
    host.hide_filler_btn = SimpleNamespace(isChecked=lambda: False)
    # Capture executor submissions and emitted payloads.
    host.submitted = []
    host._executor = SimpleNamespace(
        submit=lambda fn, *a: host.submitted.append((fn, a))
    )
    host.emitted = []
    host._data_loaded = SimpleNamespace(emit=lambda payload: host.emitted.append(payload))
    return host


# ---------------------------------------------------------------------------
# 2. Trigger layer — the regressing half.
# ---------------------------------------------------------------------------

def test_reload_browse_empty_search_fetches_schedule_not_placeholder():
    """REGRESSION: empty search must reach _fetch_browse (the schedule branch),
    NOT short-circuit to a placeholder. Fails against dd576bf's gate."""
    host = _make_trigger_host(search_text="", provider_ids=["p1"])
    _EpgBrowseMixin._reload_browse(host)
    # A schedule fetch was submitted — Browse is alive with an empty search.
    assert len(host.submitted) == 1, "empty search should still fetch the schedule"
    fn, args = host.submitted[0]
    assert fn == host._fetch_browse
    provider_ids, target_date, time_slot, search, hide_filler = args
    assert search == "", "search term forwarded as empty (schedule mode)"
    assert provider_ids == ["p1"]
    # And crucially it did NOT emit the placeholder-only payload.
    assert host.emitted == []


def test_reload_browse_with_search_still_fetches():
    """A non-empty search also fetches (search-narrowing mode) — unchanged."""
    host = _make_trigger_host(search_text="Arsenal", provider_ids=["p1"])
    _EpgBrowseMixin._reload_browse(host)
    assert len(host.submitted) == 1
    _, args = host.submitted[0]
    assert args[3] == "Arsenal"
    assert host.emitted == []


def test_reload_browse_no_providers_emits_placeholder():
    """With no EPG sources, short-circuit to the placeholder (the query could only
    return empty) — and do NOT submit a doomed fetch."""
    host = _make_trigger_host(search_text="", provider_ids=[])
    _EpgBrowseMixin._reload_browse(host)
    assert host.submitted == []
    assert len(host.emitted) == 1
    assert host.emitted[0]["tab"] == "browse"
    assert host.emitted[0]["placeholder"] is True


# ---------------------------------------------------------------------------
# Render-layer host: real QTreeWidget + label stubs.
# ---------------------------------------------------------------------------

def _make_render_host(qapp, *, provider_ids, search_text, name_map):
    from PyQt6.QtWidgets import QTreeWidget, QLabel

    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host.config = SimpleNamespace(epg_watchlist_patterns=[])
    host._channel_name_map = dict(name_map)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: search_text)
    host.browse_list = QTreeWidget()
    host.browse_list.setColumnCount(4)
    host.browse_list.setHeaderLabels(["Time", "Channel", "Show", "Duration"])
    host.browse_placeholder = QLabel()
    host.browse_stats = QLabel()
    host.status_message = SimpleNamespace(emit=MagicMock())
    return host


# ---------------------------------------------------------------------------
# 3. Render layer.
# ---------------------------------------------------------------------------

def test_render_browse_renders_schedule_rows(qapp, seeded_db):
    db, now = seeded_db
    # Fetch real (then-detached) programmes the way _fetch_browse does: a plain
    # get_session() + close() (no commit/rollback), so loaded scalar columns stay
    # readable on the main-thread render even after the session closes.
    session = db.get_session()
    progs = EpgRepository(session).get_schedule(
        target_date=to_local(now).date(), provider_ids=["p1"]
    )
    session.close()
    host = _make_render_host(
        qapp, provider_ids=["p1"], search_text="", name_map={"c1": "ESPN HD"}
    )
    _EpgBrowseMixin._render_browse(host, progs)
    assert host.browse_list.topLevelItemCount() == 1
    item = host.browse_list.topLevelItem(0)
    assert item.text(1) == "ESPN HD"
    assert "Premier League" in item.text(2)
    assert host.browse_stats.text() == "1 programmes"


def test_render_browse_empty_schedule_shows_placeholder(qapp):
    """No programmes for the day → placeholder shown, not a bare empty tree."""
    host = _make_render_host(
        qapp, provider_ids=["p1"], search_text="", name_map={}
    )
    _EpgBrowseMixin._render_browse(host, [])
    assert host.browse_placeholder.text() == "No programmes for the selected day and time."
    assert host.browse_stats.text() == ""
    assert host.browse_list.topLevelItemCount() == 0


def test_render_browse_empty_no_sources_message(qapp):
    host = _make_render_host(
        qapp, provider_ids=[], search_text="", name_map={}
    )
    _EpgBrowseMixin._render_browse(host, [])
    assert "No EPG sources" in host.browse_placeholder.text()
