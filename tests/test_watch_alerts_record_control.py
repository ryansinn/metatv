"""Watch Alerts' Record control (REC-2, Catch Keep Record Feature 3).

Every EPG programme row in the section — a single-source "direct" row, a
bundled group's parent row, and one of its children — carries a Record
control wired to ``WatchAlertsSection.programmeRecordRequested``. This pins
the WIRING (the row's own click mechanics are covered by
``test_alert_row_left_slot.py``): each shape of row must emit the signal with
its OWN channel id and guide window, never the wrong one borrowed from a
sibling.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

from PyQt6.QtCore import Qt

from metatv.core.config import Config
from metatv.gui.sidebar.alerts_common import _Airing
from metatv.gui.sidebar.alerts_rows import _AlertRow

NOW = datetime(2026, 8, 26, 20, 0, 0)


def _section(qtbot, tmp_path):
    from metatv.gui.sidebar.alerts import WatchAlertsSection

    sec = WatchAlertsSection(Config(config_dir=tmp_path), MagicMock())
    qtbot.addWidget(sec)
    sec.resize(330, 460)
    sec.show()
    qtbot.waitExposed(sec)
    return sec


def _settle(qtbot):
    for _ in range(8):
        qtbot.wait(1)


def _rows(sec) -> dict:
    """channel_db_id -> _AlertRow, for every row wired via _wire_row/_add_parent."""
    out = {}
    for item, row in sec._iter_rows():
        cid = item.data(0, Qt.ItemDataRole.UserRole)
        if cid:
            out[cid] = row
    return out


def _find_parent_row(sec) -> _AlertRow:
    """The bundled group's PARENT row — the top-level item WITH children.

    Never a hardcoded ``topLevelItem(0)``: an all-upcoming payload puts the
    foldable "Upcoming" heading at index 0, pushing the group's own parent row
    to index 1.
    """
    tree = sec.alerts_tree
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item.childCount() > 0:
            widget = tree.itemWidget(item, 0)
            if isinstance(widget, _AlertRow):
                return widget
    raise AssertionError("no parent row with children found")


def test_single_source_direct_row_records_its_own_window(qtbot, tmp_path):
    """A single-airing group goes through _add_direct — one row, one window."""
    sec = _section(qtbot, tmp_path)
    prog_start = NOW - timedelta(minutes=10)
    prog_stop = NOW + timedelta(minutes=50)
    payload = {
        "empty_reason": "",
        "live_groups": {
            "k1": {"title": "The Match", "upcoming": [], "live": [_Airing(
                3, "3m left", "ESPN", "c1", NOW + timedelta(minutes=20),
                NOW - timedelta(minutes=10), "", "",
                prog_start, prog_stop,
            )]},
        },
        "upcoming_only": {},
    }
    sec._populate_rows(payload)
    _settle(qtbot)

    captured = []
    sec.programmeRecordRequested.connect(lambda *a: captured.append(a))

    row = _rows(sec)["c1"]
    assert isinstance(row, _AlertRow)
    row.record_clicked.emit()

    assert captured == [("c1", prog_start, prog_stop, "The Match")]


def test_bundled_group_parent_records_the_lead_airing(qtbot, tmp_path):
    """A multi-airing group's PARENT row (_add_parent) records the lead —
    the same one its own play button starts."""
    sec = _section(qtbot, tmp_path)
    lead_start = NOW - timedelta(minutes=5)
    lead_stop = NOW + timedelta(minutes=55)
    other_start = NOW - timedelta(minutes=8)
    other_stop = NOW + timedelta(minutes=52)
    payload = {
        "empty_reason": "",
        "live_groups": {
            "k1": {"title": "The Match", "upcoming": [], "live": [
                _Airing(1, "5m left", "ESPN", "lead", NOW + timedelta(minutes=5),
                        lead_start, "", "", lead_start, lead_stop),
                _Airing(2, "8m left", "FOX", "other", NOW + timedelta(minutes=8),
                        other_start, "", "", other_start, other_stop),
            ]},
        },
        "upcoming_only": {},
    }
    sec._populate_rows(payload)
    _settle(qtbot)

    captured = []
    sec.programmeRecordRequested.connect(lambda *a: captured.append(a))

    _find_parent_row(sec).record_clicked.emit()

    assert captured == [("lead", lead_start, lead_stop, "The Match")]


def test_bundled_group_child_records_its_own_airing_not_the_leads(qtbot, tmp_path):
    """A CHILD row (_add_child) must record ITS OWN window — proof it is not
    silently sharing the parent's."""
    sec = _section(qtbot, tmp_path)
    lead_start = NOW - timedelta(minutes=5)
    lead_stop = NOW + timedelta(minutes=55)
    other_start = NOW - timedelta(minutes=8)
    other_stop = NOW + timedelta(minutes=52)
    payload = {
        "empty_reason": "",
        "live_groups": {
            "k1": {"title": "The Match", "upcoming": [], "live": [
                _Airing(1, "5m left", "ESPN", "lead", NOW + timedelta(minutes=5),
                        lead_start, "", "", lead_start, lead_stop),
                _Airing(2, "8m left", "FOX", "other", NOW + timedelta(minutes=8),
                        other_start, "", "", other_start, other_stop),
            ]},
        },
        "upcoming_only": {},
    }
    sec._populate_rows(payload)
    _settle(qtbot)

    captured = []
    sec.programmeRecordRequested.connect(lambda *a: captured.append(a))

    other_row = _rows(sec)["other"]
    other_row.record_clicked.emit()

    assert captured == [("other", other_start, other_stop, "The Match")]


def test_upcoming_only_bundled_parent_records_without_a_play_button(qtbot, tmp_path):
    """An all-upcoming group's parent has no first_source (never live), but
    still has a channel to RECORD — channel_db_id, separate from play."""
    sec = _section(qtbot, tmp_path)
    lead_start = NOW + timedelta(hours=1)
    lead_stop = NOW + timedelta(hours=2)
    other_start = NOW + timedelta(hours=1, minutes=30)
    other_stop = NOW + timedelta(hours=2, minutes=30)
    payload = {
        "empty_reason": "",
        "live_groups": {},
        "upcoming_only": {
            "u1": {"title": "Later Show", "airings": [
                _Airing(1, "9:00 PM", "ESPN", "lead", lead_start,
                        None, "", "", lead_start, lead_stop),
                _Airing(2, "9:30 PM", "FOX", "other", other_start,
                        None, "", "", other_start, other_stop),
            ]},
        },
    }
    sec._populate_rows(payload)
    _settle(qtbot)

    captured = []
    sec.programmeRecordRequested.connect(lambda *a: captured.append(a))

    _find_parent_row(sec).record_clicked.emit()

    assert captured == [("lead", lead_start, lead_stop, "Later Show")]


def test_refresh_recording_indicators_updates_the_matching_rows_state(qtbot, tmp_path):
    """The poll-tick push (MainWindow._refresh_transfer_sections) must reach
    the row that actually overlaps — and leave an unrelated row alone."""
    from metatv.core.recording_manager import RecordingProgress

    sec = _section(qtbot, tmp_path)
    prog_start = NOW - timedelta(minutes=10)
    prog_stop = NOW + timedelta(minutes=50)
    payload = {
        "empty_reason": "",
        "live_groups": {
            "k1": {"title": "The Match", "upcoming": [], "live": [_Airing(
                3, "3m left", "ESPN", "c1", NOW + timedelta(minutes=20),
                NOW - timedelta(minutes=10), "", "", prog_start, prog_stop,
            )]},
            "k2": {"title": "Other Show", "upcoming": [], "live": [_Airing(
                4, "3m left", "FOX", "c2", NOW + timedelta(minutes=20),
                NOW - timedelta(minutes=10), "", "",
                NOW - timedelta(minutes=5), NOW + timedelta(minutes=55),
            )]},
        },
        "upcoming_only": {},
    }
    sec._populate_rows(payload)
    _settle(qtbot)

    rows = _rows(sec)
    sec.refresh_recording_indicators([RecordingProgress(
        recording_id="r1", channel_id="c1", channel_name="ESPN",
        programme_title="The Match", state="recording",
        starts_at=prog_start, ends_at=prog_stop, recorded_bytes=0,
        dest_path="", error=None, waiting_for_slot=False,
    )])

    assert rows["c1"]._record_state == "recording"
    assert rows["c2"]._record_state is None, "an unrelated row must not light up"
