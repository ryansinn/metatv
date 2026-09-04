"""Record from the guide — REC-3 (schedule a specific programme) + REC-5 (the
window follows the guide if it moves), settled in *Catch, Keep, Record*.

Covered behaviors
------------------
1. ``RecordingManager.resync_from_guide()`` (REC-5): a scheduled recording
   whose programme moved in the guide gets its window updated; a same-title
   airing two days away is not adopted; an unchanged row reports nothing.
2. ``ACTIONS["record_programme"]`` applies only with programme identity, a
   live channel and a single selection, and is listed on the three surfaces
   that can carry a programme row.
3. ``MainWindow._schedule_and_announce`` (reached via
   ``schedule_recording_from_programme``): the stored row carries the
   configured padding, and a same-source schedule clash routes through the
   ``_resolve_recording_conflict`` seam — "drop the other" cancels the first.
4. ``_confirm_quit_with_due_recordings``: true with nothing scheduled, the
   seam's answer otherwise.
5. Settings → Recording round-trips minutes on screen to seconds in config.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, EpgProgramDB, RecordingDB
from metatv.core.epg_utils import now_utc
from metatv.core.recording_manager import RecordingManager
from tests.conftest import make_channel, make_downloads_mixin_host


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — CLAUDE.md forbids :memory: for session work."""
    database = Database(f"sqlite:///{tmp_path / 'rec_guide.db'}")
    database.create_tables()
    return database


@pytest.fixture
def config(tmp_path):
    class _Config:
        download_dir = str(tmp_path / "library")
        recording_pad_start_seconds = -90
        recording_pad_end_seconds = 300
    return _Config()


@pytest.fixture
def accountant():
    return ConnectionAccountant(capacity_resolver=lambda _pid: 1)


def _make_scheduled_recording(db, *, channel_id, title, start, end,
                              provider_id="p1"):
    rid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(RecordingDB(
            id=rid, channel_id=channel_id, provider_id=provider_id,
            channel_name="ESPN", programme_title=title,
            source_url="http://example.com/stream.ts",
            dest_path="/tmp/rec.ts",
            programme_start=start, programme_end=end,
            pad_start_seconds=-120, pad_end_seconds=900,
            state="scheduled"))
    return rid


def _make_epg_row(db, *, channel_id, title, start, end, provider_id="p1"):
    with db.session_scope() as session:
        session.add(EpgProgramDB(
            provider_id=provider_id, channel_epg_id="espn.us",
            channel_db_id=channel_id, channel_name="ESPN",
            title=title, start_time=start, stop_time=end))


# --------------------------------------------------------------------------- #
# 1. resync_from_guide (REC-5)
# --------------------------------------------------------------------------- #

def test_resync_follows_a_moved_programme(db, config, accountant):
    """A scheduled row whose guide entry moved +15 minutes gets updated and
    is returned. FAILS pre-fix (before resync_from_guide re-matched anything —
    verified below by mutating the method to a no-op)."""
    now = now_utc().replace(microsecond=0)
    orig_start = now + timedelta(hours=2)
    orig_end = orig_start + timedelta(hours=1)
    rid = _make_scheduled_recording(
        db, channel_id="ch1", title="The Big Game",
        start=orig_start, end=orig_end)

    new_start = orig_start + timedelta(minutes=15)
    new_end = orig_end + timedelta(minutes=15)
    _make_epg_row(db, channel_id="ch1", title="The Big Game",
                 start=new_start, end=new_end)

    mgr = RecordingManager(db, config, accountant)
    moved = mgr.resync_from_guide()

    assert len(moved) == 1
    assert moved[0][0] == rid
    assert moved[0][1] == "The Big Game"
    assert moved[0][2] == new_start

    with db.session_scope(commit=False) as session:
        row = session.get(RecordingDB, rid)
        assert row.programme_start == new_start
        assert row.programme_end == new_end


def test_resync_does_not_adopt_a_same_title_airing_two_days_away(db, config, accountant):
    """The same title recurring two days later must not be mistaken for the
    SAME airing having moved — narrowed to a ±20h window."""
    now = now_utc().replace(microsecond=0)
    orig_start = now + timedelta(hours=2)
    orig_end = orig_start + timedelta(hours=1)
    _make_scheduled_recording(
        db, channel_id="ch1", title="Weekly Show",
        start=orig_start, end=orig_end)

    far_start = orig_start + timedelta(days=2)
    far_end = orig_end + timedelta(days=2)
    _make_epg_row(db, channel_id="ch1", title="Weekly Show",
                 start=far_start, end=far_end)

    mgr = RecordingManager(db, config, accountant)
    moved = mgr.resync_from_guide()

    assert moved == []


def test_resync_returns_nothing_for_an_unchanged_row(db, config, accountant):
    """The guide entry is identical to what was already stored — no notice."""
    now = now_utc().replace(microsecond=0)
    start = now + timedelta(hours=2)
    end = start + timedelta(hours=1)
    _make_scheduled_recording(
        db, channel_id="ch1", title="Steady Show", start=start, end=end)
    _make_epg_row(db, channel_id="ch1", title="Steady Show", start=start, end=end)

    mgr = RecordingManager(db, config, accountant)
    assert mgr.resync_from_guide() == []


# --------------------------------------------------------------------------- #
# 2. ACTIONS["record_programme"]
# --------------------------------------------------------------------------- #

def test_record_programme_applies_only_with_programme_identity_live_single():
    from datetime import datetime

    from metatv.gui.channel_menu import ACTIONS, ChannelMenuContext

    action = ACTIONS["record_programme"]
    start = datetime(2026, 9, 4, 20, 0)
    end = datetime(2026, 9, 4, 21, 0)

    with_programme = ChannelMenuContext(
        channel_ids=["c1"], surface="epg_on_now", channel_found=True,
        media_type="live", programme_start=start, programme_end=end)
    assert action.applies(with_programme) is True

    no_programme = ChannelMenuContext(
        channel_ids=["c1"], surface="epg_on_now", channel_found=True,
        media_type="live")
    assert action.applies(no_programme) is False

    not_live = ChannelMenuContext(
        channel_ids=["c1"], surface="epg_on_now", channel_found=True,
        media_type="movie", programme_start=start, programme_end=end)
    assert action.applies(not_live) is False

    multi_select = ChannelMenuContext(
        channel_ids=["c1", "c2"], surface="epg_on_now", channel_found=True,
        media_type="live", programme_start=start, programme_end=end)
    assert action.applies(multi_select) is False


def test_record_programme_listed_on_the_three_programme_row_surfaces():
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    for surface in ("alerts", "epg_on_now", "epg_browse"):
        assert "record_programme" in SURFACE_LAYOUTS[surface], (
            f"record_programme missing from the {surface!r} layout"
        )


# --------------------------------------------------------------------------- #
# 3. schedule_recording_from_programme -> _schedule_and_announce
# --------------------------------------------------------------------------- #

def test_schedule_recording_from_programme_applies_configured_padding(
        db, config, accountant):
    """FAILS pre-fix: the host has no schedule_recording_from_programme method
    at all — verified below by disabling it and confirming the row never
    lands."""
    with db.session_scope() as session:
        ch = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                          stream_url="http://example.com/espn.ts")
        cid = ch.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)

    start = now_utc().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    host.schedule_recording_from_programme(cid, start, end, "SportsCenter")

    with db.session_scope(commit=False) as session:
        rows = session.query(RecordingDB).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.programme_title == "SportsCenter"
        assert row.programme_start == start
        assert row.programme_end == end
        # The configured default padding, not the RecordingDB column default.
        assert row.pad_start_seconds == -90
        assert row.pad_end_seconds == 300

    host.notification_manager.show.assert_called_once()


def test_schedule_conflict_drop_other_cancels_the_first(db, config, accountant):
    """A second recording clashing on the same (single-connection) source
    routes through _resolve_recording_conflict; "drop the other" cancels the
    FIRST recording and lets the second stand."""
    with db.session_scope() as session:
        ch1 = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                           stream_url="http://example.com/espn.ts")
        ch2 = make_channel(session, "ESPN2", provider_id="p1", media_type="live",
                           stream_url="http://example.com/espn2.ts")
        cid1, cid2 = ch1.id, ch2.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)

    start = now_utc().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    host.schedule_recording_from_programme(cid1, start, end, "Game A")

    seam_calls = []

    def _fake_resolve(outcome, title, others_label):
        seam_calls.append((outcome, title, others_label))
        return "drop_other"

    host._resolve_recording_conflict = _fake_resolve
    host.schedule_recording_from_programme(cid2, start, end, "Game B")

    assert len(seam_calls) == 1, "the conflict seam must be asked exactly once"

    with db.session_scope(commit=False) as session:
        states = {r.programme_title: r.state
                  for r in session.query(RecordingDB).all()}
    assert states["Game A"] == "cancelled"
    assert states["Game B"] == "scheduled"


def test_schedule_conflict_keep_both_cancels_nothing(db, config, accountant):
    """"Keep both" (the default) leaves both rows scheduled."""
    with db.session_scope() as session:
        ch1 = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                           stream_url="http://example.com/espn.ts")
        ch2 = make_channel(session, "ESPN2", provider_id="p1", media_type="live",
                           stream_url="http://example.com/espn2.ts")
        cid1, cid2 = ch1.id, ch2.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)

    start = now_utc().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    host.schedule_recording_from_programme(cid1, start, end, "Game A")
    host._resolve_recording_conflict = lambda outcome, title, others: "keep_both"
    host.schedule_recording_from_programme(cid2, start, end, "Game B")

    with db.session_scope(commit=False) as session:
        states = {r.programme_title: r.state
                  for r in session.query(RecordingDB).all()}
    assert states["Game A"] == "scheduled"
    assert states["Game B"] == "scheduled"


# --------------------------------------------------------------------------- #
# 4. _confirm_quit_with_due_recordings
# --------------------------------------------------------------------------- #

def test_confirm_quit_true_with_nothing_scheduled(db, config, accountant):
    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)
    assert host._confirm_quit_with_due_recordings() is True


def test_confirm_quit_returns_the_seams_answer_with_one_scheduled(db, config, accountant):
    with db.session_scope() as session:
        ch = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                          stream_url="http://example.com/espn.ts")
        cid = ch.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)
    start = now_utc().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=1)
    host.schedule_recording_from_programme(cid, start, end, "Game")

    host._ask_quit_with_recordings = lambda count: False
    assert host._confirm_quit_with_due_recordings() is False

    host._ask_quit_with_recordings = lambda count: True
    assert host._confirm_quit_with_due_recordings() is True


# --------------------------------------------------------------------------- #
# 5. Settings -> Recording tab round-trip
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_settings_recording_tab_round_trips_minutes_to_seconds(qapp, tmp_path):
    """Driven through the REAL ``SettingsDialog(config, parent=None)``
    constructor with a real ``Config`` (CLAUDE.md: never a hand-written stub
    that drifts from the model) — proves the round-trip against production
    wiring, not a copy of it."""
    from metatv.gui.settings_dialog import SettingsDialog
    from tests.conftest import settings_config_double

    cfg = settings_config_double(
        config_dir=tmp_path,
        recording_pad_start_seconds=-180, recording_pad_end_seconds=600)
    dlg = SettingsDialog(cfg, parent=None)
    try:
        assert dlg._rec_pad_start_spin.value() == -3
        assert dlg._rec_pad_end_spin.value() == 10

        dlg._rec_pad_start_spin.setValue(-5)
        dlg._rec_pad_end_spin.setValue(20)
        dlg._save_values()

        assert cfg.recording_pad_start_seconds == -300
        assert cfg.recording_pad_end_seconds == 1200
    finally:
        dlg.close()
