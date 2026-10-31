"""Play outcomes recorded per source (Source Analytics Q6, Q8).

Drives the REAL start-watch functions (arm / on_loaded_tick / on_idle_tick /
on_player_gone) on the same duck-typed host the never-started tests use, with
a ``_run_query`` that runs synchronously against a file-backed Database, and
asserts the rows that land: started with time to picture and seconds watched,
dropped mid-play, refused at the connection limit, and a frozen play that then
advanced becoming one ``started`` row rather than two. Then the repository's
summary, the 90-day fold into weekly counts, and a source delete taking its
history with it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.core.players.mpv_log_tap import STREAM_EXIT_REASONS
from metatv.core.playback_models import PlaybackEventDB, PlaybackWeeklyDB
from metatv.core.repositories import RepositoryFactory
from metatv.gui import playback_start_watch as watch
from metatv.gui.playback_start_watch import FAILED_AFTER_TICKS, STALLED_AFTER_TICKS, PlayAttempt

ATTEMPT = PlayAttempt("ch1", "Some Film", "http://x/1.ts", provider_id="trex")


@pytest.fixture()
def file_db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


def _host(db):
    from tests.conftest import wire_status_method

    def run_query(fn, on_result, *, commit=False, on_error=None, token_ref=None):
        with db.session_scope() as session:
            result = fn(RepositoryFactory(session))
        on_result(result)

    host = SimpleNamespace(status_bar=MagicMock(), notification_manager=MagicMock(),
                           stream_retry_manager=MagicMock(),
                           _provider_display_name=MagicMock(return_value="TREX"),
                           _run_query=run_query)
    wire_status_method(host)
    return host


def _rows(db):
    with db.session_scope(commit=False) as s:
        return [(r.outcome, r.http_code, r.time_to_picture_ms, r.seconds_watched, r.provider_id)
                for r in s.query(PlaybackEventDB).order_by(PlaybackEventDB.id)]


def test_a_play_that_advances_is_recorded_started_then_gets_its_watched_time(file_db):
    host = _host(file_db)
    watch.arm(host, ATTEMPT)
    watch.on_loaded_tick(host, 0.0, False, cache_duration=2.0)
    watch.on_loaded_tick(host, 2.0, False, cache_duration=2.0)     # progress
    watch.on_loaded_tick(host, 62.0, False, cache_duration=2.0)
    watch.on_idle_tick(host)                                         # closed
    [(outcome, code, ttp, watched, pid)] = _rows(file_db)
    assert (outcome, code, watched, pid) == ("started", None, 62, "trex")
    assert ttp is not None and ttp >= 0


def test_a_play_cut_mid_film_is_recorded_dropped(file_db):
    host = _host(file_db)
    watch.arm(host, ATTEMPT)
    watch.on_loaded_tick(host, 0.0, False, cache_duration=2.0, duration=5000.0)
    watch.on_loaded_tick(host, 2.0, False, cache_duration=2.0, duration=5000.0)
    watch.on_loaded_tick(host, 200.0, False, cache_duration=2.0, duration=5000.0)
    watch.on_player_gone(host, exit_reason=next(iter(STREAM_EXIT_REASONS)))
    [(outcome, _code, _ttp, watched, _pid)] = _rows(file_db)
    assert (outcome, watched) == ("dropped", 200)


def test_a_connection_limit_refusal_is_recorded_refused_with_its_code(file_db):
    host = _host(file_db)
    with patch("metatv.gui.playback_start_watch._http_refusal", return_value=458):
        watch.arm(host, ATTEMPT)
        for _ in range(FAILED_AFTER_TICKS):
            watch.on_idle_tick(host)
    assert [(r[0], r[1]) for r in _rows(file_db)] == [("refused", 458)]


def test_a_frozen_play_that_then_advances_is_one_started_row(file_db):
    host = _host(file_db)
    with patch("metatv.gui.playback_start_watch._http_refusal", return_value=None):
        watch.arm(host, ATTEMPT)
        for _ in range(STALLED_AFTER_TICKS):
            watch.on_loaded_tick(host, 5.0, False, cache_duration=2.0)
        assert [r[0] for r in _rows(file_db)] == ["never_started"]
        watch.on_loaded_tick(host, 7.0, False, cache_duration=2.0)
    rows = _rows(file_db)
    assert [r[0] for r in rows] == ["started"] and rows[0][2] is not None


def test_a_play_with_no_source_is_not_recorded(file_db):
    host = _host(file_db)
    watch.arm(host, PlayAttempt("ep1", "Episode", "http://x/2.ts"))
    watch.on_loaded_tick(host, 0.0, False, cache_duration=2.0)
    watch.on_loaded_tick(host, 2.0, False, cache_duration=2.0)
    assert _rows(file_db) == []


def test_summary_counts_and_median_time_to_picture(file_db):
    now = datetime(2026, 10, 31, 12, 0)
    with file_db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        for outcome, ttp in [("started", 1000), ("started", 3000), ("dropped", 2000),
                             ("never_started", None), ("refused", None)]:
            repo.record(provider_id="trex", channel_id="c", title="t", outcome=outcome,
                        started_at=now, time_to_picture_ms=ttp)
        repo.record(provider_id="other", channel_id="c", title="t", outcome="started", started_at=now)
    with file_db.session_scope(commit=False) as s:
        summary = RepositoryFactory(s).playback_events.summary("trex")
    assert (summary.started, summary.never_started, summary.refused, summary.dropped) == (3, 1, 1, 1)
    assert summary.attempts == 5 and summary.median_time_to_picture_ms == 2000
    assert summary.since == now


def test_rows_past_ninety_days_fold_into_weekly_counts(file_db):
    now = datetime(2026, 10, 31, 12, 0)
    old = datetime(2026, 7, 1, 20, 0)       # a Wednesday, 122 days back
    with file_db.session_scope() as s:
        repo = RepositoryFactory(s).playback_events
        for outcome in ("started", "started", "refused"):
            repo.record(provider_id="trex", channel_id="c", title="t", outcome=outcome, started_at=old)
        repo.record(provider_id="trex", channel_id="c", title="t", outcome="started", started_at=now)
    with file_db.session_scope() as s:
        assert RepositoryFactory(s).playback_events.fold_old(now) == 3
    with file_db.session_scope(commit=False) as s:
        weekly = {(w.week_start.isoformat(), w.outcome): w.count for w in s.query(PlaybackWeeklyDB)}
        assert weekly == {("2026-06-29", "started"): 2, ("2026-06-29", "refused"): 1}
        assert s.query(PlaybackEventDB).count() == 1
        assert not RepositoryFactory(s).playback_events.has_old(now)


def test_deleting_a_source_takes_its_play_history(file_db):
    from metatv.core.database import ProviderDB
    with file_db.session_scope() as s:
        s.add(ProviderDB(id="trex", name="TREX", type="xtream", url="http://t", username="u", password="p"))
        RepositoryFactory(s).playback_events.record(
            provider_id="trex", channel_id="c", title="t", outcome="started", started_at=datetime.utcnow())
    with file_db.session_scope() as s:
        assert RepositoryFactory(s).providers.delete("trex")
    assert _rows(file_db) == []


def test_the_fold_task_is_registered_and_idempotent(file_db):
    from metatv.core.migrations.playback_events_fold import PlaybackEventsFoldTask
    from metatv.core.migrations.registry import TASKS
    assert ("playback_events_fold", "PlaybackEventsFoldTask", "") in TASKS
    task = PlaybackEventsFoldTask(file_db)
    assert task.needs_run(None) is False
    with file_db.session_scope() as s:
        RepositoryFactory(s).playback_events.record(
            provider_id="trex", channel_id="c", title="t", outcome="started",
            started_at=datetime.utcnow() - timedelta(days=120))
    assert task.needs_run(None) is True
    task.run(lambda *_: None, lambda: False)
    assert task.needs_run(None) is False
