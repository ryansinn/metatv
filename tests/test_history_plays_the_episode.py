"""A History row plays the episode it NAMES.

A series row in History shows an ``S..E..`` on its meta line — the episode you
last watched. Double-clicking it sent the host only the channel id, so the host
re-derived a target from the series through the smart-resume ladder. That ladder
answers a different question ("what should I watch next?"), and for a COMPLETED
episode with nothing after it, it answers "nothing" — at which point the caller
opened the series browser and the double-click played nothing at all.

Owner: "double clicking a watched episode in history doesn't play the episode
(it should play on double click) it instead opens the browse the series."

The id was on the row the repository already walked; it was being dropped on the
way out. The ladder is untouched for the cases it is right for — a series with
no episode played yet, and the ">>" button, which deliberately asks for the next
one rather than the last.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest


@pytest.fixture
def db(tmp_path):
    """File-backed, not ``:memory:`` — pooled connections must share tables."""
    from metatv.core.database import Database

    database = Database(f"sqlite:///{tmp_path / 'history.db'}")
    database.create_tables()
    yield database
    database.close()


def _seed_series(db, name="Silicon Valley") -> str:
    from metatv.core.database import ChannelDB

    cid = str(uuid.uuid4())
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="series1", provider_id="p1",
            name=name, media_type="series",
            last_played=datetime.utcnow(),
        ))
    return cid


def _seed_episode(db, ep_num: int, *, played_ago_min: int | None = None,
                  completed: bool = False) -> str:
    from metatv.core.database import EpisodeDB, SeasonDB

    ep_id = f"series1_e{ep_num}"
    with db.session_scope() as session:
        if not session.get(SeasonDB, "series1_s01"):
            session.add(SeasonDB(id="series1_s01", series_id="series1",
                                 provider_id="p1", season_number=1,
                                 name="Season 1"))
        session.add(EpisodeDB(
            id=ep_id, season_id="series1_s01", series_id="series1",
            provider_id="p1", episode_id=str(ep_num),
            episode_num=ep_num, season_num=1,
            title=f"Episode {ep_num}",
            stream_url="http://example.com/ep",
            last_played=(datetime.utcnow() - timedelta(minutes=played_ago_min)
                         if played_ago_min is not None else None),
            last_played_via="manual" if played_ago_min is not None else None,
            watch_completed=completed,
        ))
    return ep_id


def _host(db):
    """The half of MainWindow this path touches, over the real mixin.

    The mixin, not a stub of it: the whole defect was in which branch that
    method takes, so a double that reimplemented the method would test the
    double.
    """
    from metatv.gui.main_window_favorites import _FavoritesMixin

    class _Host(_FavoritesMixin):
        def __init__(self, database):
            self.db = database
            self.played_ids: list[str] = []
            self.played_episodes: list[str] = []
            self.drilled: list[str] = []

        def play_episode_by_id(self, episode_id):
            self.played_ids.append(episode_id)

        def play_episode(self, ep, **_kw):
            self.played_episodes.append(ep.id)

        def drill_into_series(self, ch):
            self.drilled.append(ch.name)

        def play_media(self, ch):
            self.played_episodes.append(ch.id)

    return _Host(db)


class TestTheRepositoryHandsBackTheId:

    def test_it_returns_the_episode_id_beside_the_code(self, db):
        """It returned the code alone, and the id was on the row all along."""
        from metatv.core.repositories import RepositoryFactory

        _seed_series(db)
        ep_id = _seed_episode(db, 3, played_ago_min=10)
        with db.session_scope() as session:
            got = RepositoryFactory(session).episodes.get_last_played_for_series(
                [("series1", "p1")])
        assert got[("series1", "p1")] == (ep_id, "S01E03")

    def test_the_most_recent_play_wins(self, db):
        """Same single-row semantics the batched query replaced."""
        from metatv.core.repositories import RepositoryFactory

        _seed_series(db)
        _seed_episode(db, 1, played_ago_min=600)
        recent = _seed_episode(db, 7, played_ago_min=2)
        with db.session_scope() as session:
            got = RepositoryFactory(session).episodes.get_last_played_for_series(
                [("series1", "p1")])
        assert got[("series1", "p1")][0] == recent


class TestTheRowCarriesIt:

    def test_the_history_dto_names_the_episode_it_shows(self, db):
        from metatv.core.repositories.dtos import build_history_dtos
        from metatv.core.repositories import RepositoryFactory

        _seed_series(db)
        ep_id = _seed_episode(db, 3, played_ago_min=10)
        with db.session_scope() as session:
            dtos = build_history_dtos(RepositoryFactory(session))
        row = next(d for d in dtos if d.media_type == "series")
        assert row.episode_code == "S01E03"
        assert row.episode_id == ep_id, (
            "the row shows an episode code but cannot say which episode it is"
        )

    def test_a_non_series_row_names_no_episode(self, db):
        from metatv.core.database import ChannelDB
        from metatv.core.repositories.dtos import build_history_dtos
        from metatv.core.repositories import RepositoryFactory

        with db.session_scope() as session:
            session.add(ChannelDB(id=str(uuid.uuid4()), source_id="m1",
                                  provider_id="p1", name="Blade Runner",
                                  media_type="movie",
                                  last_played=datetime.utcnow()))
        with db.session_scope() as session:
            dtos = build_history_dtos(RepositoryFactory(session))
        row = next(d for d in dtos if d.media_type == "movie")
        assert row.episode_id is None


class TestDoubleClickPlaysIt:

    def test_a_finished_episode_with_nothing_after_it_still_plays(self, db):
        """The exact reported case.

        The ladder returns no target here — the episode is complete and there
        is no next one — so before this the double-click opened the browser.
        """
        cid = _seed_series(db)
        ep_id = _seed_episode(db, 3, played_ago_min=10, completed=True)

        host = _host(db)
        host.play_from_history_id(cid, ep_id)
        assert host.played_ids == [ep_id]
        assert not host.drilled, "it opened the series browser instead"

    def test_a_row_that_names_no_episode_still_uses_the_ladder(self, db):
        """The ladder is right for a series never started — don't break it."""
        cid = _seed_series(db)
        _seed_episode(db, 1)          # exists, never played

        host = _host(db)
        host.play_from_history_id(cid, "")
        assert host.played_ids == [], "took the episode path with no episode"

    def test_the_old_one_argument_call_still_works(self, db):
        """``main_window_channels`` calls this with the channel id alone."""
        cid = _seed_series(db)
        _seed_episode(db, 1)
        host = _host(db)
        host.play_from_history_id(cid)        # must not TypeError


def test_the_section_sends_both_the_channel_and_the_episode(qtbot, tmp_path):
    """The signal is what carries it, so the signal is what gets asserted."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem

    from metatv.core.config import Config
    from metatv.gui.sidebar.history import HistorySection, _ROLE_EPISODE_ID

    section = HistorySection(Config(config_dir=tmp_path), None)
    qtbot.addWidget(section)

    item = QListWidgetItem(section.history_list)
    item.setData(Qt.ItemDataRole.UserRole, "chan-1")
    item.setData(_ROLE_EPISODE_ID, "ep-9")

    seen = []
    section.historyItemClicked.connect(lambda c, e: seen.append((c, e)))
    section.on_history_item_clicked(item)
    assert seen == [("chan-1", "ep-9")]


def test_a_row_with_no_episode_sends_an_empty_string(qtbot, tmp_path):
    """Not None — the signal is typed ``str`` and None would not survive it."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QListWidgetItem

    from metatv.core.config import Config
    from metatv.gui.sidebar.history import HistorySection, _ROLE_EPISODE_ID

    section = HistorySection(Config(config_dir=tmp_path), None)
    qtbot.addWidget(section)
    item = QListWidgetItem(section.history_list)
    item.setData(Qt.ItemDataRole.UserRole, "chan-1")
    item.setData(_ROLE_EPISODE_ID, "")

    seen = []
    section.historyItemClicked.connect(lambda c, e: seen.append((c, e)))
    section.on_history_item_clicked(item)
    assert seen == [("chan-1", "")]
