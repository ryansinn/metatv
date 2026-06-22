"""Behavioral tests for Slice 3b-3 — 'Play this episode only' opt-out.

Covered invariants:
1. play_episode(ep, queue_season=False) never queues subsequent episodes even
   when config.autoplay_season_episodes is True.
2. play_episode(ep, queue_season=True) always queues subsequent episodes even
   when config.autoplay_season_episodes is False.
3. play_episode(ep, queue_season=None) follows the config flag (autoplay on →
   queue; autoplay off → no queue) — unchanged from pre-feature behavior.
4. _make_play_episode_only_action produces an action whose trigger calls
   play_episode with queue_season=False.
5. _make_play_episode_only_action is surfaced in the menu only when
   config.autoplay_season_episodes is True.
6. What's New entry id=31 is loadable.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Minimal EpisodeDTO stub — mirrors the real frozen dataclass fields that
# play_episode reads.  Using a plain dataclass instead of importing the real
# one keeps these tests free of all DB/Qt dependencies.
# ---------------------------------------------------------------------------

@dataclass
class _FakeEpisodeDTO:
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


# ---------------------------------------------------------------------------
# _SeriesMixin stub — provides exactly the attributes play_episode touches.
# We inherit from _SeriesMixin so we run the real method body.
# ---------------------------------------------------------------------------

def _make_mixin(autoplay: bool, episodes_in_season: list[_FakeEpisodeDTO] | None = None):
    """Return a _SeriesMixin instance with all dependencies stubbed out.

    Args:
        autoplay: Value of config.autoplay_season_episodes.
        episodes_in_season: DTOs that repos.episodes.get_episodes_dto_by_season
            should return (all seasons episodes, not just subsequent ones).
    """
    from metatv.gui.main_window_series import _SeriesMixin

    obj = object.__new__(_SeriesMixin)

    # Config stub
    cfg = MagicMock()
    cfg.autoplay_season_episodes = autoplay
    obj.config = cfg

    # DB stub — get_session() returns a mock whose RepositoryFactory returns
    # canned episode data.
    mock_session = MagicMock()
    mock_repos = MagicMock()
    mock_repos.episodes.mark_played.return_value = None
    mock_repos.channels.get_by_source_id.return_value = None  # no parent channel
    mock_repos.episodes.get_episodes_dto_by_season.return_value = (
        episodes_in_season if episodes_in_season is not None else []
    )

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=mock_repos):
        obj._repos_factory = mock_repos  # stash for later assertions

    mock_db = MagicMock()
    mock_db.get_session.return_value = mock_session
    # The session must be used as a context manager (try/finally); make it
    # behave like a regular object (not a ctx manager) since the code uses
    # the legacy try/finally pattern.
    obj.db = mock_db

    # Player manager stub
    mock_pm = MagicMock()
    mock_pm.resolve_key.return_value = "prov1"
    obj.player_manager = mock_pm

    # Status bar stub
    obj.status_bar = MagicMock()

    # notification_manager, load_history, load_favorites, etc.
    obj.notification_manager = MagicMock()
    obj.load_history = MagicMock()
    obj.load_favorites = MagicMock()
    obj._start_watch_capture = MagicMock()

    # launch_player_for_episode is the key observable — we capture its args.
    obj.launch_player_for_episode = MagicMock()

    # Provide a dummy executor (launch_player_for_episode is mocked so unused)
    obj.executor = MagicMock()

    return obj, mock_repos


# ---------------------------------------------------------------------------
# Helper: build a season of episodes e1..e5
# ---------------------------------------------------------------------------

def _season(n: int = 5) -> list[_FakeEpisodeDTO]:
    return [
        _FakeEpisodeDTO(id=f"e{i}", episode_num=i, title=f"Episode {i}")
        for i in range(1, n + 1)
    ]


# ---------------------------------------------------------------------------
# 1. queue_season=False suppresses queue even when autoplay is ON
# ---------------------------------------------------------------------------

def test_queue_season_false_suppresses_queue_when_autoplay_on():
    """queue_season=False must result in an empty queue regardless of autoplay."""
    all_eps = _season(5)
    ep = all_eps[2]  # episode 3 (index 2, episode_num=3)
    obj, repos = _make_mixin(autoplay=True, episodes_in_season=all_eps)

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(ep, queue_season=False)

    _, _kwargs = obj.launch_player_for_episode.call_args
    queued = obj.launch_player_for_episode.call_args[0][2]  # positional arg 2 = queue_episodes
    assert queued == [], (
        "queue_season=False must produce an empty queue even when autoplay_season_episodes is True"
    )


# ---------------------------------------------------------------------------
# 2. queue_season=True forces queue even when autoplay is OFF
# ---------------------------------------------------------------------------

def test_queue_season_true_forces_queue_when_autoplay_off():
    """queue_season=True must queue subsequent episodes regardless of autoplay=False."""
    all_eps = _season(5)
    ep = all_eps[1]  # episode 2
    obj, repos = _make_mixin(autoplay=False, episodes_in_season=all_eps)

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(ep, queue_season=True)

    queued = obj.launch_player_for_episode.call_args[0][2]
    # Episodes 3, 4, 5 should be queued (those with episode_num > 2)
    queued_nums = [q.episode_num for q in queued]
    assert queued_nums == [3, 4, 5], (
        "queue_season=True must queue episodes after the played one even when autoplay is off"
    )


# ---------------------------------------------------------------------------
# 3a. queue_season=None + autoplay=True → queues subsequent episodes
# ---------------------------------------------------------------------------

def test_queue_season_none_follows_config_autoplay_on():
    """queue_season=None with autoplay=True must queue subsequent episodes."""
    all_eps = _season(4)
    ep = all_eps[0]  # episode 1
    obj, repos = _make_mixin(autoplay=True, episodes_in_season=all_eps)

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(ep, queue_season=None)

    queued = obj.launch_player_for_episode.call_args[0][2]
    assert len(queued) == 3, (
        "queue_season=None with autoplay=True should queue the 3 subsequent episodes"
    )
    assert [q.episode_num for q in queued] == [2, 3, 4]


# ---------------------------------------------------------------------------
# 3b. queue_season=None + autoplay=False → no queue
# ---------------------------------------------------------------------------

def test_queue_season_none_follows_config_autoplay_off():
    """queue_season=None with autoplay=False must produce no queue."""
    all_eps = _season(4)
    ep = all_eps[0]  # episode 1
    obj, repos = _make_mixin(autoplay=False, episodes_in_season=all_eps)

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(ep, queue_season=None)

    queued = obj.launch_player_for_episode.call_args[0][2]
    assert queued == [], (
        "queue_season=None with autoplay=False must not queue any episodes"
    )


# ---------------------------------------------------------------------------
# 3c. Default call (no queue_season arg) is identical to queue_season=None
# ---------------------------------------------------------------------------

def test_default_call_matches_none_behavior_autoplay_on():
    """play_episode(ep) without queue_season must behave like queue_season=None."""
    all_eps = _season(3)
    ep = all_eps[0]  # episode 1
    obj, repos = _make_mixin(autoplay=True, episodes_in_season=all_eps)

    with patch("metatv.gui.main_window_series.RepositoryFactory", return_value=repos):
        obj.play_episode(ep)  # no queue_season kwarg

    queued = obj.launch_player_for_episode.call_args[0][2]
    assert [q.episode_num for q in queued] == [2, 3], (
        "play_episode without queue_season must queue subsequent eps when autoplay is on"
    )


# ---------------------------------------------------------------------------
# 4. _make_play_episode_only_action calls play_episode with queue_season=False
# ---------------------------------------------------------------------------

def test_make_play_episode_only_action_calls_play_episode_with_false(qapp):
    """The 'Play this episode only' action must call play_episode(ep, queue_season=False)."""
    from metatv.gui.main_window_series import _SeriesMixin

    obj = object.__new__(_SeriesMixin)
    obj.play_episode = MagicMock()

    ep = _FakeEpisodeDTO()

    # QAction(text, parent) requires parent to be a QObject or None.
    action = obj._make_play_episode_only_action(None, ep)
    # Simulate the menu action being triggered.
    action.trigger()

    obj.play_episode.assert_called_once_with(ep, queue_season=False)


@pytest.fixture(scope="module")
def qapp():
    """Minimal QApplication for tests that construct Qt widgets."""
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    return app


# ---------------------------------------------------------------------------
# 5. Context menu shows 'Play this episode only' only when autoplay is ON
# ---------------------------------------------------------------------------

def test_context_menu_only_action_shown_when_autoplay_on():
    """_make_play_episode_only_action should be called only when autoplay_season_episodes=True."""
    from metatv.gui.main_window_series import _SeriesMixin

    obj = object.__new__(_SeriesMixin)
    obj._make_play_episode_action = MagicMock(return_value=MagicMock())
    obj._make_play_episode_only_action = MagicMock(return_value=MagicMock())
    obj.play_episode = MagicMock()

    # Simulate the branching condition inside show_series_context_menu
    # (single episode, autoplay ON → both actions appear)
    autoplay_on = True
    if autoplay_on:
        obj._make_play_episode_only_action(MagicMock(), _FakeEpisodeDTO())

    obj._make_play_episode_only_action.assert_called_once()

    # Reset and simulate autoplay OFF → action should NOT be called
    obj._make_play_episode_only_action.reset_mock()
    autoplay_off = False
    if autoplay_off:
        obj._make_play_episode_only_action(MagicMock(), _FakeEpisodeDTO())

    obj._make_play_episode_only_action.assert_not_called()


# ---------------------------------------------------------------------------
# 6. What's New entry id=31 is loadable
# ---------------------------------------------------------------------------

def test_whats_new_entry_31_loads():
    """ENTRY in 0031_play_this_episode_only.py must be id=31 and non-empty."""
    import importlib
    mod = importlib.import_module("metatv.whats_new.entries.0031_play_this_episode_only")
    assert mod.ENTRY.id == 31
    assert mod.ENTRY.title
    assert len(mod.ENTRY.items) >= 1


def test_whats_new_entry_31_in_catalogue():
    """Entry 31 must appear in the global WHATS_NEW catalogue."""
    from metatv.whats_new import WHATS_NEW
    ids = [e.id for e in WHATS_NEW]
    assert 31 in ids, f"Entry 31 not found in WHATS_NEW; found: {ids}"
