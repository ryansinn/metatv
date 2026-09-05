"""Record a channel for a time window — REC Option B (Catch, Keep, Record).

Needs no guide data at all, which is why it exists: a source with no EPG (the
owner's own live source among them) has nothing for "record what's on"
(``record_channel_by_id``) to read, so the user picks the start/end directly.

Covered behaviors
------------------
1. ``epg_utils.to_utc_naive``: converts a naive LOCAL datetime to UTC-naive
   independent of the machine's timezone (forced to America/Denver, the same
   precedent ``test_event_slot_times.py`` uses).
2. ``RecordWindowDialog``: default window is "now" (rounded up to the next 5
   minutes) -> +2h; end <= start disables OK; a window that has already
   ended also disables OK; a window already STARTED but not ended stays
   enabled with a note; padding spins are prefilled from the config
   defaults; the accepted window converts to UTC-naive for scheduling.
3. ``MainWindow.record_channel_window`` (via the skeleton
   ``make_downloads_mixin_host``): gated to live channels only; schedules
   through ``_schedule_and_announce`` with the DIALOG's own padding (not the
   config default); a cancelled dialog schedules nothing; a same-source
   clash still routes through ``_resolve_recording_conflict``.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

import pytest

from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, RecordingDB
from metatv.core.epg_utils import now_utc, to_local, to_utc_naive
from metatv.core.recording_manager import RecordingManager
from tests.conftest import make_channel, make_downloads_mixin_host


# --------------------------------------------------------------------------- #
# Shared fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture
def db(tmp_path):
    """A real Database on a real file — CLAUDE.md forbids :memory: for session work."""
    database = Database(f"sqlite:///{tmp_path / 'rec_window.db'}")
    database.create_tables()
    return database


@pytest.fixture
def config(tmp_path):
    class _Config:
        download_dir = str(tmp_path / "library")
        recording_pad_start_seconds = -180
        recording_pad_end_seconds = 600
    return _Config()


@pytest.fixture
def accountant():
    return ConnectionAccountant(capacity_resolver=lambda _pid: 1)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _with_denver_tz(fn):
    """Run *fn* with TZ=America/Denver, restoring the prior TZ after.

    Same forced-non-UTC-machine-TZ precedent as
    ``tests/test_event_slot_times.py::TestSlotTimesAreUtc``.
    """
    old_tz = os.environ.get("TZ")
    os.environ["TZ"] = "America/Denver"
    time.tzset()
    try:
        return fn()
    finally:
        if old_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = old_tz
        time.tzset()


# --------------------------------------------------------------------------- #
# 1. epg_utils.to_utc_naive
# --------------------------------------------------------------------------- #
# Both tests here force a non-UTC MACHINE timezone (time.tzset is POSIX-only),
# so only THIS class skips where it is unavailable — not the whole module,
# which has plenty of tests that need no timezone forcing at all.

class TestToUtcNaive:

    @pytest.fixture(autouse=True)
    def _require_tzset(self):
        if not hasattr(time, "tzset"):
            pytest.skip("time.tzset is POSIX-only; not available here")

    def test_converts_denver_local_to_utc(self):
        """September is MDT (UTC-6): 14:00 local -> 20:00 UTC.

        FAILS under a machine-local reading that ignores the forced zone
        (would return 2026-09-04 14:00 unchanged).
        """
        local_dt = datetime(2026, 9, 4, 14, 0)
        got = _with_denver_tz(lambda: to_utc_naive(local_dt))
        assert got == datetime(2026, 9, 4, 20, 0)

    def test_round_trips_through_to_local(self):
        """Inverse of to_local: local -> UTC -> local returns the original
        wall time."""
        local_dt = datetime(2026, 9, 4, 14, 30)

        def _roundtrip():
            utc = to_utc_naive(local_dt)
            return to_local(utc).replace(tzinfo=None)

        assert _with_denver_tz(_roundtrip) == local_dt


# --------------------------------------------------------------------------- #
# 2. RecordWindowDialog
# --------------------------------------------------------------------------- #

class TestRecordWindowDialog:

    def test_default_window_is_now_rounded_up_to_5min_plus_2h(self, qapp, config):
        from metatv.gui.record_window_dialog import RecordWindowDialog

        now = datetime(2026, 9, 4, 19, 3, 17)
        dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
        try:
            start = dlg._start_edit.dateTime().toPyDateTime()
            end = dlg._end_edit.dateTime().toPyDateTime()
            assert start == datetime(2026, 9, 4, 19, 5)
            assert end == start + timedelta(hours=2)
        finally:
            dlg.close()

    def test_default_window_on_an_exact_5_minute_mark_is_unchanged(self, qapp, config):
        from metatv.gui.record_window_dialog import RecordWindowDialog

        now = datetime(2026, 9, 4, 19, 5, 0)
        dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
        try:
            start = dlg._start_edit.dateTime().toPyDateTime()
            assert start == datetime(2026, 9, 4, 19, 5)
        finally:
            dlg.close()

    def test_end_at_or_before_start_disables_ok(self, qapp, config):
        from PyQt6.QtWidgets import QDialogButtonBox

        from metatv.gui.record_window_dialog import RecordWindowDialog

        now = datetime(2026, 9, 4, 19, 0)
        dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
        try:
            ok_btn = dlg._buttons.button(QDialogButtonBox.StandardButton.Ok)
            assert ok_btn.isEnabled(), "the default 2h window must start valid"

            dlg._end_edit.setDateTime(dlg._start_edit.dateTime())
            assert not ok_btn.isEnabled()
            assert "after the start" in dlg._status_lbl.text()
        finally:
            dlg.close()

    def test_a_window_that_already_ended_disables_ok(self, qapp, config):
        from PyQt6.QtCore import QDateTime
        from PyQt6.QtWidgets import QDialogButtonBox

        from metatv.gui.record_window_dialog import RecordWindowDialog

        now = datetime(2026, 9, 4, 19, 0)
        dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
        try:
            ok_btn = dlg._buttons.button(QDialogButtonBox.StandardButton.Ok)
            dlg._start_edit.setDateTime(QDateTime(now - timedelta(hours=3)))
            dlg._end_edit.setDateTime(QDateTime(now - timedelta(hours=1)))
            assert not ok_btn.isEnabled()
            assert "already ended" in dlg._status_lbl.text()
        finally:
            dlg.close()

    def test_a_window_already_started_but_not_ended_stays_enabled_with_a_note(
            self, qapp, config):
        from PyQt6.QtCore import QDateTime
        from PyQt6.QtWidgets import QDialogButtonBox

        from metatv.gui.record_window_dialog import RecordWindowDialog

        now = datetime(2026, 9, 4, 19, 0)
        dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
        try:
            ok_btn = dlg._buttons.button(QDialogButtonBox.StandardButton.Ok)
            dlg._start_edit.setDateTime(QDateTime(now - timedelta(minutes=30)))
            dlg._end_edit.setDateTime(QDateTime(now + timedelta(hours=1)))
            assert ok_btn.isEnabled(), (
                "a window that started but has not ended must still be recordable")
            assert "begins" in dlg._status_lbl.text().lower()
        finally:
            dlg.close()

    def test_padding_spins_prefilled_from_config_defaults(self, qapp, config):
        from metatv.gui.record_window_dialog import RecordWindowDialog

        dlg = RecordWindowDialog(
            "ESPN", "MySource", config, now=datetime(2026, 9, 4, 19, 0))
        try:
            # Same minutes-on-screen/seconds-in-config formula as SettingsDialog.
            assert dlg._pad_start_spin.value() == -3    # -180s / 60
            assert dlg._pad_end_spin.value() == 10       # 600s / 60
        finally:
            dlg.close()

    def test_result_window_converts_local_to_utc_naive_under_forced_tz(
            self, qapp, config):
        """FAILS if result_window() forgot the local->UTC conversion (or did
        it backwards): under Denver MDT the accepted 14:00 local window would
        come back unconverted (14:00) instead of 20:00 UTC.
        """
        if not hasattr(time, "tzset"):
            pytest.skip("time.tzset is POSIX-only; not available here")
        from metatv.gui.record_window_dialog import RecordWindowDialog

        def _build_and_read():
            now = datetime(2026, 9, 4, 14, 0)
            dlg = RecordWindowDialog("ESPN", "MySource", config, now=now)
            try:
                return dlg.result_window()
            finally:
                dlg.close()

        starts_at, ends_at, pad_start, pad_end = _with_denver_tz(_build_and_read)
        assert starts_at == datetime(2026, 9, 4, 20, 0)
        assert ends_at == datetime(2026, 9, 4, 22, 0)
        assert pad_start == -180
        assert pad_end == 600


# --------------------------------------------------------------------------- #
# 3. MainWindow.record_channel_window
# --------------------------------------------------------------------------- #

class _FakeRecordWindowDialog:
    """A drop-in double for RecordWindowDialog — no Qt event loop required.

    Patched onto ``metatv.gui.record_window_dialog.RecordWindowDialog`` (the
    DEFINING module, per CLAUDE.md's import-a-private-name rule) rather than
    onto ``main_window_downloads``, since the production code re-imports the
    name fresh on every call.
    """

    #: Set per-test via ``_FakeRecordWindowDialog.configure(...)``.
    _window = None
    _accept = True
    opened_with: list = []

    def __init__(self, channel_name, provider_name, config, parent=None, **kwargs):
        self.__class__.opened_with.append((channel_name, provider_name))

    def exec(self):
        from PyQt6.QtWidgets import QDialog
        return (QDialog.DialogCode.Accepted if self._accept
               else QDialog.DialogCode.Rejected)

    def result_window(self):
        assert self._accept, "result_window() must not be read after Reject"
        return self._window

    @classmethod
    def configure(cls, window=None, accept=True):
        cls._window = window
        cls._accept = accept
        cls.opened_with = []


@pytest.fixture
def fake_dialog(monkeypatch):
    _FakeRecordWindowDialog.configure()
    monkeypatch.setattr(
        "metatv.gui.record_window_dialog.RecordWindowDialog",
        _FakeRecordWindowDialog)
    return _FakeRecordWindowDialog


def test_record_channel_window_schedules_with_the_dialogs_own_padding(
        db, config, accountant, fake_dialog):
    """FAILS pre-fix: the host has no record_channel_window method at all."""
    with db.session_scope() as session:
        ch = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                          stream_url="http://example.com/espn.ts")
        cid = ch.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)

    start = now_utc().replace(microsecond=0) + timedelta(hours=1)
    end = start + timedelta(hours=2)
    # Deliberately NOT the config default (-180/600) — proves the dialog's own
    # padding is used, not the config's.
    fake_dialog.configure(window=(start, end, -60, 900))

    host.record_channel_window(cid)

    with db.session_scope(commit=False) as session:
        rows = session.query(RecordingDB).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.programme_start == start
        assert row.programme_end == end
        assert row.pad_start_seconds == -60
        assert row.pad_end_seconds == 900

    # No ProviderDB row exists for "p1" in this fixture, so the fallback name
    # ("This source") is what the dialog gets — proves the lookup happened
    # and did not blow up on a missing provider row.
    assert fake_dialog.opened_with == [("ESPN", "This source")]
    host.notification_manager.show.assert_called_once()


def test_record_channel_window_refuses_a_non_live_channel(
        db, config, accountant, fake_dialog):
    """Gated to live channels, same as record_channel_by_id — a VOD has
    download() instead. FAILS pre-fix if the media_type guard is dropped:
    the dialog would open for a movie."""
    with db.session_scope() as session:
        ch = make_channel(session, "A Movie", provider_id="p1", media_type="movie",
                          stream_url="http://example.com/movie.ts")
        cid = ch.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)
    fake_dialog.configure(window=(now_utc(), now_utc() + timedelta(hours=1), 0, 0))

    host.record_channel_window(cid)

    assert fake_dialog.opened_with == [], "the dialog must not open for a non-live channel"
    with db.session_scope(commit=False) as session:
        assert session.query(RecordingDB).count() == 0


def test_record_channel_window_cancelled_dialog_schedules_nothing(
        db, config, accountant, fake_dialog):
    with db.session_scope() as session:
        ch = make_channel(session, "ESPN", provider_id="p1", media_type="live",
                          stream_url="http://example.com/espn.ts")
        cid = ch.id

    mgr = RecordingManager(db, config, accountant)
    host = make_downloads_mixin_host(db, config, recording_manager=mgr)
    fake_dialog.configure(accept=False)

    host.record_channel_window(cid)

    with db.session_scope(commit=False) as session:
        assert session.query(RecordingDB).count() == 0


def test_record_channel_window_clash_routes_through_resolve_conflict(
        db, config, accountant, fake_dialog):
    """A second window recording clashing on the same (single-connection)
    source routes through _resolve_recording_conflict, same as REC-3's
    schedule_recording_from_programme."""
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

    fake_dialog.configure(window=(start, end, 0, 0))
    host.record_channel_window(cid1)

    seam_calls = []

    def _fake_resolve(outcome, title, others_label):
        seam_calls.append((outcome, title, others_label))
        return "drop_other"

    host._resolve_recording_conflict = _fake_resolve
    fake_dialog.configure(window=(start, end, 0, 0))
    host.record_channel_window(cid2)

    assert len(seam_calls) == 1, "the conflict seam must be asked exactly once"

    with db.session_scope(commit=False) as session:
        states = {r.channel_name: r.state for r in session.query(RecordingDB).all()}
    assert states["ESPN"] == "cancelled"
    assert states["ESPN2"] == "scheduled"
