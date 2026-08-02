"""Behavioral tests for the graduated play-failure ledger (roadmap S3, #227).

Covered behaviors:

1. Graduation thresholds: StreamRetryRepository.add() increments play_fail_count
   on every call and graduates reliability_state — 1st failure -> "flagged",
   3rd+ -> "degraded", 6th+ -> "dead".

2. Advisory HTTP codes (401/403/511) now enqueue into the ledger — the prior
   exclusion (main_window_streaming.py's advisory gate) is deliberately
   revisited so a stream that always fails pre-flight with an advisory code
   (e.g. a dead channel returning HTTP 511 forever) can still graduate.

3. A background-checker SUCCESS (StreamRetryRepository.mark_checked(ok=True))
   resets the ledger to play_fail_count=0 / reliability_state="ok", even from
   "dead".

4. "dead" channels are excluded from ChannelRepository.get_all() (the
   forward-looking list query, via the shared _apply_channel_filters
   chokepoint) while "degraded" channels remain visible.

5. The recheck_failed_on_refresh settings toggle gates whether a source
   refresh re-probes the retry ledger via stream_retry_manager.check_all_now().

6. The real Settings -> Playback -> Network checkbox loads/saves
   recheck_failed_on_refresh to/from config, same load/save pattern as its
   sibling network fields.

All DB tests use file-backed SQLite (tmp_path) per CLAUDE.md rule.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    return d


def _insert_provider(session, provider_id: str = "prov-1", name: str = "Prov") -> None:
    from metatv.core.database import ProviderDB
    session.add(ProviderDB(
        id=provider_id, name=name, type="xtream", url="http://example.com",
        is_active=True, urls=[],
    ))
    session.flush()


def _insert_channel(session, provider_id: str, name: str) -> str:
    from metatv.core.database import ChannelDB
    ch_id = str(uuid.uuid4())
    session.add(ChannelDB(
        id=ch_id,
        source_id=str(uuid.uuid4()),
        provider_id=provider_id,
        name=name,
        stream_url=f"http://example.com/{ch_id}.ts",
        media_type="live",
    ))
    session.flush()
    return ch_id


def _insert_retry_row(session, channel_id: str, reliability_state: str) -> None:
    from metatv.core.database import StreamRetryDB
    session.add(StreamRetryDB(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        channel_name="whatever",
        stream_url="http://example.com/x.ts",
        status="pending",
        reliability_state=reliability_state,
    ))
    session.flush()


# ---------------------------------------------------------------------------
# Part 1: graduation thresholds
# ---------------------------------------------------------------------------

def test_add_failure_graduates_reliability_state(tmp_path):
    """1st add() -> flagged, 3rd -> degraded, 6th -> dead; play_fail_count tracks calls."""
    from metatv.core.repositories.stream_retry import StreamRetryRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        channel_id = "ch-graduation"

        entry = repo.add(channel_id, "Some Channel", "http://x/1.ts", "HTTP 511")
        assert entry.play_fail_count == 1
        assert entry.reliability_state == "flagged"
        assert entry.last_play_error == "HTTP 511"

        entry = repo.add(channel_id, "Some Channel", "http://x/1.ts", "HTTP 511")
        assert entry.play_fail_count == 2
        assert entry.reliability_state == "flagged"

        entry = repo.add(channel_id, "Some Channel", "http://x/1.ts", "HTTP 511")
        assert entry.play_fail_count == 3
        assert entry.reliability_state == "degraded"

        for _ in range(2):  # play_fail_count -> 5
            entry = repo.add(channel_id, "Some Channel", "http://x/1.ts", "HTTP 511")
        assert entry.play_fail_count == 5
        assert entry.reliability_state == "degraded"

        entry = repo.add(channel_id, "Some Channel", "http://x/1.ts", "HTTP 511")
        assert entry.play_fail_count == 6
        assert entry.reliability_state == "dead"


# ---------------------------------------------------------------------------
# Part 2: advisory errors now enqueue
# ---------------------------------------------------------------------------

def _make_streaming_mixin():
    """Bare _StreamingMixin with just enough mocked state for _on_stream_ready."""
    from metatv.gui.main_window_streaming import _StreamingMixin
    obj = _StreamingMixin.__new__(_StreamingMixin)
    obj.loading_channels = set()
    obj.db = MagicMock()
    obj.executor = MagicMock()
    obj.player_manager = MagicMock()
    obj.notification_manager = MagicMock()
    obj.notification_manager.show.return_value = "notif-xyz"
    obj.status_bar = MagicMock()
    obj._stream_ready = MagicMock()
    obj._provider_icons = {}
    return obj


def test_advisory_511_now_enqueues_in_ledger():
    """A 511 (advisory) failure DOES call stream_retry_manager.add_failure.

    Pins the roadmap-S3 gate flip in main_window_streaming.py: previously
    advisory errors were skipped entirely, so a channel that always returns
    511 could never graduate to "dead".
    """
    obj = _make_streaming_mixin()
    retry_mgr = MagicMock()
    obj.stream_retry_manager = retry_mgr

    data = {
        "ok": False,
        "channel_id": "ch-advisory",
        "channel_name": "XMAS 24/7",
        "original_url": "http://example.com/xmas.ts",
        "final_url": "",
        "stream_err": "HTTP 511",
        "notif_id": "n1",
        "provider_id": "p1",
        "force_new_window": False,
        "start_seconds": 0,
        "open_ended_buffer": False,
        "advisory": True,
        "siblings": [],
    }
    obj._on_stream_ready(data)

    retry_mgr.add_failure.assert_called_once_with(
        "ch-advisory", "XMAS 24/7", "http://example.com/xmas.ts", "HTTP 511"
    )


# ---------------------------------------------------------------------------
# Part 3: checker success resets the ledger
# ---------------------------------------------------------------------------

def test_checker_success_resets_ledger_from_dead(tmp_path):
    """mark_checked(ok=True) resets play_fail_count/reliability_state even from 'dead'."""
    from metatv.core.repositories.stream_retry import StreamRetryRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        repo = StreamRetryRepository(session)
        channel_id = "ch-recover"
        entry = None
        for _ in range(6):
            entry = repo.add(channel_id, "Recoverable Channel", "http://x/2.ts", "HTTP 511")
        assert entry.reliability_state == "dead"
        assert entry.play_fail_count == 6

        repo.mark_checked(entry, ok=True, error=None)

        assert entry.status == "online"
        assert entry.play_fail_count == 0
        assert entry.reliability_state == "ok"
        assert entry.last_play_error is None


# ---------------------------------------------------------------------------
# Part 4: dead excluded from list query, degraded stays visible
# ---------------------------------------------------------------------------

def test_dead_excluded_from_get_all_degraded_stays_visible(tmp_path):
    from metatv.core.repositories.channel import ChannelRepository

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session)
        ok_id = _insert_channel(session, "prov-1", "OK Channel")
        degraded_id = _insert_channel(session, "prov-1", "Degraded Channel")
        dead_id = _insert_channel(session, "prov-1", "Dead Channel")

        _insert_retry_row(session, degraded_id, "degraded")
        _insert_retry_row(session, dead_id, "dead")

        results = ChannelRepository(session).get_all()
        result_ids = {c.id for c in results}

        assert ok_id in result_ids
        assert degraded_id in result_ids, "degraded channels must stay visible"
        assert dead_id not in result_ids, "dead channels must be excluded from the list query"


def test_dead_excluded_from_count_watched_matching(tmp_path):
    """The shared _apply_channel_filters chokepoint also gates count_watched_matching."""
    from metatv.core.repositories.channel import ChannelRepository
    from metatv.core.database import ChannelDB

    db = _make_db(tmp_path)
    with db.session_scope() as session:
        _insert_provider(session)
        dead_id = _insert_channel(session, "prov-1", "Dead Watched Channel")
        session.query(ChannelDB).filter_by(id=dead_id).update({"watch_completed": True})
        _insert_retry_row(session, dead_id, "dead")
        session.flush()

        count = ChannelRepository(session).count_watched_matching()
        assert count == 0, "a dead channel must not be counted even if watch_completed"


# ---------------------------------------------------------------------------
# Part 5: recheck_failed_on_refresh toggle gates check_all_now
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _make_provider_refresh_stub(recheck_failed_on_refresh: bool):
    """Minimal MainWindow-shaped stub for _on_queue_refresh_finished's success path.

    Every attribute the handler's success path touches must be set explicitly —
    on a __new__'d QMainWindow a *missing* attr raises RuntimeError from PyQt
    rather than AttributeError/False (see test_add_provider_epg.py's identical
    stub pattern).
    """
    from metatv.gui.main_window import MainWindow
    mw = MainWindow.__new__(MainWindow)
    mw.active_threads = []
    mw.refreshing_providers = set()
    mw.notification_manager = MagicMock()
    mw.epg_manager = MagicMock()
    mw._refresh_provider_dependent_views = MagicMock()
    mw.stream_retry_manager = MagicMock()
    mw.config = SimpleNamespace(recheck_failed_on_refresh=recheck_failed_on_refresh)
    mw._epg_fetch_after_add = set()
    mw._maybe_refresh_provider_epg = MagicMock()
    return mw


def test_recheck_failed_on_refresh_true_triggers_check_all_now(qapp):
    mw = _make_provider_refresh_stub(recheck_failed_on_refresh=True)
    mw._on_queue_refresh_finished("prov-1", True, "ok", None)
    mw.stream_retry_manager.check_all_now.assert_called_once()


def test_recheck_failed_on_refresh_false_skips_check_all_now(qapp):
    mw = _make_provider_refresh_stub(recheck_failed_on_refresh=False)
    mw._on_queue_refresh_finished("prov-1", True, "ok", None)
    mw.stream_retry_manager.check_all_now.assert_not_called()


# ---------------------------------------------------------------------------
# Part 6: real Settings -> Playback -> Network checkbox load/save round-trip
# ---------------------------------------------------------------------------

def test_settings_dialog_loads_recheck_failed_on_refresh(qapp):
    """The Network group checkbox reflects config.recheck_failed_on_refresh on load."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import SettingsDialog

    cfg = Config()
    cfg.recheck_failed_on_refresh = False
    dlg = SettingsDialog(cfg, parent=None)

    assert dlg._recheck_failed_on_refresh_check.isChecked() is False
    dlg.close()


def test_settings_dialog_saves_recheck_failed_on_refresh(qapp):
    """Toggling the checkbox and saving writes recheck_failed_on_refresh back to config."""
    from metatv.core.config import Config
    from metatv.gui.settings_dialog import SettingsDialog

    cfg = Config()
    cfg.recheck_failed_on_refresh = True
    dlg = SettingsDialog(cfg, parent=None)

    dlg._recheck_failed_on_refresh_check.setChecked(False)
    dlg._save_values()

    assert cfg.recheck_failed_on_refresh is False
    dlg.close()
