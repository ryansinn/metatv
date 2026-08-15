"""Behavioral tests for What's New #0304 — episodes can now be resumed.

Covers the two confirmed gaps:
1. DetailsPaneWidget.show_episode never surfaced a Resume button for an
   episode with a saved position (details_pane.py's Resume gate was
   movie-only) — Cases 1-3 below assert the Resume button's RENDERED state
   (visibility + formatted M:SS text), not just that some method fired.
2. The episode launch path (launch_player_for_episode / _do_launch_episode)
   had no way to carry a start position through to _play_checked — Case 5
   asserts start_seconds actually reaches _play_checked, with a default-0
   case proving every existing (non-resume) call site is unchanged.

All DB-backed cases use a real file-backed Database (tmp_path), never
:memory:, per CLAUDE.md. Qt widget cases go through a real DetailsPaneWidget
(db=None — no DB-backed section is exercised by show_episode).
"""

from __future__ import annotations

import concurrent.futures
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from metatv.core.database import Database, ChannelDB, EpisodeDB, SeasonDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import EpisodeDTO


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path: Path):
    """File-backed (not :memory:) Database so every pooled connection shares tables."""
    d = Database(f"sqlite:///{tmp_path / 'test.db'}")
    d.create_tables()
    yield d
    d.close()


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _make_config():
    from metatv.core.config import Config
    return Config()


def _fake_channel(media_type="series", *, name="Test Show"):
    ch = MagicMock()
    ch.id = str(uuid.uuid4())
    ch.name = name
    ch.media_type = media_type
    ch.is_favorite = False
    ch.is_adult = False
    ch.detected_title = name
    ch.detected_year = None
    ch.detected_prefix = None
    ch.detected_quality = None
    ch.detected_region = None
    ch.raw_data = None
    ch.provider_id = None
    ch.watch_completed = False
    ch.watch_progress = 0
    ch.logo_url = None
    return ch


def _make_details_pane(qapp):
    from metatv.gui.details_pane import DetailsPaneWidget
    cache = MagicMock()
    cache.get_image_sync.return_value = None
    return DetailsPaneWidget(_make_config(), cache, db=None)


def _episode_dto(
    title="Pilot", *, episode_id=None, episode_num=1, season_num=1,
    watch_progress=0, watch_completed=False,
):
    return EpisodeDTO(
        id=episode_id or str(uuid.uuid4()), episode_num=episode_num, season_num=season_num,
        title=title, series_name="Test Show", stream_url="http://stream/ep",
        duration="45:00", is_watched=False, rating=None,
        watch_progress=watch_progress, watch_completed=watch_completed,
    )


def _seed_series(db: Database, name: str = "Breaking Bad", provider_id: str = "p1",
                  source_id: str = "series1") -> str:
    """Insert a series ChannelDB row; return its id."""
    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id=source_id, provider_id=provider_id,
            name=name, media_type="series",
        ))
    return cid


def _seed_episode(
    db: Database, *, provider_id: str = "p1", series_source_id: str = "series1",
    season_num: int = 1, episode_num: int = 1, title: str = "Pilot",
) -> str:
    """Insert an EpisodeDB (+ its SeasonDB parent); return the episode id."""
    season_id = f"{provider_id}_{series_source_id}_s{season_num:02d}"
    ep_id = f"{provider_id}_{series_source_id}_e{episode_num}"
    with db.session_scope() as session:
        if not session.get(SeasonDB, season_id):
            session.add(SeasonDB(
                id=season_id, series_id=series_source_id, provider_id=provider_id,
                season_number=season_num, name=f"Season {season_num}",
            ))
        session.add(EpisodeDB(
            id=ep_id, season_id=season_id, series_id=series_source_id,
            provider_id=provider_id, episode_id=str(episode_num),
            episode_num=episode_num, season_num=season_num,
            title=title, stream_url="http://example.com/ep",
        ))
    return ep_id


# ---------------------------------------------------------------------------
# 1-3. DetailsPaneWidget — Resume button rendered state in episode mode
# ---------------------------------------------------------------------------

class TestEpisodeResumeButtonRenderedState:
    def test_resume_visible_with_correct_formatted_position(self, qapp):
        """Case 1 (mandatory rendered-appearance assertion).

        An episode with a saved, incomplete position must show a Resume
        button whose ``isHidden()`` flag is False (the project's established
        rendered-visibility check for an unshown-parent widget tree — see
        test_details_rating_sentiment_layout.py / test_details_double_click_
        actions.py) AND whose text carries the correctly formatted M:SS
        position (450s == 7:30) — not just "some button exists somewhere".
        """
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto(watch_progress=450, watch_completed=False)

        pane.show_episode(ep, series)

        assert not pane._action_bar.resume_button.isHidden()
        assert "7:30" in pane._action_bar.resume_button.text()

    def test_resume_hidden_when_no_saved_progress(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto(watch_progress=0, watch_completed=False)

        pane.show_episode(ep, series)

        assert pane._action_bar.resume_button.isHidden()

    def test_resume_hidden_when_episode_completed(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto(watch_progress=450, watch_completed=True)

        pane.show_episode(ep, series)

        assert pane._action_bar.resume_button.isHidden()

    def test_resume_hides_again_on_return_to_series_root(self, qapp):
        """Switching from an episode with Resume showing back to the series
        root via show_channel must not leave a stale Resume button visible —
        series roots are gated by MOVIE media_type only, never SERIES."""
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto(watch_progress=450, watch_completed=False)

        pane.show_episode(ep, series)
        assert not pane._action_bar.resume_button.isHidden()

        pane.show_channel(series)

        assert pane._action_bar.resume_button.isHidden()


# ---------------------------------------------------------------------------
# 4. Resume click routes to the EPISODE-grain signal, not the channel-grain one
# ---------------------------------------------------------------------------

class TestEpisodeResumeClickRouting:
    def test_resume_click_emits_episode_signal_not_channel_signal(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto(watch_progress=450, watch_completed=False)
        pane.show_episode(ep, series)

        episode_fired, channel_fired = [], []
        pane.resume_episode_requested.connect(lambda: episode_fired.append(True))
        pane.resume_requested.connect(lambda cid: channel_fired.append(cid))

        pane._action_bar.resume_button.click()

        assert episode_fired == [True]
        assert channel_fired == [], (
            "emitting the channel-grain resume_requested here would resume the "
            "wrong item (the series row, not the episode)"
        )

    def test_resume_click_in_channel_mode_still_emits_channel_signal(self, qapp):
        """Non-regression: a movie/live channel's Resume click must still emit
        the original channel-grain signal."""
        pane = _make_details_pane(qapp)
        channel = _fake_channel("movie")
        channel.watch_progress = 450
        channel.watch_completed = False
        pane.show_channel(channel)

        episode_fired, channel_fired = [], []
        pane.resume_episode_requested.connect(lambda: episode_fired.append(True))
        pane.resume_requested.connect(lambda cid: channel_fired.append(cid))

        pane._action_bar.resume_button.click()

        assert channel_fired == [channel.id]
        assert episode_fired == []


# ---------------------------------------------------------------------------
# 5. start_seconds threaded through the episode launch path
# ---------------------------------------------------------------------------

class _ImmediateExecutor:
    """Test double: runs submitted work synchronously so the preflight's
    add_done_callback fires inline, making launch_player_for_episode
    deterministic without a real background thread."""

    def submit(self, fn, *args, **kwargs):
        future = concurrent.futures.Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as exc:  # pragma: no cover - defensive
            future.set_exception(exc)
        return future


def _build_launch_host():
    from metatv.gui.main_window_series import _SeriesMixin
    host = _SeriesMixin.__new__(_SeriesMixin)
    host.player_manager = MagicMock()
    host.player_manager.is_available.return_value = True
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif-1"
    host.validate_stream_url = MagicMock(return_value=(True, None))
    host.executor = _ImmediateExecutor()
    host._episode_ready = MagicMock()
    return host


def _build_do_launch_host():
    from metatv.gui.main_window_series import _SeriesMixin
    host = _SeriesMixin.__new__(_SeriesMixin)
    host.notification_manager = MagicMock()
    host.status_bar = MagicMock()
    host._start_playback_health = MagicMock()
    host._play_checked = MagicMock(return_value=True)
    return host


class TestStartSecondsThreadedThroughLaunchPath:
    def test_do_launch_episode_passes_start_seconds_to_play_checked(self, qapp):
        host = _build_do_launch_host()

        host._do_launch_episode(
            "notif-1", "http://x/ep", "Title", None,
            provider_id="p1", start_seconds=125,
        )

        host._play_checked.assert_called_once_with(
            "http://x/ep", "Title", provider_id="p1", start_seconds=125
        )

    def test_do_launch_episode_defaults_start_seconds_to_zero(self, qapp):
        """Every existing call site (which never passes start_seconds) must
        keep its current from-the-beginning behaviour unchanged."""
        host = _build_do_launch_host()

        host._do_launch_episode("notif-1", "http://x/ep", "Title", None, provider_id="p1")

        host._play_checked.assert_called_once_with(
            "http://x/ep", "Title", provider_id="p1", start_seconds=0
        )

    def test_launch_player_for_episode_threads_start_seconds_into_signal(self, qapp):
        host = _build_launch_host()

        host.launch_player_for_episode(
            "http://x/ep", "Title", queue_episodes=None,
            provider_id="p1", start_seconds=90,
        )

        host._episode_ready.emit.assert_called_once_with(
            "notif-1", "http://x/ep", "Title", None, "p1", 90
        )

    def test_launch_player_for_episode_default_start_seconds_is_zero(self, qapp):
        host = _build_launch_host()

        host.launch_player_for_episode("http://x/ep", "Title", provider_id="p1")

        host._episode_ready.emit.assert_called_once_with(
            "notif-1", "http://x/ep", "Title", None, "p1", 0
        )

    def test_play_episode_forwards_start_seconds_to_launch_player_for_episode(self, db):
        from metatv.gui.main_window_series import _SeriesMixin

        _seed_series(db)
        ep_id = _seed_episode(db, season_num=1, episode_num=2, title="Cat's in the Bag...")
        with db.session_scope(commit=False) as session:
            episode = RepositoryFactory(session).episodes.get_playable_dto(ep_id)

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        host.config = _make_config()
        host.player_manager = MagicMock()
        host.load_history = MagicMock()
        host.load_favorites = MagicMock()
        host._start_watch_capture = MagicMock()
        host.launch_player_for_episode = MagicMock()

        host.play_episode(episode, queue_season=False, start_seconds=200)

        host.launch_player_for_episode.assert_called_once()
        _, kwargs = host.launch_player_for_episode.call_args
        assert kwargs["start_seconds"] == 200
        assert kwargs["provider_id"] == episode.provider_id, (
            "adding start_seconds must not drop the provider_id keying"
        )

    def test_play_episode_default_start_seconds_is_zero(self, db):
        """Every existing play_episode call site (Play Episode, queue rows,
        season Play-All, ...) never passes start_seconds — must stay 0."""
        from metatv.gui.main_window_series import _SeriesMixin

        _seed_series(db)
        ep_id = _seed_episode(db, season_num=1, episode_num=3, title="...And the Bag's in the River")
        with db.session_scope(commit=False) as session:
            episode = RepositoryFactory(session).episodes.get_playable_dto(ep_id)

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        host.config = _make_config()
        host.player_manager = MagicMock()
        host.load_history = MagicMock()
        host.load_favorites = MagicMock()
        host._start_watch_capture = MagicMock()
        host.launch_player_for_episode = MagicMock()

        host.play_episode(episode, queue_season=False)

        _, kwargs = host.launch_player_for_episode.call_args
        assert kwargs["start_seconds"] == 0


# ---------------------------------------------------------------------------
# Host handler — _on_details_resume_episode reads current_episode.watch_progress
# ---------------------------------------------------------------------------

class TestOnDetailsResumeEpisodeHandler:
    def test_reads_current_episode_watch_progress_and_calls_play_episode(self, qapp):
        from metatv.gui.main_window_series import _SeriesMixin

        host = _SeriesMixin.__new__(_SeriesMixin)
        ep = _episode_dto(watch_progress=333, watch_completed=False)
        host.details_pane = MagicMock()
        host.details_pane.current_episode = ep
        host.play_episode = MagicMock()

        host._on_details_resume_episode()

        host.play_episode.assert_called_once_with(ep, start_seconds=333)

    def test_noop_when_no_current_episode(self, qapp):
        from metatv.gui.main_window_series import _SeriesMixin

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.details_pane = MagicMock()
        host.details_pane.current_episode = None
        host.play_episode = MagicMock()

        host._on_details_resume_episode()

        host.play_episode.assert_not_called()
