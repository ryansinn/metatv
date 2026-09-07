"""The Recordings sidebar row context menu — Watch / Stop recording / Extend.

Audit slice 1 (2026-09-07, two independent audits): ``recordings_list`` set
``Qt.ContextMenuPolicy.CustomContextMenu`` but nothing ever connected
``customContextMenuRequested``, so a recording's Watch/Stop/Extend — the
handlers were already complete and idle (``_watch_recording``/
``_cancel_recording``/``_extend_recording``, ``main_window_downloads.py``) —
were unreachable from the sidebar. This proves the menu that finally reaches
them, mirroring ``show_downloads_context_menu``'s shape and this suite's own
``QMenu.exec`` stub-and-capture convention
(``tests/test_context_menu_coverage.py``).

FAILS against the pre-fix tree: ``show_recordings_context_menu`` did not
exist, so every test here raised ``AttributeError`` before this slice.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from PyQt6.QtWidgets import QApplication, QMenu

from metatv.core.config import Config
from metatv.core.connection_accountant import ConnectionAccountant
from metatv.core.database import Database, ProviderDB, RecordingDB
from metatv.core.recording_manager import RecordingManager, RecordingProgress
from metatv.gui.sidebar.recordings import RecordingsSection
from tests.conftest import make_downloads_mixin_widget_host

NOW = datetime(2026, 9, 7, 19, 0, 0)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def config(tmp_path):
    return Config(config_dir=tmp_path / "config")


@pytest.fixture()
def db(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'rec.db'}")
    database.create_tables()
    with database.session_scope() as session:
        session.add(ProviderDB(id="p1", name="Shark", type="xtream", url="http://x"))
    return database


@pytest.fixture()
def section(qapp, qtbot, config):
    sec = RecordingsSection(config, db=None)
    qtbot.addWidget(sec)
    sec.resize(320, 240)
    sec.show()
    QApplication.processEvents()
    return sec


@pytest.fixture()
def host(db, config, section, qtbot):
    accountant = ConnectionAccountant(capacity_resolver=lambda _pid: 1)
    manager = RecordingManager(db, config, accountant)
    # A real QWidget, not a SimpleNamespace: show_recordings_context_menu does
    # QMenu(self), and QMenu's parent must be a QWidget|None.
    h = make_downloads_mixin_widget_host(db, config, recording_manager=manager)
    qtbot.addWidget(h)
    h.sidebar_sections = {"recordings": section}
    return h


def _seed_recording_row(db, *, state: str, dest_path: str = "") -> str:
    """A RecordingDB row inserted directly — full control over *state*,
    unlike ``RecordingManager.schedule()`` which always starts "scheduled"."""
    rid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(RecordingDB(
            id=rid, channel_id="c1", provider_id="p1", channel_name="BBC One",
            programme_title="The Match", source_url="http://x/live.ts",
            dest_path=dest_path, state=state,
            programme_start=NOW - timedelta(hours=1),
            programme_end=NOW + timedelta(hours=1),
            pad_start_seconds=0, pad_end_seconds=0, extend_seconds=0,
        ))
    return rid


def _progress_row(recording_id: str, *, state: str, dest_path: str = "") -> RecordingProgress:
    return RecordingProgress(
        recording_id=recording_id, channel_id="c1", channel_name="BBC One",
        programme_title="The Match", state=state,
        starts_at=NOW - timedelta(hours=1), ends_at=NOW + timedelta(hours=1),
        recorded_bytes=1000, dest_path=dest_path, error=None,
        waiting_for_slot=False, provider_id="p1",
    )


def _open_menu(host, section, row: RecordingProgress) -> "QMenu | None":
    """Render *row* as the section's only row, right-click its centre, and
    capture the QMenu ``show_recordings_context_menu`` built — ``QMenu.exec``
    is stubbed so nothing actually blocks on a modal loop."""
    section.refresh_progress([row])
    QApplication.processEvents()
    item = section.recordings_list.item(0)
    assert item is not None, "the row did not render"
    rect = section.recordings_list.visualItemRect(item)
    assert rect.height() > 0, "the row has no geometry — widget not shown/laid out"

    captured: dict = {}

    def _fake_exec(self, *_args, **_kwargs):
        captured["menu"] = self
        return None

    with patch.object(QMenu, "exec", _fake_exec):
        host.show_recordings_context_menu(rect.center())
    return captured.get("menu")


def _labels(menu) -> list[str]:
    return [] if menu is None else [
        a.text() for a in menu.actions() if not a.isSeparator()]


def _action(menu, label: str):
    for act in menu.actions():
        if act.text() == label:
            return act
    raise AssertionError(f"no {label!r} action in {_labels(menu)}")


# ── which actions appear, by state ──────────────────────────────────────────

def test_an_in_progress_recording_offers_watch_stop_and_extend(host, section, db):
    rid = _seed_recording_row(db, state="recording")
    menu = _open_menu(host, section, _progress_row(rid, state="recording"))
    assert _labels(menu) == ["Watch", "Stop recording", "Extend +15 min"], (
        "N in the Extend label comes from config.recording_extend_minutes "
        "(default 15, since the test Config declares no override)")


def test_a_finished_recording_with_a_file_offers_only_watch(host, section, db, tmp_path):
    finished = tmp_path / "match.ts"
    finished.write_bytes(b"x")
    rid = _seed_recording_row(db, state="completed", dest_path=str(finished))
    menu = _open_menu(
        host, section, _progress_row(rid, state="completed", dest_path=str(finished)))
    assert _labels(menu) == ["Watch"], (
        "a finished file can be watched, but there is nothing left to stop "
        "or extend")


def test_a_finished_recording_with_no_file_offers_nothing(host, section, db):
    """DL-2's rule applies here too: "downloaded" (or watchable) must come
    from the disk, never the stored state column."""
    rid = _seed_recording_row(db, state="completed", dest_path="/gone/match.ts")
    menu = _open_menu(
        host, section, _progress_row(rid, state="completed", dest_path="/gone/match.ts"))
    assert _labels(menu) == []


def test_a_scheduled_not_yet_started_recording_offers_nothing(host, section, db):
    """Nothing to watch, stop or extend before it has even started."""
    rid = _seed_recording_row(db, state="scheduled")
    menu = _open_menu(host, section, _progress_row(rid, state="scheduled"))
    assert _labels(menu) == []


def test_right_clicking_empty_space_shows_no_menu(host, section, db):
    rid = _seed_recording_row(db, state="recording")
    section.refresh_progress([_progress_row(rid, state="recording")])
    QApplication.processEvents()
    captured: dict = {}

    def _fake_exec(self, *_a, **_kw):
        captured["menu"] = self
        return None

    from PyQt6.QtCore import QPoint
    with patch.object(QMenu, "exec", _fake_exec):
        host.show_recordings_context_menu(QPoint(-5, -5))
    assert "menu" not in captured, "no row under the cursor — no menu at all"


# ── every action calls the real host slot with the right argument ──────────

def test_extend_calls_recording_manager_extend_with_the_configured_minutes(
        host, section, db):
    rid = _seed_recording_row(db, state="recording")
    menu = _open_menu(host, section, _progress_row(rid, state="recording"))

    spy = MagicMock(wraps=host.recording_manager.extend)
    host.recording_manager.extend = spy
    _action(menu, "Extend +15 min").trigger()

    spy.assert_called_once_with(rid, 15 * 60)
    with db.session_scope() as s:
        row = s.get(RecordingDB, rid)
        assert row.extend_seconds == 15 * 60, "the end time actually moved"


def test_stop_recording_calls_the_cancel_slot(host, section, db):
    rid = _seed_recording_row(db, state="recording")
    menu = _open_menu(host, section, _progress_row(rid, state="recording"))

    _action(menu, "Stop recording").trigger()

    with db.session_scope() as s:
        row = s.get(RecordingDB, rid)
        assert row.state == "cancelled"


def test_watch_calls_watch_recording_with_the_recording_id(host, section, db, tmp_path):
    finished = tmp_path / "match.ts"
    finished.write_bytes(b"x")
    rid = _seed_recording_row(db, state="completed", dest_path=str(finished))
    menu = _open_menu(
        host, section, _progress_row(rid, state="completed", dest_path=str(finished)))

    host._watch_recording = MagicMock()
    _action(menu, "Watch").trigger()
    host._watch_recording.assert_called_once_with(rid)


def test_every_action_carries_a_tooltip(host, section, db):
    rid = _seed_recording_row(db, state="recording")
    menu = _open_menu(host, section, _progress_row(rid, state="recording"))
    for act in menu.actions():
        assert act.toolTip(), f"{act.text()!r} has no tooltip"
