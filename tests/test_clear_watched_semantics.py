"""Test clear_watched() semantics for the watch queue.

Tests that clear_watched() removes only genuinely finished content, not
partially watched items.
"""

from datetime import datetime
import pytest

from metatv.core.database import Database, ChannelDB, EpisodeDB, WatchQueueDB


@pytest.fixture
def test_db(tmp_path):
    """Create a real Database on a temp file (never :memory:)."""
    db_path = tmp_path / "test.db"
    db = Database(f"sqlite:///{db_path}")
    db.create_tables()
    yield db


def test_clear_watched_series_partial_watched(test_db):
    """Series with 3 episodes, only 1 watched → KEPT."""
    with test_db.session_scope() as session:
        # Create a series channel
        series = ChannelDB(
            id="series_1",
            source_id="series_1_src",
            provider_id="test_provider",
            name="Test Series",
            media_type="series",
            watch_completed=False,
        )
        session.add(series)

        # Create 3 episodes: only first is watched
        ep1 = EpisodeDB(
            id="ep_1",
            episode_id="ep_1_api",
            series_id="series_1_src",
            provider_id="test_provider",
            season_id="s1_1",
            season_num=1,
            episode_num=1,
            title="Episode 1",
            is_watched=True,
            watch_completed=True,
        )
        ep2 = EpisodeDB(
            id="ep_2",
            episode_id="ep_2_api",
            series_id="series_1_src",
            provider_id="test_provider",
            season_id="s1_1",
            season_num=1,
            episode_num=2,
            title="Episode 2",
            is_watched=False,
            watch_completed=False,
        )
        ep3 = EpisodeDB(
            id="ep_3",
            episode_id="ep_3_api",
            series_id="series_1_src",
            provider_id="test_provider",
            season_id="s1_1",
            season_num=1,
            episode_num=3,
            title="Episode 3",
            is_watched=False,
            watch_completed=False,
        )
        session.add_all([ep1, ep2, ep3])

        # Add channel-grain queue entry for this series
        queue_entry = WatchQueueDB(
            channel_id="series_1",
            channel_name="Test Series",
            media_type="series",
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Series should NOT be removed (only 1/3 episodes watched)
        assert removed == 0
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 1
        assert queue_rows[0].channel_id == "series_1"


def test_clear_watched_series_all_watched(test_db):
    """Series with 3 episodes all watched → REMOVED."""
    with test_db.session_scope() as session:
        # Create a series channel
        series = ChannelDB(
            id="series_2",
            source_id="series_2_src",
            provider_id="test_provider",
            name="Watched Series",
            media_type="series",
            watch_completed=True,
        )
        session.add(series)

        # Create 3 episodes: all watched
        for i in range(1, 4):
            ep = EpisodeDB(
                id=f"ep_w{i}",
                episode_id=f"ep_w{i}_api",
                series_id="series_2_src",
                provider_id="test_provider",
                season_id="s2_1",
                season_num=1,
                episode_num=i,
                title=f"Episode {i}",
                is_watched=True,
                watch_completed=True,
            )
            session.add(ep)

        # Add channel-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="series_2",
            channel_name="Watched Series",
            media_type="series",
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Series should be removed (all 3 episodes watched)
        assert removed == 1
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 0


def test_clear_watched_series_no_episodes(test_db):
    """Series with no stored episodes → KEPT (conservative)."""
    with test_db.session_scope() as session:
        # Create a series channel with NO episodes
        series = ChannelDB(
            id="series_3",
            source_id="series_3_src",
            provider_id="test_provider",
            name="Series with no episodes",
            media_type="series",
            watch_completed=False,
        )
        session.add(series)

        # Add channel-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="series_3",
            channel_name="Series with no episodes",
            media_type="series",
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Series should NOT be removed (no episodes to prove it's finished)
        assert removed == 0
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 1


def test_clear_watched_episode_grain_unwatched(test_db):
    """Episode-grain row for unwatched episode → KEPT."""
    with test_db.session_scope() as session:
        # Create a series channel (parent)
        series = ChannelDB(
            id="series_4",
            source_id="series_4_src",
            provider_id="test_provider",
            name="Test Series 4",
            media_type="series",
        )
        session.add(series)

        # Create an unwatched episode
        ep = EpisodeDB(
            id="ep_unwatched",
            episode_id="ep_unwatched_api",
            series_id="series_4_src",
            provider_id="test_provider",
            season_id="s4_1",
            season_num=1,
            episode_num=1,
            title="Unwatched Episode",
            is_watched=False,
            watch_completed=False,
        )
        session.add(ep)

        # Add episode-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="series_4",
            channel_name="Test Series 4",
            media_type="series",
            episode_id="ep_unwatched",
            season_num=1,
            episode_num=1,
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Episode-grain entry should NOT be removed (unwatched)
        assert removed == 0
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 1


def test_clear_watched_episode_grain_watched(test_db):
    """Episode-grain row for watched episode → REMOVED."""
    with test_db.session_scope() as session:
        # Create a series channel (parent)
        series = ChannelDB(
            id="series_5",
            source_id="series_5_src",
            provider_id="test_provider",
            name="Test Series 5",
            media_type="series",
        )
        session.add(series)

        # Create a watched episode
        ep = EpisodeDB(
            id="ep_watched",
            episode_id="ep_watched_api",
            series_id="series_5_src",
            provider_id="test_provider",
            season_id="s5_1",
            season_num=1,
            episode_num=1,
            title="Watched Episode",
            is_watched=True,
            watch_completed=True,
        )
        session.add(ep)

        # Add episode-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="series_5",
            channel_name="Test Series 5",
            media_type="series",
            episode_id="ep_watched",
            season_num=1,
            episode_num=1,
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Episode-grain entry should be removed (watched)
        assert removed == 1
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 0


def test_clear_watched_movie_partial(test_db):
    """Movie with last_played but watch_completed=False → KEPT."""
    with test_db.session_scope() as session:
        # Create a movie channel with last_played set but NOT completed
        movie = ChannelDB(
            id="movie_1",
            source_id="movie_1_src",
            provider_id="test_provider",
            name="Partial Movie",
            media_type="movie",
            last_played=datetime.now(),
            watch_completed=False,
            watch_progress=1800,  # 30 mins watched
        )
        session.add(movie)

        # Add channel-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="movie_1",
            channel_name="Partial Movie",
            media_type="movie",
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Movie should NOT be removed (not completed)
        assert removed == 0
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 1


def test_clear_watched_movie_completed(test_db):
    """Movie with watch_completed=True → REMOVED."""
    with test_db.session_scope() as session:
        # Create a movie channel with watch_completed=True
        movie = ChannelDB(
            id="movie_2",
            source_id="movie_2_src",
            provider_id="test_provider",
            name="Finished Movie",
            media_type="movie",
            last_played=datetime.now(),
            watch_completed=True,
        )
        session.add(movie)

        # Add channel-grain queue entry
        queue_entry = WatchQueueDB(
            channel_id="movie_2",
            channel_name="Finished Movie",
            media_type="movie",
            position=0,
        )
        session.add(queue_entry)
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Movie should be removed (watch_completed=True)
        assert removed == 1
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 0


def test_clear_watched_mixed_queue(test_db):
    """Mixed queue with various items → correct ones removed."""
    with test_db.session_scope() as session:
        # Create multiple items: partial series, completed movie, unwatched live
        series = ChannelDB(
            id="mixed_series",
            source_id="mixed_series_src",
            provider_id="test_provider",
            name="Partial Series",
            media_type="series",
        )
        movie = ChannelDB(
            id="mixed_movie",
            source_id="mixed_movie_src",
            provider_id="test_provider",
            name="Completed Movie",
            media_type="movie",
            watch_completed=True,
        )
        live = ChannelDB(
            id="mixed_live",
            source_id="mixed_live_src",
            provider_id="test_provider",
            name="Live Channel",
            media_type="live",
            watch_completed=False,
        )
        session.add_all([series, movie, live])

        # Add series episode (partial)
        ep = EpisodeDB(
            id="mixed_ep",
            episode_id="mixed_ep_api",
            series_id="mixed_series",
            provider_id="test_provider",
            season_id="mixed_s1",
            season_num=1,
            episode_num=1,
            title="Partial Episode",
            is_watched=False,
            watch_completed=False,
        )
        session.add(ep)

        # Add queue entries
        q1 = WatchQueueDB(
            channel_id="mixed_series",
            channel_name="Partial Series",
            media_type="series",
            position=0,
        )
        q2 = WatchQueueDB(
            channel_id="mixed_movie",
            channel_name="Completed Movie",
            media_type="movie",
            position=1,
        )
        q3 = WatchQueueDB(
            channel_id="mixed_live",
            channel_name="Live Channel",
            media_type="live",
            position=2,
        )
        session.add_all([q1, q2, q3])
        session.commit()

        # Clear watched
        from metatv.core.repositories.queue import WatchQueueRepository
        repo = WatchQueueRepository(session)
        removed = repo.clear_watched()

        # Only completed movie should be removed
        assert removed == 1
        queue_rows = session.query(WatchQueueDB).all()
        assert len(queue_rows) == 2
        remaining_ids = {r.channel_id for r in queue_rows}
        assert "mixed_series" in remaining_ids
        assert "mixed_live" in remaining_ids
        assert "mixed_movie" not in remaining_ids
