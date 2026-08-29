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
"""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import OperationalError


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
    """A ``_SeriesMixin`` whose bookkeeping raises *failure*, if given."""
    from metatv.gui.main_window_series import _SeriesMixin

    obj = object.__new__(_SeriesMixin)

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
    db.get_session.return_value = session
    obj.db = db

    obj.player_manager = MagicMock()
    obj.player_manager.resolve_key.return_value = "prov1"
    obj.status_bar = MagicMock()
    obj.notification_manager = MagicMock()
    obj.load_history = MagicMock()
    obj.load_favorites = MagicMock()
    obj._start_watch_capture = MagicMock()
    obj.launch_player_for_episode = MagicMock()
    obj.executor = MagicMock()
    return obj, repos, session


def test_a_locked_database_does_not_kill_the_app(monkeypatch):
    """THE assertion. Pre-fix this propagates and PyQt aborts the process."""
    obj, repos, _session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())  # must not raise

    obj.launch_player_for_episode.assert_called_once(), (
        "the episode did not play; bookkeeping blocked the user's actual intent"
    )


def test_the_episode_still_plays_when_bookkeeping_fails(monkeypatch):
    """Degraded, not broken — the stream is what the user asked for."""
    obj, repos, _session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode(title="The Gang Gets Tested"))

    assert obj.launch_player_for_episode.call_count == 1


def test_the_session_is_still_closed_when_bookkeeping_fails():
    """The finally must survive the new except — a leaked session is a lock."""
    obj, repos, session = _host(failure=_locked())

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())

    session.close.assert_called_once()


def test_the_failure_is_logged_not_swallowed():
    """A lock held this long is a real problem; it just must not be fatal."""
    from metatv.gui import main_window_series

    obj, repos, _session = _host(failure=_locked())
    logged: list[str] = []
    monkey = MagicMock()
    monkey.error.side_effect = lambda msg, *a: logged.append(str(msg))
    monkey.info.side_effect = lambda *a, **k: None
    monkey.warning.side_effect = lambda *a, **k: None
    monkey.debug.side_effect = lambda *a, **k: None

    with patch.object(main_window_series, "logger", monkey), \
            patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())

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

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())

    obj.launch_player_for_episode.assert_called_once()


def test_the_normal_path_is_unchanged():
    """The guard must not swallow a working play."""
    obj, repos, session = _host()

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(_Episode())

    repos.episodes.mark_played.assert_called_once_with("e1")
    obj.launch_player_for_episode.assert_called_once()
    session.close.assert_called_once()
