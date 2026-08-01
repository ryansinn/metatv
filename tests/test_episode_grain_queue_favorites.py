"""Behavioral tests for Wave 2 Slice 2B — episode-grain Watch Queue + episode favorites.

Covers:
1. WatchQueueRepository.add_episode/remove_episode/is_episode_queued — round-trip at
   episode grain, incl. QueueEntry DTO fields (is_episode, season_num, episode_num,
   episode_title) and the channel-grain/episode-grain scoping split (add/remove/
   is_queued/get_queued_ids only ever touch episode_id IS NULL rows, independently
   of any episode-grain rows sharing the same parent channel_id).
2. Database._migrate() adds the new columns (episodes.is_favorite, seasons.is_favorite,
   watch_queue.episode_id/season_num/episode_num/episode_title) to a DB FILE created
   under the pre-Slice-2B schema, without touching pre-existing data.
3. EpisodeRepository — favorite toggle persists; get_favorites_dto returns favorited
   episodes only, with availability annotation.
4. DetailsPaneWidget episode mode — the queue button stays VISIBLE (targets the
   EPISODE, not the series) and its click / the favorite click emit
   episode_queue_toggled / episode_favorite_toggled with the EPISODE id;
   apply_episode_action_state's stale-drop guard; load() must not clobber the
   episode-scoped queue state when a same-titled series-level fetch resolves late.
5. main_window_favorites._on_details_episode_queue_toggle /
   _on_details_episode_favorite_toggle — real handlers against a real Database: the
   repository sees the EPISODE id (and the parent series id for the join), never a
   series-wide write.
6. play_episode_by_id — the shared chokepoint used by both the Watch Queue and
   Favorites sidebar rows for episode-grain playback.
7. The series-tree row's own context menu — Favorite/Unfavorite Episode persists and
   patches the tree item's UserRole DTO in place.
8. Sidebar UserRole payload shape (queue.py dict; favorites.py additive role) and the
   double-click / click routing that branches on it.

All DB tests use a real file-backed Database (tmp_path), never :memory:, per CLAUDE.md.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import Qt

from metatv.core.database import Database, ChannelDB, EpisodeDB, SeasonDB
from metatv.core.repositories import RepositoryFactory
from metatv.core.repositories.dtos import EpisodeDTO, EpisodeFavoriteDTO


# ---------------------------------------------------------------------------
# Fixtures
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


def _episode_dto(title="Pilot", *, episode_id=None, episode_num=1, season_num=1,
                  is_favorite=False):
    return EpisodeDTO(
        id=episode_id or str(uuid.uuid4()), episode_num=episode_num, season_num=season_num,
        title=title, series_name="Test Show", stream_url="http://stream/ep",
        duration="45:00", is_watched=False, rating=None, is_favorite=is_favorite,
    )


# ---------------------------------------------------------------------------
# 1. WatchQueueRepository — episode-grain round trip
# ---------------------------------------------------------------------------

class TestEpisodeGrainQueue:
    def test_add_episode_round_trip_dto_fields(self, db):
        series_id = _seed_series(db)
        ep_id = _seed_episode(db, season_num=2, episode_num=4, title="Face Off")

        with db.session_scope() as session:
            RepositoryFactory(session).queue.add_episode(
                ep_id, channel_id=series_id, channel_name="Breaking Bad",
                season_num=2, episode_num=4, episode_title="Face Off",
                source_id="series1",
            )

        with db.session_scope(commit=False) as session:
            entries = RepositoryFactory(session).queue.get_all()

        assert len(entries) == 1
        entry = entries[0]
        assert entry.is_episode is True
        assert entry.episode_id == ep_id
        assert entry.channel_id == series_id, "channel_id must be the PARENT SERIES"
        assert entry.season_num == 2
        assert entry.episode_num == 4
        assert entry.episode_title == "Face Off"
        assert entry.available is True

    def test_add_episode_is_noop_when_already_queued(self, db):
        series_id = _seed_series(db)
        ep_id = _seed_episode(db)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.queue.add_episode(ep_id, channel_id=series_id)
            repos.queue.add_episode(ep_id, channel_id=series_id)  # no-op

        with db.session_scope(commit=False) as session:
            entries = RepositoryFactory(session).queue.get_all()
        assert len(entries) == 1

    def test_remove_episode(self, db):
        series_id = _seed_series(db)
        ep_id = _seed_episode(db)
        with db.session_scope() as session:
            repos = RepositoryFactory(session)
            repos.queue.add_episode(ep_id, channel_id=series_id)
            assert repos.queue.is_episode_queued(ep_id) is True
            repos.queue.remove_episode(ep_id)
            assert repos.queue.is_episode_queued(ep_id) is False

        with db.session_scope(commit=False) as session:
            entries = RepositoryFactory(session).queue.get_all()
        assert entries == []

    def test_channel_and_episode_grain_are_independent(self, db):
        """Queuing an episode must NOT make the series root read as 'in queue', and
        vice versa — the grains are scoped independently via episode_id IS NULL."""
        series_id = _seed_series(db)
        ep_id = _seed_episode(db)

        with db.session_scope() as session:
            RepositoryFactory(session).queue.add_episode(ep_id, channel_id=series_id)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            assert repos.queue.is_queued(series_id) is False, (
                "queuing an episode must not flag the series root as queued"
            )
            assert repos.queue.is_episode_queued(ep_id) is True
            assert series_id not in repos.queue.get_queued_ids()

        # Reverse: queuing the series root as a whole channel must coexist with the
        # episode-grain row, not clobber it.
        with db.session_scope() as session:
            RepositoryFactory(session).queue.add(series_id, channel_name="Breaking Bad")

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            assert len(repos.queue.get_all()) == 2
            assert repos.queue.is_queued(series_id) is True
            assert repos.queue.is_episode_queued(ep_id) is True

        # remove(channel_id) must only delete the CHANNEL-grain row.
        with db.session_scope() as session:
            RepositoryFactory(session).queue.remove(series_id)
        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            assert repos.queue.is_queued(series_id) is False
            assert repos.queue.is_episode_queued(ep_id) is True, (
                "remove(channel_id) must never delete an episode-grain row"
            )

    def test_clear_watched_checks_episode_own_last_played(self, db):
        """clear_watched on an episode-grain row checks the EPISODE's own
        last_played, not the series'."""
        from datetime import datetime

        series_id = _seed_series(db)
        ep_id = _seed_episode(db)
        with db.session_scope() as session:
            RepositoryFactory(session).queue.add_episode(ep_id, channel_id=series_id)

        # Only the episode was played; the series channel's own last_played is NULL.
        with db.session_scope() as session:
            session.get(EpisodeDB, ep_id).last_played = datetime.utcnow()

        with db.session_scope() as session:
            removed = RepositoryFactory(session).queue.clear_watched()
        assert removed == 1

        with db.session_scope(commit=False) as session:
            assert RepositoryFactory(session).queue.get_all() == []


# ---------------------------------------------------------------------------
# 2. Migration — ALTER TABLE adds the new columns to a pre-upgrade DB file
# ---------------------------------------------------------------------------

def test_migration_adds_episode_grain_columns_to_existing_db(tmp_path: Path):
    """A DB file built under the pre-Slice-2B schema (no is_favorite / episode_*
    columns) gets them added by Database.create_tables() -> _migrate(), and a
    pre-existing row survives untouched."""
    db_path = tmp_path / "legacy.db"

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE episodes (
            id TEXT PRIMARY KEY, season_id TEXT NOT NULL, series_id TEXT NOT NULL,
            provider_id TEXT NOT NULL, episode_id TEXT NOT NULL,
            episode_num INTEGER NOT NULL, season_num INTEGER NOT NULL, title TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE seasons (
            id TEXT PRIMARY KEY, series_id TEXT NOT NULL, provider_id TEXT NOT NULL,
            season_number INTEGER NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE watch_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL,
            channel_name TEXT NOT NULL DEFAULT '', media_type TEXT NOT NULL DEFAULT '',
            source_id TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute(
        "INSERT INTO episodes (id, season_id, series_id, provider_id, episode_id, "
        "episode_num, season_num, title) VALUES "
        "('ep1', 's1', 'series1', 'p1', '1', 1, 1, 'Pilot')"
    )
    conn.execute(
        "INSERT INTO watch_queue (channel_id, channel_name, media_type, source_id, position) "
        "VALUES ('ch1', 'Some Channel', 'movie', 'src1', 0)"
    )
    conn.commit()
    conn.close()

    d = Database(f"sqlite:///{db_path}")
    d.create_tables()
    d.close()

    conn = sqlite3.connect(str(db_path))
    ep_cols = {row[1] for row in conn.execute("PRAGMA table_info(episodes)")}
    season_cols = {row[1] for row in conn.execute("PRAGMA table_info(seasons)")}
    wq_cols = {row[1] for row in conn.execute("PRAGMA table_info(watch_queue)")}

    assert "is_favorite" in ep_cols
    assert "is_favorite" in season_cols
    assert {"episode_id", "season_num", "episode_num", "episode_title"} <= wq_cols

    # Pre-existing rows survive the migration, unmodified.
    ep_row = conn.execute("SELECT title, is_favorite FROM episodes WHERE id='ep1'").fetchone()
    assert ep_row[0] == "Pilot"
    assert ep_row[1] in (0, None)

    wq_row = conn.execute(
        "SELECT channel_name, episode_id FROM watch_queue WHERE channel_id='ch1'"
    ).fetchone()
    assert wq_row[0] == "Some Channel", "pre-existing row must survive the migration untouched"
    assert wq_row[1] is None
    conn.close()


# ---------------------------------------------------------------------------
# 3. EpisodeRepository — favorite persistence + favorites loader
# ---------------------------------------------------------------------------

class TestEpisodeFavoritesRepository:
    def test_favorite_flag_persists(self, db):
        _seed_series(db)
        ep_id = _seed_episode(db)

        with db.session_scope() as session:
            ep = session.get(EpisodeDB, ep_id)
            assert not ep.is_favorite
            ep.is_favorite = True

        with db.session_scope(commit=False) as session:
            assert session.get(EpisodeDB, ep_id).is_favorite is True

    def test_get_favorites_dto_returns_favorited_episodes_only(self, db):
        _seed_series(db)
        fav_id = _seed_episode(db, episode_num=1, title="Fave")
        _seed_episode(db, episode_num=2, title="Not fave")

        with db.session_scope() as session:
            session.get(EpisodeDB, fav_id).is_favorite = True

        with db.session_scope(commit=False) as session:
            dtos = RepositoryFactory(session).episodes.get_favorites_dto()

        assert len(dtos) == 1
        assert dtos[0].id == fav_id
        assert dtos[0].title == "Fave"
        assert dtos[0].season_num == 1
        assert dtos[0].episode_num == 1
        assert dtos[0].available is True

    def test_get_favorites_dto_annotates_hidden_provider_unavailable(self, db):
        _seed_series(db, provider_id="p1")
        ep_id = _seed_episode(db, provider_id="p1")
        with db.session_scope() as session:
            session.get(EpisodeDB, ep_id).is_favorite = True

        with db.session_scope(commit=False) as session:
            dtos = RepositoryFactory(session).episodes.get_favorites_dto(
                hidden_provider_ids={"p1"}
            )
        assert dtos[0].available is False

    def test_get_playable_dto_resolves_episode(self, db):
        _seed_series(db)
        ep_id = _seed_episode(db, season_num=3, episode_num=7, title="Say My Name")

        with db.session_scope(commit=False) as session:
            playable = RepositoryFactory(session).episodes.get_playable_dto(ep_id)

        assert playable is not None
        assert playable.id == ep_id
        assert playable.title == "Say My Name"
        assert playable.season_num == 3
        assert playable.episode_num == 7

    def test_get_playable_dto_missing_episode_returns_none(self, db):
        with db.session_scope(commit=False) as session:
            assert RepositoryFactory(session).episodes.get_playable_dto("nope") is None


# ---------------------------------------------------------------------------
# 4. DetailsPaneWidget episode mode — queue/favorite target the EPISODE
# ---------------------------------------------------------------------------

class TestDetailsPaneEpisodeQueueFavorite:
    def test_queue_button_stays_visible_in_episode_mode(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        pane.show_episode(_episode_dto(), series)
        assert not pane._action_bar.queue_button.isHidden(), (
            "Watch Queue button must stay visible in episode mode (it now targets "
            "the episode, not the series)"
        )
        assert "watch queue" in pane._action_bar.queue_button.toolTip().lower()

    def test_queue_click_emits_episode_id_not_channel_id(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto("Face Off", season_num=2, episode_num=4)
        pane.show_episode(ep, series)

        episode_fired, channel_fired = [], []
        pane.episode_queue_toggled.connect(lambda eid: episode_fired.append(eid))
        pane.queue_toggled.connect(lambda cid: channel_fired.append(cid))

        pane._action_bar.queue_button.click()

        assert episode_fired == [ep.id]
        assert channel_fired == []

    def test_favorite_click_emits_episode_id_with_scoped_tooltip(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto("Face Off", season_num=2, episode_num=4)
        pane.show_episode(ep, series)

        assert "S02E04" in pane._action_bar.favorite_button.toolTip()

        episode_fired, channel_fired = [], []
        pane.episode_favorite_toggled.connect(lambda eid: episode_fired.append(eid))
        pane.favorite_toggled.connect(lambda cid: channel_fired.append(cid))

        pane._action_bar.favorite_button.click()

        assert episode_fired == [ep.id]
        assert channel_fired == []

    def test_apply_episode_action_state_updates_buttons(self, qapp):
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto()
        pane.show_episode(ep, series)
        assert pane._action_bar.queue_button.isChecked() is False

        pane.apply_episode_action_state(ep.id, in_queue=True, is_favorite=True)

        assert pane._action_bar.queue_button.isChecked() is True
        assert pane._action_bar.favorite_button.toolTip().lower().startswith("remove")

    def test_apply_episode_action_state_drops_stale_response(self, qapp):
        """A response for a since-abandoned episode must not touch button state."""
        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        pane.show_episode(_episode_dto(), series)

        pane.apply_episode_action_state("some-other-episode-id", in_queue=True, is_favorite=True)
        assert pane._action_bar.queue_button.isChecked() is False

    def test_series_level_load_does_not_clobber_episode_queue_state(self, qapp):
        """The series-level action_state_requested fetch can resolve AFTER the
        episode-level one (two independent async requests) — load() must not stomp
        the episode-scoped queue flag."""
        from metatv.gui.details_actions import ChannelActionState

        pane = _make_details_pane(qapp)
        series = _fake_channel("series")
        ep = _episode_dto()
        pane.show_episode(ep, series)

        pane.apply_episode_action_state(ep.id, in_queue=True, is_favorite=False)
        assert pane._action_bar.queue_button.isChecked() is True

        # A late series-level fetch resolves with in_queue=False for the series.
        pane.apply_action_state(ChannelActionState(channel_id=series.id, in_queue=False))
        assert pane._action_bar.queue_button.isChecked() is True, (
            "series-level load() must not clobber the episode-scoped queue state"
        )


# ---------------------------------------------------------------------------
# 5. main_window_favorites handlers — episode-grain queue/favorite toggle
# ---------------------------------------------------------------------------

def _build_favorites_host(db):
    from metatv.gui.main_window_favorites import _FavoritesMixin

    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.db = db
    host.status_bar = MagicMock()
    host.sidebar_sections = {}
    host.load_favorites = MagicMock()
    return host


class TestDetailsEpisodeToggleHandlers:
    def test_queue_toggle_adds_then_removes_by_episode_id(self, db):
        series_id = _seed_series(db)
        ep_id = _seed_episode(db, season_num=1, episode_num=3, title="...And the Bag's in the River")
        host = _build_favorites_host(db)

        host._on_details_episode_queue_toggle(ep_id)

        with db.session_scope(commit=False) as session:
            repos = RepositoryFactory(session)
            assert repos.queue.is_episode_queued(ep_id) is True
            assert repos.queue.is_queued(series_id) is False, (
                "must never write a channel-grain row for the series"
            )
            entry = repos.queue.get_all()[0]
            assert entry.episode_num == 3
            assert entry.channel_id == series_id

        host._on_details_episode_queue_toggle(ep_id)
        with db.session_scope(commit=False) as session:
            assert RepositoryFactory(session).queue.is_episode_queued(ep_id) is False

    def test_favorite_toggle_flips_episode_not_series(self, db):
        series_id = _seed_series(db)
        ep_id = _seed_episode(db)
        host = _build_favorites_host(db)

        host._on_details_episode_favorite_toggle(ep_id)

        with db.session_scope(commit=False) as session:
            assert session.get(EpisodeDB, ep_id).is_favorite is True
            assert session.get(ChannelDB, series_id).is_favorite is False, (
                "must never touch the series' own favorite flag"
            )
        host.load_favorites.assert_called_once()

        host._on_details_episode_favorite_toggle(ep_id)
        with db.session_scope(commit=False) as session:
            assert session.get(EpisodeDB, ep_id).is_favorite is False


# ---------------------------------------------------------------------------
# 6. play_episode_by_id — shared chokepoint for episode-grain sidebar rows
# ---------------------------------------------------------------------------

class TestPlayEpisodeById:
    def test_resolves_and_plays(self, db):
        from metatv.gui.main_window_series import _SeriesMixin

        _seed_series(db)
        ep_id = _seed_episode(db, season_num=1, episode_num=1, title="Pilot")

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        played = []
        host.play_episode = lambda episode: played.append(episode)

        host.play_episode_by_id(ep_id)

        assert len(played) == 1
        assert played[0].id == ep_id
        assert played[0].title == "Pilot"

    def test_missing_episode_shows_status_message_and_does_not_play(self, db):
        from metatv.gui.main_window_series import _SeriesMixin

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        host.play_episode = MagicMock()

        host.play_episode_by_id("does-not-exist")

        host.play_episode.assert_not_called()
        host.status_bar.showMessage.assert_called_once()


# ---------------------------------------------------------------------------
# 7. Series-tree row context menu — Favorite/Unfavorite Episode
# ---------------------------------------------------------------------------

class TestSeriesTreeFavoriteEpisodeAction:
    def test_toggle_episode_favorite_persists_and_patches_tree_item(self, db, qapp):
        from metatv.gui.main_window_series import _SeriesMixin
        from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

        _seed_series(db)
        ep_id = _seed_episode(db, title="Face Off")
        ep = _episode_dto("Face Off", episode_id=ep_id, is_favorite=False)

        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db = db
        host.status_bar = MagicMock()
        host.load_favorites = MagicMock()

        tree = QTreeWidget()
        item = QTreeWidgetItem(tree)
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": ep})

        host._toggle_episode_favorite(item, ep)

        with db.session_scope(commit=False) as session:
            assert session.get(EpisodeDB, ep_id).is_favorite is True

        patched = item.data(0, Qt.ItemDataRole.UserRole)
        assert patched["data"].is_favorite is True, "tree UserRole DTO must be patched in place"
        assert patched["data"].id == ep_id
        host.load_favorites.assert_called_once()

    def test_make_favorite_episode_action_label_reflects_state(self, qapp):
        from metatv.gui.main_window_series import _SeriesMixin
        from PyQt6.QtWidgets import QMenu

        host = _SeriesMixin.__new__(_SeriesMixin)
        menu = QMenu()
        item = MagicMock()

        not_fav = _episode_dto("X", is_favorite=False)
        action = host._make_favorite_episode_action(menu, item, not_fav)
        assert "Favorite Episode" in action.text()
        assert "Unfavorite" not in action.text()

        fav = _episode_dto("X", is_favorite=True)
        action2 = host._make_favorite_episode_action(menu, item, fav)
        assert "Unfavorite Episode" in action2.text()


# ---------------------------------------------------------------------------
# 8. Sidebar UserRole payload shape + click routing (queue.py / favorites.py)
# ---------------------------------------------------------------------------

class TestQueueSidebarEpisodeGrain:
    def test_add_entry_item_tags_episode_grain_and_renders_code(self, qapp, db):
        from metatv.gui.sidebar.queue import WatchQueueSection
        from metatv.core.repositories.queue import QueueEntry

        section = WatchQueueSection(_make_config(), db)
        entry = QueueEntry(
            queue_id=1, channel_id="series-1", channel_name="Breaking Bad",
            media_type="series", last_played=None, channel=None,
            episode_id="ep-1", season_num=2, episode_num=4, episode_title="Face Off",
        )
        section._add_entry_item(entry)

        item = section._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "episode", "episode_id": "ep-1", "channel_id": "series-1",
        }

    def test_add_entry_item_tags_channel_grain(self, qapp, db):
        from metatv.gui.sidebar.queue import WatchQueueSection
        from metatv.core.repositories.queue import QueueEntry

        section = WatchQueueSection(_make_config(), db)
        entry = QueueEntry(
            queue_id=2, channel_id="movie-1", channel_name="Some Movie",
            media_type="movie", last_played=None, channel=None,
        )
        section._add_entry_item(entry)

        item = section._list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == {
            "grain": "channel", "channel_id": "movie-1",
        }

    def test_double_click_on_episode_row_emits_episode_activated(self, qapp, db):
        from metatv.gui.sidebar.queue import WatchQueueSection, _ROLE_AVAILABLE
        from PyQt6.QtWidgets import QListWidgetItem

        section = WatchQueueSection(_make_config(), db)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {
            "grain": "episode", "episode_id": "ep-1", "channel_id": "series-1",
        })
        item.setData(_ROLE_AVAILABLE, True)

        episode_ids, channel_ids = [], []
        section.episodeActivated.connect(lambda eid: episode_ids.append(eid))
        section.itemDoubleClicked.connect(lambda cid: channel_ids.append(cid))

        section._on_double_click(item)

        assert episode_ids == ["ep-1"]
        assert channel_ids == []

    def test_double_click_on_channel_row_emits_item_double_clicked(self, qapp, db):
        from metatv.gui.sidebar.queue import WatchQueueSection, _ROLE_AVAILABLE
        from PyQt6.QtWidgets import QListWidgetItem

        section = WatchQueueSection(_make_config(), db)
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, {"grain": "channel", "channel_id": "movie-1"})
        item.setData(_ROLE_AVAILABLE, True)

        episode_ids, channel_ids = [], []
        section.episodeActivated.connect(lambda eid: episode_ids.append(eid))
        section.itemDoubleClicked.connect(lambda cid: channel_ids.append(cid))

        section._on_double_click(item)

        assert channel_ids == ["movie-1"]
        assert episode_ids == []


class TestFavoritesSidebarEpisodeGrain:
    def test_add_episode_item_renders_code_and_tags_grain(self, qapp, db):
        from metatv.gui.sidebar.favorites import FavoritesSection, _ROLE_GRAIN

        section = FavoritesSection(_make_config(), db)
        dto = EpisodeFavoriteDTO(
            id="ep-1", title="Face Off", series_name="Breaking Bad",
            season_num=2, episode_num=4,
        )
        section._add_episode_item(dto)

        item = section.favorites_list.item(0)
        assert item.data(Qt.ItemDataRole.UserRole) == "ep-1"
        assert item.data(_ROLE_GRAIN) == "episode"

    def test_favorite_clicked_routes_episode_vs_channel(self, qapp, db):
        from metatv.gui.sidebar.favorites import FavoritesSection, _ROLE_GRAIN, _ROLE_AVAILABLE
        from PyQt6.QtWidgets import QListWidgetItem

        section = FavoritesSection(_make_config(), db)

        ep_item = QListWidgetItem()
        ep_item.setData(Qt.ItemDataRole.UserRole, "ep-1")
        ep_item.setData(_ROLE_GRAIN, "episode")
        ep_item.setData(_ROLE_AVAILABLE, True)

        episode_ids, channel_ids = [], []
        section.episodeFavoriteClicked.connect(lambda eid: episode_ids.append(eid))
        section.favoriteClicked.connect(lambda cid: channel_ids.append(cid))

        section.on_favorite_clicked(ep_item)
        assert episode_ids == ["ep-1"]
        assert channel_ids == []

        ch_item = QListWidgetItem()
        ch_item.setData(Qt.ItemDataRole.UserRole, "ch-1")
        ch_item.setData(_ROLE_AVAILABLE, True)
        section.on_favorite_clicked(ch_item)
        assert channel_ids == ["ch-1"]
        assert episode_ids == ["ep-1"], "channel-grain click must not also fire episode signal"
