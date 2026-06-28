"""Behavioral tests for EPG guide-coverage honesty.

Root cause (proven against the live DB)
----------------------------------------
``EpgManager._fetch_worker`` was computing ``epg_data_end = max(stop_time)`` over ALL
programmes, including multi-day filler placeholders (e.g. a single "Program" entry
spanning 3 d 19 h).  That inflated ``epg_data_end`` to Jun 27 while the real schedule
depth (latest real programme *start*) was only Jun 24 22:55 UTC, making Browse show
nothing for prime-time tonight while the provider appeared "good through Jun 27".

The fix
-------
``_compute_honest_guide_end`` excludes programmes longer than 12 hours from the
``max_stop`` calculation.  The worker calls this helper instead of tracking ``max_stop``
inline.  The Browse empty-state is also updated to display actual coverage when known.

What these tests guard
-----------------------
A — ``_compute_honest_guide_end`` returns real depth (not filler stop) in the mixed case.
B — The helper fails against the OLD inline ``max(stop_time)`` logic (documented).
C — ``_browse_placeholder_text`` shows coverage when guide_end is known.
D — ``get_schedule`` slot math: prime-time today and tomorrow each return seeded programmes.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from metatv.core.database import ChannelDB, Database, EpgProgramDB
from metatv.core.epg_manager import EPG_FILLER_THRESHOLD, _compute_honest_guide_end
from metatv.core.epg_utils import now_utc
from metatv.core.repositories.epg import EpgRepository
from metatv.core.xmltv_parser import XmltvProgramme
from metatv.gui.epg_browse_mixin import _EpgBrowseMixin


# ---------------------------------------------------------------------------
# A helper XmltvProgramme factory (only the fields the helper reads)
# ---------------------------------------------------------------------------

def _prog(start: datetime, stop: datetime, title: str = "Show") -> XmltvProgramme:
    return XmltvProgramme(
        channel_id="ch1",
        title=title,
        description="",
        start_time=start,
        stop_time=stop,
    )


# ---------------------------------------------------------------------------
# A. _compute_honest_guide_end — unit tests of the pure helper
# ---------------------------------------------------------------------------

_BASE = datetime(2026, 6, 24, 0, 0, 0)  # arbitrary UTC epoch


def test_honest_guide_end_ignores_filler():
    """A multi-day filler must NOT determine epg_data_end when real programmes exist.

    This is the regression test: the old ``max(stop_time)`` code would return the
    filler's stop (Jun 27), while the honest end is the real programme's stop (today).
    """
    real_stop = _BASE + timedelta(hours=22, minutes=55)
    filler_stop = _BASE + timedelta(days=3, hours=19)  # >12 h — filler

    progs = [
        _prog(_BASE + timedelta(hours=20), real_stop, "Premier League"),
        _prog(_BASE + timedelta(hours=4), filler_stop, "Program"),  # filler
    ]

    result = _compute_honest_guide_end(progs)

    assert result == real_stop, (
        f"expected {real_stop} (real programme stop), got {result} — filler is leaking"
    )
    # Explicitly show the old code would have returned the filler stop.
    naive_max = max(p.stop_time for p in progs)
    assert naive_max == filler_stop, "confirm old code returns filler stop"
    assert result != naive_max, "fix must differ from old naive max"


def test_honest_guide_end_all_normal_programmes():
    """All normal-length programmes → straightforward max stop."""
    progs = [
        _prog(_BASE, _BASE + timedelta(hours=1)),
        _prog(_BASE + timedelta(hours=1), _BASE + timedelta(hours=3)),
    ]
    assert _compute_honest_guide_end(progs) == _BASE + timedelta(hours=3)


def test_honest_guide_end_multiple_fillers_picks_latest_real():
    """Multiple fillers + multiple real entries — returns latest real stop."""
    # Real programmes: 30 min and 1 h each (both well under 12 h)
    real_1 = _BASE + timedelta(hours=1, minutes=30)
    real_2 = _BASE + timedelta(hours=2)
    filler_1 = _BASE + timedelta(days=2)
    filler_2 = _BASE + timedelta(days=4)

    progs = [
        _prog(_BASE + timedelta(hours=1), real_1, "News"),       # 30 min
        _prog(_BASE + timedelta(hours=1), real_2, "Sport"),      # 1 h
        _prog(_BASE, filler_1, "Placeholder A"),                  # 48 h
        _prog(_BASE, filler_2, "Placeholder B"),                  # 96 h
    ]
    assert _compute_honest_guide_end(progs) == real_2


def test_honest_guide_end_fallback_when_all_filler():
    """When every programme is filler, fall back to filler max (don't return None)."""
    filler_1 = _BASE + timedelta(days=1)
    filler_2 = _BASE + timedelta(days=3)

    progs = [
        _prog(_BASE, filler_1, "Filler A"),
        _prog(_BASE, filler_2, "Filler B"),
    ]
    assert _compute_honest_guide_end(progs) == filler_2


def test_honest_guide_end_empty_feed():
    """Empty programme list → None (no guide at all)."""
    assert _compute_honest_guide_end([]) is None


def test_filler_threshold_exactly_at_boundary():
    """A programme of exactly 12 h is NOT filler; 12 h + 1 s IS filler."""
    at_limit = _prog(_BASE, _BASE + EPG_FILLER_THRESHOLD, "Long Movie")
    over_limit = _prog(_BASE, _BASE + EPG_FILLER_THRESHOLD + timedelta(seconds=1), "Filler")

    # Exactly 12 h → real programme, contributes to honest guide end
    assert _compute_honest_guide_end([at_limit]) == _BASE + EPG_FILLER_THRESHOLD

    # 12 h + 1 s → filler, falls back to filler bucket
    assert _compute_honest_guide_end([over_limit]) == _BASE + EPG_FILLER_THRESHOLD + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# B. File-backed DB: integration test — honest end is stored, not filler end
# ---------------------------------------------------------------------------

@pytest.fixture()
def coverage_db(tmp_path):
    """A file-backed DB seeded with real + filler programmes under one provider."""
    db = Database(f"sqlite:///{tmp_path / 'coverage.db'}")
    db.create_tables()
    now = datetime(2026, 6, 24, 12, 0, 0)  # fixed UTC

    real_stop   = now + timedelta(hours=10, minutes=55)  # today 22:55 UTC
    filler_stop = now + timedelta(days=3, hours=7)       # Jun 27 19:00 UTC — 3 d 7 h

    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="TRT Spor"))
        # Real programme
        session.add(EpgProgramDB(
            provider_id="p1",
            channel_epg_id="trt.spor",
            channel_db_id="c1",
            channel_name="TRT Spor",
            title="Turkish Super League",
            description="",
            start_time=now + timedelta(hours=8),
            stop_time=real_stop,
        ))
        # Multi-day filler (the kind that was inflating epg_data_end)
        for i in range(21):
            session.add(EpgProgramDB(
                provider_id="p1",
                channel_epg_id="trt.spor",
                channel_db_id="c1",
                channel_name="TRT Spor",
                title="Program",
                description="",
                start_time=now - timedelta(hours=i * 4),
                stop_time=filler_stop,
            ))

    return db, real_stop, filler_stop


def test_epg_data_end_excludes_filler_via_helper(coverage_db):
    """Simulate what _fetch_worker does: call the helper on the programmes list and
    confirm the result is the real stop, not the filler stop.

    This test FAILS against the OLD ``max(stop_time)`` logic.
    """
    db, real_stop, filler_stop = coverage_db

    # Re-read the stored programmes (as XmltvProgramme equivalents via DB rows).
    with db.session_scope(commit=False) as session:
        rows = session.query(EpgProgramDB).filter_by(provider_id="p1").all()
        # Convert to XmltvProgramme objects so we can drive the pure helper.
        programmes = [
            XmltvProgramme(
                channel_id=r.channel_epg_id,
                title=r.title,
                description=r.description or "",
                start_time=r.start_time,
                stop_time=r.stop_time,
            )
            for r in rows
        ]

    honest_end = _compute_honest_guide_end(programmes)

    assert honest_end == real_stop, (
        f"epg_data_end should reflect real programme depth ({real_stop}), "
        f"not filler stop ({filler_stop}).  Got: {honest_end}"
    )

    # Prove the old naive max differs.
    naive_max = max(p.stop_time for p in programmes)
    assert naive_max == filler_stop
    assert honest_end != naive_max


# ---------------------------------------------------------------------------
# C. Browse empty-state: coverage-aware placeholder text
# ---------------------------------------------------------------------------

def _make_browse_host(*, provider_ids, search_text, guide_end=None):
    """Minimal _EpgBrowseMixin host for _browse_placeholder_text."""
    from PyQt6.QtWidgets import QLabel
    host = _EpgBrowseMixin.__new__(_EpgBrowseMixin)
    host._provider_ids = list(provider_ids)
    host._filtered_provider_ids = lambda: host._provider_ids
    host.search_input = SimpleNamespace(text=lambda: search_text)
    return host


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_placeholder_shows_guide_end_when_known(qapp):
    """When the slot is empty but guide_end is known, the message names the date/time."""
    guide_end = datetime(2026, 6, 24, 22, 55, 0)  # UTC-naive
    host = _make_browse_host(provider_ids=["p1"], search_text="")
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=guide_end)
    assert "guide currently reaches" in text
    assert "No programmes for the selected day" not in text


def test_placeholder_generic_when_guide_end_unknown(qapp):
    """When guide_end is None (not fetched or missing), falls back to generic message."""
    host = _make_browse_host(provider_ids=["p1"], search_text="")
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=None)
    assert text == "No upcoming programmes in the guide."


def test_placeholder_no_sources(qapp):
    """No EPG sources → the source message, regardless of guide_end."""
    host = _make_browse_host(provider_ids=[], search_text="")
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=datetime(2026, 6, 24))
    assert "No EPG sources" in text


def test_placeholder_search_nomatch(qapp):
    """Active search with no results → search message, not coverage message."""
    host = _make_browse_host(provider_ids=["p1"], search_text="unknownxyz")
    text = _EpgBrowseMixin._browse_placeholder_text(host, guide_end=datetime(2026, 6, 24))
    assert "match your search" in text


# ---------------------------------------------------------------------------
# D. get_schedule slot math: primetime today and tomorrow (regression pins)
# ---------------------------------------------------------------------------

_TZ_UTC = zoneinfo.ZoneInfo("UTC")


@pytest.fixture()
def slot_db(tmp_path):
    """File-backed DB with programmes covering tonight prime-time and tomorrow."""
    db = Database(f"sqlite:///{tmp_path / 'slot.db'}")
    db.create_tables()

    # Use a fixed UTC timezone so slot windows are deterministic in CI.
    today = date(2026, 6, 24)
    tomorrow = today + timedelta(days=1)

    # tonight primetime: start_time UTC = 2026-06-24 19:00 (slot 18-23 UTC)
    prime_start = datetime(2026, 6, 24, 19, 30, 0)
    prime_stop  = datetime(2026, 6, 24, 21, 0, 0)

    # tomorrow: start_time UTC = 2026-06-25 20:00
    tmr_start = datetime(2026, 6, 25, 20, 0, 0)
    tmr_stop  = datetime(2026, 6, 25, 22, 0, 0)

    with db.session_scope() as session:
        session.add(ChannelDB(id="c1", source_id="s1", provider_id="p1", name="ESPN"))
        session.add(EpgProgramDB(
            provider_id="p1",
            channel_epg_id="espn",
            channel_db_id="c1",
            channel_name="ESPN",
            title="Champions League Final",
            description="",
            start_time=prime_start,
            stop_time=prime_stop,
        ))
        session.add(EpgProgramDB(
            provider_id="p1",
            channel_epg_id="espn",
            channel_db_id="c1",
            channel_name="ESPN",
            title="Tomorrow Night Football",
            description="",
            start_time=tmr_start,
            stop_time=tmr_stop,
        ))

    return db, today, tomorrow


def _with_utc_tz():
    """Context manager: patch _local_tz to return UTC so slot windows are deterministic."""
    return patch("metatv.core.repositories.epg._local_tz", side_effect=lambda: _TZ_UTC)


def test_get_schedule_primetime_returns_evening_programme(slot_db):
    """Primetime slot (18-23 local) returns the 19:30 programme on the same day.

    Uses UTC as local timezone so slot math is deterministic.
    """
    db, today, _ = slot_db

    with _with_utc_tz():
        session = db.get_session()
        try:
            progs = EpgRepository(session).get_schedule(
                target_date=today,
                provider_ids=["p1"],
                time_slot="primetime",
            )
            titles = [p.title for p in progs]
        finally:
            session.close()

    assert len(titles) == 1
    assert "Champions League Final" in titles


def test_get_schedule_today_all_excludes_tomorrow(slot_db):
    """'All Day' for today does not include tomorrow's programme."""
    db, today, _ = slot_db

    with _with_utc_tz():
        session = db.get_session()
        try:
            progs = EpgRepository(session).get_schedule(
                target_date=today,
                provider_ids=["p1"],
                time_slot="all",
            )
            titles = [p.title for p in progs]
        finally:
            session.close()

    assert "Champions League Final" in titles
    assert "Tomorrow Night Football" not in titles


def test_get_schedule_tomorrow_returns_tomorrow_programme(slot_db):
    """Selecting tomorrow's date returns tomorrow's seeded programme, not today's."""
    db, _, tomorrow = slot_db

    with _with_utc_tz():
        session = db.get_session()
        try:
            progs = EpgRepository(session).get_schedule(
                target_date=tomorrow,
                provider_ids=["p1"],
                time_slot="all",
            )
            titles = [p.title for p in progs]
        finally:
            session.close()

    assert len(titles) == 1
    assert "Tomorrow Night Football" in titles


def test_get_schedule_latenight_slot_empty_no_latenight_programmes(slot_db):
    """Late night slot (23-03) on today returns nothing (no programme in that window)."""
    db, today, _ = slot_db

    with _with_utc_tz():
        session = db.get_session()
        try:
            progs = EpgRepository(session).get_schedule(
                target_date=today,
                provider_ids=["p1"],
                time_slot="latenight",
            )
            count = len(progs)
        finally:
            session.close()

    assert count == 0
