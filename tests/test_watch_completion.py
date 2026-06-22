"""Watch-completion engine (Slice 1): record_watch_progress.

The chokepoint records a VOD item's resume position and marks it *completed*
(sticky) once watched past a configurable fraction of its duration. Covers
movies (ChannelRepository) and episodes (EpisodeRepository), which share the
same semantics: resume point on partial, sticky completion + cleared resume at
threshold, completion is one-way (a later partial rewatch doesn't un-finish it).
"""

from __future__ import annotations

import pytest

from metatv.core.database import Database, ChannelDB, EpisodeDB
from metatv.core.repositories import RepositoryFactory


@pytest.fixture()
def db(tmp_path):
    d = Database(f"sqlite:///{tmp_path / 'watch.db'}")
    d.create_tables()
    yield d
    d.close()


# ── Movies (ChannelRepository) ─────────────────────────────────────────────────

def _seed_movie(db, ch_id="m1"):
    s = db.get_session()
    try:
        s.add(ChannelDB(id=ch_id, source_id=ch_id, provider_id="p",
                        name="Movie", media_type="movie"))
        s.commit()
    finally:
        s.close()


def test_partial_watch_sets_resume_not_completed(db):
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        done = repo.record_watch_progress("m1", position_s=600, duration_s=3000)  # 20%
        assert done is False
        ch = repo.get_by_id("m1")
        assert ch.watch_progress == 600
        assert bool(ch.watch_completed) is False
        assert ch.last_played_via == "manual"
        assert ch.last_played is not None
    finally:
        s.close()


def test_crossing_threshold_marks_completed_and_clears_resume(db):
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        done = repo.record_watch_progress("m1", position_s=2900, duration_s=3000)  # 96%
        assert done is True
        ch = repo.get_by_id("m1")
        assert bool(ch.watch_completed) is True
        assert ch.watch_progress == 0, "finished item must not linger in 'continue watching'"
    finally:
        s.close()


def test_completion_is_sticky(db):
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        repo.record_watch_progress("m1", 2900, 3000)            # finish it
        repo.record_watch_progress("m1", 300, 3000)             # rewatch, stop at 10%
        ch = repo.get_by_id("m1")
        assert bool(ch.watch_completed) is True, "completion is one-way (stays finished)"
        assert ch.watch_progress == 300, "resume point still tracks the rewatch"
    finally:
        s.close()


def test_threshold_is_configurable(db):
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        # 80% counts as complete at 0.75, but not at the 0.9 default.
        assert repo.record_watch_progress("m1", 800, 1000, threshold=0.75) is True
    finally:
        s.close()
    _seed_movie(db, "m2")
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        assert repo.record_watch_progress("m2", 800, 1000, threshold=0.9) is False
    finally:
        s.close()


def test_played_via_recorded(db):
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        repo.record_watch_progress("m1", 100, 1000, played_via="queue")
        assert repo.get_by_id("m1").last_played_via == "queue"
    finally:
        s.close()


def test_missing_channel_is_safe(db):
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        assert repo.record_watch_progress("nope", 100, 200) is False
    finally:
        s.close()


def test_zero_duration_never_completes(db):
    """A live/unknown-duration stream (duration 0) must never be 'completed'."""
    _seed_movie(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).channels
        assert repo.record_watch_progress("m1", 5000, 0) is False
        assert bool(repo.get_by_id("m1").watch_completed) is False
    finally:
        s.close()


# ── Episodes (EpisodeRepository) ───────────────────────────────────────────────

def _seed_episode(db, ep_id="e1"):
    s = db.get_session()
    try:
        s.add(EpisodeDB(id=ep_id, series_id="ser1", season_id="s1", provider_id="p",
                        episode_id="ep1", season_num=1, episode_num=1, title="E1"))
        s.commit()
    finally:
        s.close()


def test_episode_partial_then_complete(db):
    _seed_episode(db)
    s = db.get_session()
    try:
        repo = RepositoryFactory(s).episodes
        assert repo.record_watch_progress("e1", 300, 1500) is False  # 20%
        assert repo.get_by_id("e1").watch_progress == 300
        assert repo.record_watch_progress("e1", 1450, 1500) is True  # 96%
        ep = repo.get_by_id("e1")
        assert bool(ep.is_watched) is True
        assert ep.watch_progress == 0
    finally:
        s.close()
