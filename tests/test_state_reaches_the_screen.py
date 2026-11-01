"""D60 — a watch/favourite/queue change reaches every surface showing it (reader half).

Census 2026-11-01 (docs/REFACTOR_PLAN.md D60) found three gaps, each fixed here:

1. Marking a film watched from the list's menu updated only the list: it never
   published, so the details pane showing that film kept its resume button and
   watched badge.
2. The details pane's episode Favourite / Queue buttons wrote the change and
   never re-read the pane, so the button kept its old state; series-tree
   changes to the shown episode never reached the pane either.
3. The series tree's row repaint re-read the watch fields only, so favouriting
   an episode from the pane left the tree's menu offering "Favorite" again.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from metatv.core.database import ChannelDB, EpisodeDB
from tests.conftest import destroy_widget
from tests.test_episode_grain_queue_favorites import _episode_dto, _fake_channel, _make_details_pane


def _visible(widget) -> bool:
    return not widget.isHidden()


def test_a_watched_change_made_elsewhere_reaches_the_poster_badge(qapp):
    from metatv.gui.details_actions import ChannelActionState
    pane = _make_details_pane(qapp)
    pane.resize(400, 700)
    pane.show()
    try:
        film = _fake_channel("movie", name="Innocent Blood")
        pane.show_channel(film)
        qapp.processEvents()
        badge = pane._poster._watched_badge
        assert not _visible(badge), "unwatched, not hovered: no badge"
        pane.apply_action_state(ChannelActionState(channel_id=film.id, media_type="movie",
                                                   watch_completed=True))
        qapp.processEvents()
        assert _visible(badge), "marked watched from the list: the badge shows it"
        pane.apply_action_state(ChannelActionState(channel_id=film.id, media_type="movie",
                                                   watch_completed=False))
        qapp.processEvents()
        assert not _visible(badge)
    finally:
        destroy_widget(pane)


def test_mark_watched_publishes_so_the_pane_re_reads():
    from metatv.gui.main_window_favorites import _FavoritesMixin
    from tests.conftest import attach_channel_state_bus

    class _Host(_FavoritesMixin):
        pass

    reread: list = []
    host = _Host()
    attach_channel_state_bus(host, reread=reread.append)
    host.channel_model = MagicMock()
    host._apply_mark_watched_ui(["a", "b"], watched=True)
    assert reread == ["a", "b"]
    host.channel_model.update_watch_completed.assert_called()


def test_the_pane_re_reads_only_the_episode_it_shows(qapp):
    pane = _make_details_pane(qapp)
    try:
        ep = _episode_dto("Pilot")
        pane.show_episode(ep, _fake_channel("series"))
        asked: list = []
        pane.episode_action_state_requested.connect(asked.append)
        pane.refresh_episode_state(["someone-else"])
        assert asked == []
        pane.refresh_episode_state(["someone-else", ep.id])
        assert asked == [ep.id]
    finally:
        destroy_widget(pane)


def _seed_episode(db, *, favourite=False) -> str:
    eid = str(uuid.uuid4())
    with db.session_scope() as s:
        s.add(ChannelDB(id="series-1", source_id="s1", provider_id="p", name="Show", media_type="series"))
        s.add(EpisodeDB(id=eid, season_id="x", series_id="s1", provider_id="p", episode_id=eid,
                        episode_num=1, season_num=1, title="Pilot", is_favorite=favourite))
    return eid


def test_favouriting_an_episode_from_the_pane_re_reads_the_pane_and_the_tree(db):
    from metatv.gui.main_window_favorites import _FavoritesMixin
    from tests.conftest import wire_episode_state_refresh, wire_status_method
    eid = _seed_episode(db)
    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.db = db
    host.status_bar = MagicMock()
    wire_status_method(host)
    host.load_favorites = MagicMock()
    told = wire_episode_state_refresh(host)
    host._on_details_episode_favorite_toggle(eid)
    assert told == [[eid]]


def test_queueing_an_episode_from_the_pane_re_reads_its_buttons(db):
    from metatv.gui.main_window_favorites import _FavoritesMixin
    from tests.conftest import wire_episode_state_refresh, wire_status_method
    eid = _seed_episode(db)
    host = _FavoritesMixin.__new__(_FavoritesMixin)
    host.db = db
    host.status_bar = MagicMock()
    wire_status_method(host)
    host.sidebar_sections = {}
    host._refresh_queue_section = MagicMock()
    told = wire_episode_state_refresh(host)
    host._on_details_episode_queue_toggle(eid)
    assert told == [[eid]]


def test_the_tree_repaint_carries_a_favourite_made_elsewhere(qapp, db):
    """The tree's row data is re-read, favourite included, so its menu is right."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

    from metatv.gui.main_window_series import _SeriesMixin
    from tests.conftest import wire_episode_state_refresh

    class _Cfg:
        watch_partial_threshold = 0.10

    eid = _seed_episode(db, favourite=False)
    tree = QTreeWidget()
    try:
        season = QTreeWidgetItem(tree)                    # episodes live under a season row
        season.setData(0, Qt.ItemDataRole.UserRole, {"type": "season"})
        item = QTreeWidgetItem(season)
        item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode",
                                                    "data": _episode_dto("Pilot", episode_id=eid)})
        host = _SeriesMixin.__new__(_SeriesMixin)
        host.db, host.config, host.series_tree = db, _Cfg(), tree
        wire_episode_state_refresh(host)
        with db.session_scope() as s:                     # favourited from the pane
            s.get(EpisodeDB, eid).is_favorite = True
        host.refresh_episode_watch_state([eid])
        assert item.data(0, Qt.ItemDataRole.UserRole)["data"].is_favorite is True
    finally:
        destroy_widget(tree)
