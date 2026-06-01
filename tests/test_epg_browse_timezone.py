"""Regression test for P0-2: EPG browse date picker uses local date against UTC-naive storage.

T0-2 from REFACTOR_PLAN: with a frozen non-UTC local timezone, a programme at
UTC 2026-06-01T02:00 (which is 2026-05-31 19:00 in UTC-7) must appear when
browsing local date 2026-05-31, NOT when browsing 2026-06-01.

This test FAILS on unfixed code and PASSES after the P0-2 fix.
"""

import sys
import zoneinfo
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from metatv.core.database import Base, EpgProgramDB
from metatv.core.repositories.epg import EpgRepository


_PROVIDER_ID = "prov_test"
_CHANNEL_DB_ID = "ch1"
_CHANNEL_EPG_ID = "ch1.epg"

# The programme is at UTC 2026-06-01T02:00:00 — naive (as stored by parser).
# In UTC-7 this is 2026-05-31T19:00:00 (local), so it belongs to local May 31.
_PROG_UTC_START = datetime(2026, 6, 1, 2, 0, 0)   # naive UTC
_PROG_UTC_STOP  = datetime(2026, 6, 1, 3, 0, 0)   # naive UTC


@pytest.fixture()
def db_session_epg():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture()
def seeded_repo(db_session_epg):
    prog = EpgProgramDB(
        provider_id=_PROVIDER_ID,
        channel_epg_id=_CHANNEL_EPG_ID,
        channel_db_id=_CHANNEL_DB_ID,
        title="Night Show",
        description="",
        start_time=_PROG_UTC_START,
        stop_time=_PROG_UTC_STOP,
    )
    db_session_epg.add(prog)
    db_session_epg.flush()
    return EpgRepository(db_session_epg)


def _utc_minus_7():
    """Return a fixed UTC-7 tzinfo using zoneinfo (no DST complications)."""
    return timezone(timedelta(hours=-7))


def test_programme_appears_on_local_may31(seeded_repo):
    """With UTC-7 local tz, the UTC+02:00 programme belongs to local May 31."""
    local_tz = _utc_minus_7()
    with patch("metatv.core.repositories.epg._local_tz", lambda: local_tz):
        results = seeded_repo.get_schedule(
            target_date=date(2026, 5, 31),
            provider_ids=[_PROVIDER_ID],
        )
    assert len(results) == 1, (
        f"Expected programme on local 2026-05-31 (UTC-7), got {len(results)}. "
        "Bug: get_schedule treats the local date as UTC instead of converting."
    )
    assert results[0].title == "Night Show"


def test_programme_absent_on_local_june1(seeded_repo):
    """With UTC-7 local tz, the programme must NOT appear on local June 1."""
    local_tz = _utc_minus_7()
    with patch("metatv.core.repositories.epg._local_tz", lambda: local_tz):
        results = seeded_repo.get_schedule(
            target_date=date(2026, 6, 1),
            provider_ids=[_PROVIDER_ID],
        )
    assert len(results) == 0, (
        f"Expected no programmes on local 2026-06-01 (UTC-7), got {len(results)}. "
        "Bug: programme leaked into the wrong local date window."
    )


def test_time_slot_morning_in_utc7(seeded_repo):
    """Time-slot windows must also be relative to local time (not UTC).

    UTC 2026-06-01T15:00 = 2026-06-01T08:00 local (UTC-7) → morning slot.
    """
    morning_prog = EpgProgramDB(
        provider_id=_PROVIDER_ID,
        channel_epg_id=_CHANNEL_EPG_ID,
        channel_db_id=_CHANNEL_DB_ID,
        title="Morning News",
        description="",
        start_time=datetime(2026, 6, 1, 15, 0, 0),   # 08:00 UTC-7
        stop_time=datetime(2026, 6, 1, 16, 0, 0),
    )
    seeded_repo.session.add(morning_prog)
    seeded_repo.session.flush()

    local_tz = _utc_minus_7()
    with patch("metatv.core.repositories.epg._local_tz", lambda: local_tz):
        results = seeded_repo.get_schedule(
            target_date=date(2026, 6, 1),
            provider_ids=[_PROVIDER_ID],
            time_slot="morning",
        )
    titles = [r.title for r in results]
    assert "Morning News" in titles, (
        f"Expected 'Morning News' in morning slot for local 2026-06-01 (UTC-7), "
        f"got: {titles}"
    )
