"""Playing an episode must survive a database that is busy.

The owner, mid-session, while a 293,468-item source refresh held the write
lock::

    sqlalchemy.exc.OperationalError: database is locked
      [SQL: UPDATE episodes SET last_played=?, play_count=? WHERE episodes.id = ?]
    fish: Job 1, './run.sh' terminated by signal SIGABRT (Abort)

``play_episode`` recorded the play inside ``try: ... finally: session.close()``
with **no ``except``**. PyQt calls ``qFatal()`` when an exception escapes a
slot, so a failed bookkeeping write did not degrade the feature — it killed the
process, mid-playback, with no traceback from Qt's side.

The channel path already behaved correctly: ``_bg_mark_played`` catches and
logs. The episode path was the one that never got the same treatment.

**Bookkeeping must not prevent playback.** Recording that a play happened, and
building the season queue, are both downstream of the user's actual intent.
Losing them is a degradation; losing the process is not.

The 30 s ``busy_timeout`` is not the fix and these tests do not assume one — a
bulk catalogue insert can hold the write lock longer than any timeout worth
setting, which is recorded separately as a contention problem. What is fixed
here is that it can no longer be *fatal*.

PLAY-13 (2026-09-08) moved WHERE this write happens: it used to run
synchronously inside ``play_episode()``, before the stream had even been
validated — the mirror-image of the channel path's HIST-1/PLAY-9 bug, over-
recording instead of under-recording. It now runs in ``_record_episode_play``,
called from ``_do_launch_episode`` only after preflight validated AND mpv
actually launched (``self.db.session_scope()``, not the old ``get_session()``+
``finally`` pattern). The try/except this file exists to prove survives that
move unchanged in spirit: these tests now drive ``_do_launch_episode`` with the
args ``play_episode`` would have handed a successful preflight, rather than
``play_episode`` itself, which no longer touches the database for the write.
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError
from tests.conftest import wire_status_method


@dataclass
class _Episode:
    id: str = "e1"
    episode_num: int = 3
    season_num: int = 1
    title: str = "Episode 3"
    series_name: str | None = "Test Show"
    stream_url: str | None = "http://example.com/e3.ts"
    duration: str | None = None
    is_watched: bool = False
    rating: str | None = None
    series_id: str = "ser1"
    provider_id: str = "prov1"
    season_id: str = "s1"
    watch_progress: int = 0
    watch_completed: bool = False
    watch_percent: int = 0
    last_played_via: str | None = None


def _locked() -> OperationalError:
    """The exact exception SQLite raises when the write lock is held."""
    return OperationalError(
        "UPDATE episodes SET last_played=?", {}, Exception("database is locked")
    )


def _host(failure: Exception | None = None):
    """A ``_SeriesPlaybackMixin`` whose bookkeeping raises *failure*, if given."""
    from metatv.gui.main_window_series_playback import _SeriesPlaybackMixin

    obj = object.__new__(_SeriesPlaybackMixin)

    cfg = MagicMock()
    cfg.autoplay_season_episodes = False
    obj.config = cfg

    repos = MagicMock()
    if failure is not None:
        repos.episodes.mark_played.side_effect = failure
    repos.channels.get_by_source_id.return_value = None
    repos.episodes.get_episodes_dto_by_season.return_value = []

    session = MagicMock()
    db = MagicMock()
    # __exit__ must return falsy so an exception raised inside the `with`
    # block (mark_played's side_effect) actually propagates out of
    # session_scope() into _record_episode_play's try/except, exactly as the
    # real generator-based context manager does — a bare MagicMock's
    # auto-mocked __exit__ returns a truthy Mock by default and would
    # silently SWALLOW the exception, proving nothing.
    db.session_scope.return_value.__enter__.return_value = session
    db.session_scope.return_value.__exit__.return_value = False
    obj.db = db

    obj.player_manager = MagicMock()
    obj.player_manager.resolve_key.return_value = "prov1"
    obj.status_bar = MagicMock()
    wire_status_method(obj)
    obj.notification_manager = MagicMock()
    obj.load_history = MagicMock()
    obj.load_favorites = MagicMock()
    obj._start_watch_capture = MagicMock()
    obj._start_playback_health = MagicMock()
    obj._play_checked = MagicMock(return_value=True)
    obj.launch_player_for_episode = MagicMock()
    obj.executor = MagicMock()
    return obj, repos, session


def _drive_do_launch_episode(obj):
    """Call _do_launch_episode with exactly the args play_episode passed to
    the (mocked) launch_player_for_episode — simulating a successful
    preflight, which is when PLAY-13 moved the write to actually happen.
    """
    args, kwargs = obj.launch_player_for_episode.call_args
    stream_url, title, episodes_to_queue = args
    obj._do_launch_episode(
        "notif_1", stream_url, title, episodes_to_queue,
        provider_id=kwargs["provider_id"],
        start_seconds=kwargs.get("start_seconds", 0),
        episode_id=kwargs["episode_id"],
        series_id=kwargs["series_id"],
    )


def test_a_locked_database_does_not_kill_the_app(monkeypatch):
    """THE assertion. Pre-fix this propagates and PyQt aborts the process."""
    obj, repos, _session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        obj.launch_player_for_episode.assert_called_once()
        _drive_do_launch_episode(obj)  # must not raise
        # PLAY-15: the write itself is now deferred to _pending_play_record —
        # invoke it here, where the failure actually happens.
        obj._pending_play_record()  # must not raise


def test_the_episode_still_plays_when_bookkeeping_fails(monkeypatch):
    """Degraded, not broken — the stream is what the user asked for."""
    obj, repos, _session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode(title="The Gang Gets Tested"))
        _drive_do_launch_episode(obj)

    assert obj.launch_player_for_episode.call_count == 1
    obj._play_checked.assert_called_once()


def test_the_context_manager_still_exits_when_bookkeeping_fails():
    """session_scope()'s __exit__ must run even though the write inside raised
    — that guarantee is the whole reason PLAY-13 moved this write onto
    session_scope() rather than the legacy get_session()+finally pattern.
    """
    obj, repos, _session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        _drive_do_launch_episode(obj)
        # PLAY-15: session_scope() isn't entered until the deferred write runs.
        obj._pending_play_record()

    obj.db.session_scope.return_value.__exit__.assert_called_once()


def test_the_failure_is_logged_not_swallowed():
    """A lock held this long is a real problem; it just must not be fatal."""
    from metatv.gui import main_window_series_playback

    obj, repos, _session = _host(failure=_locked())
    logged: list[str] = []
    monkey = MagicMock()
    monkey.exception.side_effect = lambda msg, *a: logged.append(str(msg))
    monkey.info.side_effect = lambda *a, **k: None
    monkey.warning.side_effect = lambda *a, **k: None
    monkey.debug.side_effect = lambda *a, **k: None

    with patch.object(main_window_series_playback, "logger", monkey), \
            patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        _drive_do_launch_episode(obj)
        # PLAY-15: the write — and its try/except — only run once deferred.
        obj._pending_play_record()

    assert logged, "the failure was swallowed with no record at all"


@pytest.mark.parametrize("failure", [
    _locked(),
    RuntimeError("something else entirely"),
    ValueError("a bad DTO"),
])
def test_any_bookkeeping_failure_is_survivable(failure):
    """Not just lock errors.

    The crash was structural — no ``except`` at all — so narrowing the guard to
    ``OperationalError`` would leave the same shape for the next exception that
    turns up there.
    """
    obj, repos, _session = _host(failure=failure)

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        _drive_do_launch_episode(obj)  # must not raise
        obj._pending_play_record()  # must not raise (PLAY-15: the deferred write)

    obj.launch_player_for_episode.assert_called_once()


def test_the_normal_path_is_unchanged():
    """The guard must not swallow a working play."""
    obj, repos, session = _host()

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        obj.launch_player_for_episode.assert_called_once()
        _drive_do_launch_episode(obj)
        obj._pending_play_record()  # PLAY-15: the write itself is deferred

    repos.episodes.mark_played.assert_called_once_with("e1")
    obj.db.session_scope.return_value.__exit__.assert_called_once()


def test_the_episode_write_waits_for_progress():
    """The owner's exact defect, at the episode layer: nothing is recorded
    just because mpv accepted the file — only once the deferred write runs."""
    obj, repos, _session = _host()

    with patch("metatv.gui.main_window_series_playback.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())
        _drive_do_launch_episode(obj)
        repos.episodes.mark_played.assert_not_called()
        obj._pending_play_record()

    repos.episodes.mark_played.assert_called_once_with("e1")
