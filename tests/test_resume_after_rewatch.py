"""Behavioral tests for the resume-after-rewatch bug fix.

The bug: finishing a VOD sets watch_completed=True and watch_progress=0.
Re-watching it partway set watch_progress=3914 but left watch_completed=True.
The play_media guard ``watch_progress > 0 and not watch_completed`` then
blocked resume, so the title always restarted from the beginning.

Fix:
1. ChannelRepository.record_watch_progress else-branch clears watch_completed=False.
2. EpisodeRepository.record_watch_progress else-branch clears both watch_completed=False
   and is_watched=False.
3. play_media guard drops the now-redundant ``and not watch_completed`` so that
   watch_progress > 0 alone is the resume condition — this also heals existing
   rows stuck with progress > 0 and watch_completed = True.

Covered behaviors
-----------------
1. Channel: completing a movie sets watch_completed=True, watch_progress=0.
2. Channel: partial re-watch after completion clears watch_completed, sets watch_progress.
3. Channel: the exact regression — progress=3914, duration~=8000 after prior completion.
4. Episode: completing an episode sets is_watched=True, watch_completed=True, watch_progress=0.
5. Episode: partial re-watch after completion clears both flags, sets watch_progress.
6. Resume guard (legacy row): channel with progress=3914, watch_completed=True (legacy)
   resolves start_seconds=3914 -- proves the guard heals stuck rows.
7. Resume guard: progress=0 -> start_seconds=0 (no spurious resume).
8. Resume guard: live channel -> start_seconds=0 regardless of progress.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# File-backed DB fixture (NOT :memory: -- pooled :memory: connections each
# get an empty DB, breaking session_scope-based tests that open a second
# connection to verify committed state).
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'rewatch.db'}")
    d.create_tables()
    yield d
    d.close()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _seed_channel(db, ch_id: str, *, watch_progress: int = 0, watch_completed: bool = False) -> None:
    from metatv.core.database import ChannelDB
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=ch_id,
            source_id=ch_id,
            provider_id="p1",
            name=f"Movie {ch_id}",
            media_type="movie",
            stream_url=f"http://example.com/{ch_id}.mp4",
            watch_progress=watch_progress,
            watch_completed=watch_completed,
        ))


def _seed_episode(db, ep_id: str, *, watch_progress: int = 0, watch_completed: bool = False,
                  is_watched: bool = False) -> None:
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=ep_id,
            season_id="season1",
            series_id="series1",
            provider_id="p1",
            episode_id=ep_id,
            episode_num=1,
            season_num=1,
            title=f"Episode {ep_id}",
            watch_progress=watch_progress,
            watch_completed=watch_completed,
            is_watched=is_watched,
        ))


def _read_channel(db, ch_id: str) -> dict:
    """Return watch fields for a channel as a plain dict (after session closes)."""
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id(ch_id)
        return {
            "watch_progress": ch.watch_progress,
            "watch_completed": ch.watch_completed,
            "watch_percent": ch.watch_percent,
        }


def _read_episode(db, ep_id: str) -> dict:
    """Return watch fields for an episode as a plain dict (after session closes)."""
    from metatv.core.repositories import RepositoryFactory
    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id(ep_id)
        return {
            "watch_progress": ep.watch_progress,
            "watch_completed": ep.watch_completed,
            "is_watched": ep.is_watched,
            "watch_percent": ep.watch_percent,
        }


# ---------------------------------------------------------------------------
# 1. Channel: completing a movie sets watch_completed=True, watch_progress=0
# ---------------------------------------------------------------------------

def test_channel_completion_sets_completed_clears_progress(db):
    """record_watch_progress at >= threshold marks complete and zeroes progress."""
    _seed_channel(db, "movie1")

    dur = 8000.0
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        result = RepositoryFactory(session).channels.record_watch_progress(
            "movie1", position_s=dur * 0.95, duration_s=dur
        )

    assert result is True  # confirmed completion
    state = _read_channel(db, "movie1")
    assert state["watch_completed"] is True
    assert state["watch_progress"] == 0
    assert state["watch_percent"] == 100


# ---------------------------------------------------------------------------
# 2. Channel: partial re-watch after completion clears watch_completed
# ---------------------------------------------------------------------------

def test_channel_partial_rewatch_clears_completed(db):
    """Partial progress after a completed title clears watch_completed (invariant restored)."""
    _seed_channel(db, "movie2", watch_completed=True, watch_progress=0)

    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        RepositoryFactory(session).channels.record_watch_progress(
            "movie2", position_s=1200.0, duration_s=8000.0
        )

    state = _read_channel(db, "movie2")
    assert state["watch_completed"] is False
    assert state["watch_progress"] == 1200
    assert 14 <= state["watch_percent"] <= 16  # 1200/8000 = 15%


# ---------------------------------------------------------------------------
# 3. Channel: exact regression -- progress=3914, duration~=8000 after prior completion
# ---------------------------------------------------------------------------

def test_channel_stuck_row_is_healed_by_partial_progress(db):
    """The exact bug: after finishing once (completed=True, progress=0), a partial
    re-watch must clear watch_completed and set watch_progress=3914."""
    _seed_channel(db, "movie3")

    dur = 8000.0

    # First watch: complete it
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        RepositoryFactory(session).channels.record_watch_progress(
            "movie3", position_s=dur * 0.96, duration_s=dur
        )

    state = _read_channel(db, "movie3")
    assert state["watch_completed"] is True
    assert state["watch_progress"] == 0

    # Re-watch: stop partway through
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        RepositoryFactory(session).channels.record_watch_progress(
            "movie3", position_s=3914.0, duration_s=dur
        )

    state = _read_channel(db, "movie3")
    assert state["watch_completed"] is False, (
        "watch_completed must be cleared when progress is saved after a prior completion"
    )
    assert state["watch_progress"] == 3914
    pct = state["watch_percent"]
    assert 48 <= pct <= 50, f"Expected ~49%, got {pct}%"


# ---------------------------------------------------------------------------
# 4. Episode: completing sets is_watched=True, watch_completed=True, watch_progress=0
# ---------------------------------------------------------------------------

def test_episode_completion_sets_watched_and_completed(db):
    """record_watch_progress at >= threshold marks episode watched+completed."""
    _seed_episode(db, "ep1")

    dur = 2700.0
    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        result = RepositoryFactory(session).episodes.record_watch_progress(
            "ep1", position_s=dur * 0.95, duration_s=dur
        )

    assert result is True
    state = _read_episode(db, "ep1")
    assert state["is_watched"] is True
    assert state["watch_completed"] is True
    assert state["watch_progress"] == 0
    assert state["watch_percent"] == 100


# ---------------------------------------------------------------------------
# 5. Episode: partial re-watch after completion clears both flags
# ---------------------------------------------------------------------------

def test_episode_partial_rewatch_clears_both_flags(db):
    """Partial progress after a completed episode clears is_watched and watch_completed."""
    _seed_episode(db, "ep2", watch_completed=True, is_watched=True, watch_progress=0)

    with db.session_scope() as session:
        from metatv.core.repositories import RepositoryFactory
        RepositoryFactory(session).episodes.record_watch_progress(
            "ep2", position_s=800.0, duration_s=2700.0
        )

    state = _read_episode(db, "ep2")
    assert state["watch_completed"] is False, "watch_completed must be cleared on partial re-watch"
    assert state["is_watched"] is False, "is_watched must be cleared on partial re-watch"
    assert state["watch_progress"] == 800
    assert 28 <= state["watch_percent"] <= 32  # 800/2700 ~= 29.6%


# ---------------------------------------------------------------------------
# 6-8. Resume guard in play_media
# ---------------------------------------------------------------------------

def _make_streaming_host():
    from metatv.gui.main_window_streaming import _StreamingMixin
    host = _StreamingMixin.__new__(_StreamingMixin)
    host.loading_channels = set()
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif-1"
    host.player_manager = MagicMock()
    host.player_manager.is_available.return_value = True
    host.executor = MagicMock()
    host.config = MagicMock()
    host.config.playback_resume_mode = "resume"
    return host


def _make_channel_dto(media_type: str, watch_progress: int = 0, watch_completed: bool = False):
    from metatv.core.repositories.dtos import PlayableChannelDTO
    return PlayableChannelDTO(
        id="ch1",
        source_id="src1",
        provider_id="p1",
        name="Test",
        stream_url="http://example.com/stream.mp4",
        media_type=media_type,
        is_favorite=False,
        is_hidden=False,
        is_adult=False,
        logo_url=None,
        detected_prefix=None,
        detected_quality=None,
        detected_region=None,
        detected_title=None,
        detected_year=None,
        raw_data=None,
        metadata_id=None,
        watch_progress=watch_progress,
        watch_completed=watch_completed,
    )


def _submitted_start_seconds(host) -> int:
    call_args = host.executor.submit.call_args
    _, *pos_args = call_args[0]
    # pos_args order: channel_id, name, stream_url, provider_id, notif_id,
    #                 force_new_window, start_seconds, open_ended_buffer
    return pos_args[6]


def test_resume_guard_heals_legacy_stuck_row():
    """A legacy row with watch_progress=3914 and watch_completed=True must still
    resolve start_seconds=3914. The guard is now watch_progress > 0 alone, so
    old stuck rows are healed immediately without requiring a re-watch."""
    host = _make_streaming_host()
    channel = _make_channel_dto("movie", watch_progress=3914, watch_completed=True)

    host.play_media(channel)

    assert _submitted_start_seconds(host) == 3914, (
        "Legacy stuck rows (progress>0, completed=True) must resume at saved position"
    )


def test_resume_guard_zero_progress_gives_zero():
    """watch_progress=0 must never trigger a resume, completed or not."""
    host = _make_streaming_host()
    channel = _make_channel_dto("movie", watch_progress=0, watch_completed=False)

    host.play_media(channel)

    assert _submitted_start_seconds(host) == 0


def test_resume_guard_live_channel_always_zero():
    """Live channels must never resume, even if they somehow have watch_progress > 0."""
    host = _make_streaming_host()
    channel = _make_channel_dto("live", watch_progress=1800, watch_completed=False)

    host.play_media(channel)

    assert _submitted_start_seconds(host) == 0
