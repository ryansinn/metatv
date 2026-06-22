"""Behavioral tests for Multi-select Play All (#28).

Covered behaviors:

1. _play_all_items with 3 items → first plays, other 2 are queued in order via
   player_manager.queue, and _watch_tracking queue list holds all 3 content_ids.

2. _play_all_items with 1 item → plays normally, no queue registered in tracking.

3. _play_all_selected_episodes converts selected QTreeWidgetItem episode DTOs →
   _PlayAllItems in tree order, skipping items without stream_url.

4. channel_menu.py ACTIONS contains a "play_all" action that applies only to
   multi-select (is_multi) and not to single-select contexts.

5. play_all action label includes the count of selected channels.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db(tmp_path):
    from metatv.core.database import Database
    d = Database(f"sqlite:///{tmp_path / 'play_all.db'}")
    d.create_tables()
    yield d
    d.close()


def _seed_episodes(db, ep_ids: list[str]) -> None:
    """Insert minimal EpisodeDB rows."""
    from metatv.core.database import EpisodeDB
    with db.session_scope() as session:
        for i, ep_id in enumerate(ep_ids, start=1):
            session.add(EpisodeDB(
                id=ep_id,
                series_id="ser1",
                season_id="seas1",
                provider_id="p1",
                episode_id=f"ep_orig_{i}",
                season_num=1,
                episode_num=i,
                title=f"Episode {i}",
                stream_url=f"http://example.com/ep{i}.ts",
            ))


def _make_series_host(db) -> object:
    """Build a minimal _SeriesMixin host for unit tests."""
    from metatv.gui.main_window_series import _SeriesMixin
    host = _SeriesMixin.__new__(_SeriesMixin)
    host.db = db
    host.config = MagicMock(
        autoplay_season_episodes=False,
        watch_complete_threshold=0.9,
        split_streams_by_source=False,
    )
    host.player_manager = MagicMock()
    host.player_manager.resolve_key.return_value = "__shared__"
    host.status_bar = MagicMock()
    host.notification_manager = MagicMock()
    host.notification_manager.show.return_value = "notif_1"
    host.executor = MagicMock()
    host._watch_tracking = {}
    host.load_history = MagicMock()
    host.load_favorites = MagicMock()
    host.launch_player_for_episode = MagicMock()
    host._start_watch_capture = MagicMock()
    return host


def _make_play_all_item(
    url: str, title: str, content_id: str,
    provider_id: str = "p1", media_type: str = "live",
):
    from metatv.gui.main_window_series import _PlayAllItem
    return _PlayAllItem(
        stream_url=url, title=title, content_id=content_id,
        provider_id=provider_id, media_type=media_type,
    )


# ---------------------------------------------------------------------------
# 1. _play_all_items with 3 items → first plays, rest queued, tracking populated
# ---------------------------------------------------------------------------

def test_play_all_items_3_plays_first_queues_rest(db):
    """_play_all_items plays the first item and queues items 2 and 3."""
    host = _make_series_host(db)

    items = [
        _make_play_all_item("http://x.com/1.ts", "Channel 1", "c1"),
        _make_play_all_item("http://x.com/2.ts", "Channel 2", "c2"),
        _make_play_all_item("http://x.com/3.ts", "Channel 3", "c3"),
    ]

    host._play_all_items(items)

    # First item: launch_player_for_episode called with first stream_url + title
    host.launch_player_for_episode.assert_called_once()
    call_args = host.launch_player_for_episode.call_args
    assert call_args[0][0] == "http://x.com/1.ts"  # first stream_url
    assert call_args[0][1] == "Channel 1"          # first title
    queue_passed = call_args[0][2]                  # queue_episodes argument
    assert len(queue_passed) == 2, f"expected 2 queued items, got {len(queue_passed)}"
    assert queue_passed[0].stream_url == "http://x.com/2.ts"
    assert queue_passed[0].title == "Channel 2"
    assert queue_passed[1].stream_url == "http://x.com/3.ts"
    assert queue_passed[1].title == "Channel 3"


def test_play_all_items_3_populates_watch_tracking(db):
    """_watch_tracking[key] contains queue list with all 3 content_ids."""
    host = _make_series_host(db)

    items = [
        _make_play_all_item("http://x.com/1.ts", "Episode 1", "e1", media_type="episode"),
        _make_play_all_item("http://x.com/2.ts", "Episode 2", "e2", media_type="episode"),
        _make_play_all_item("http://x.com/3.ts", "Episode 3", "e3", media_type="episode"),
    ]

    host._play_all_items(items)

    tracking = host._watch_tracking
    assert "__shared__" in tracking, "tracking entry missing"
    info = tracking["__shared__"]
    assert "queue" in info, "queue list missing — multi-item should use queue branch"
    queue = info["queue"]
    assert len(queue) == 3, f"expected 3 items in queue, got {len(queue)}"
    assert queue[0]["content_id"] == "e1"
    assert queue[1]["content_id"] == "e2"
    assert queue[2]["content_id"] == "e3"
    assert info["last_seen_pos"] == 0
    assert info["played_via"] == "manual"


# ---------------------------------------------------------------------------
# 2. Single-item list: plays normally, flat tracking dict (no queue key)
# ---------------------------------------------------------------------------

def test_play_all_items_single_no_queue_in_tracking(db):
    """Single-item play_all uses flat tracking dict (same as single play_episode)."""
    host = _make_series_host(db)

    items = [_make_play_all_item("http://x.com/1.ts", "Movie A", "m1", media_type="movie")]

    host._play_all_items(items)

    info = host._watch_tracking.get("__shared__")
    assert info is not None, "tracking entry missing"
    assert "queue" not in info, "single item should not register a queue list"
    assert info["content_id"] == "m1"
    assert info["media_type"] == "movie"
    assert info["played_via"] == "manual"

    # launch_player_for_episode still called — queue_episodes arg is the empty rest list
    host.launch_player_for_episode.assert_called_once()
    call_args = host.launch_player_for_episode.call_args
    assert call_args[0][0] == "http://x.com/1.ts"
    queue_passed = call_args[0][2]
    assert len(queue_passed) == 0


def test_play_all_items_empty_list_is_noop(db):
    """Empty list does nothing — no crash, no player call."""
    host = _make_series_host(db)
    host._play_all_items([])
    host.launch_player_for_episode.assert_not_called()


def test_play_all_items_all_no_url_shows_status(db):
    """Items with no stream_url are skipped; if all skip, show status message."""
    from metatv.gui.main_window_series import _PlayAllItem
    host = _make_series_host(db)
    items = [
        _PlayAllItem(stream_url="", title="No URL", content_id="x1", provider_id="p1"),
    ]
    host._play_all_items(items)
    host.launch_player_for_episode.assert_not_called()
    host.status_bar.showMessage.assert_called()


# ---------------------------------------------------------------------------
# 3. _play_all_selected_episodes converts tree items in order, skips no-URL items
# ---------------------------------------------------------------------------

def _make_episode_dto(ep_id, ep_num, url=""):
    from metatv.core.repositories.dtos import EpisodeDTO
    return EpisodeDTO(
        id=ep_id,
        episode_num=ep_num,
        season_num=1,
        title=f"Episode {ep_num}",
        series_name="Test Series",
        stream_url=url,
        duration="0:45:00",
        is_watched=False,
        rating=None,
        series_id="ser_src_1",
        provider_id="p1",
        season_id="seas1",
        watch_progress=0,
        watch_completed=False,
    )


def _make_episode_tree_item(episode_dto) -> object:
    """Build a minimal QTreeWidgetItem-like mock with UserRole data."""
    item = MagicMock()
    item.data.return_value = {"type": "episode", "data": episode_dto}
    return item


def test_play_all_selected_episodes_calls_play_all_items_in_order(db):
    """_play_all_selected_episodes converts items in order to _PlayAllItems."""
    host = _make_series_host(db)
    host._play_all_items = MagicMock()

    from PyQt6.QtCore import Qt

    ep1 = _make_episode_dto("e1", 1, url="http://x.com/ep1.ts")
    ep2 = _make_episode_dto("e2", 2, url="http://x.com/ep2.ts")
    ep3 = _make_episode_dto("e3", 3, url="http://x.com/ep3.ts")

    # Mock QTreeWidgetItem.data to return dict with "type" and "data"
    def make_item(ep):
        item = MagicMock()
        item.data = MagicMock(return_value={"type": "episode", "data": ep})
        return item

    items = [make_item(ep1), make_item(ep2), make_item(ep3)]
    host._play_all_selected_episodes(items)

    host._play_all_items.assert_called_once()
    play_items = host._play_all_items.call_args[0][0]
    assert len(play_items) == 3
    assert play_items[0].content_id == "e1"
    assert play_items[0].stream_url == "http://x.com/ep1.ts"
    assert play_items[1].content_id == "e2"
    assert play_items[2].content_id == "e3"
    # All should be media_type="episode"
    assert all(p.media_type == "episode" for p in play_items)


def test_play_all_selected_episodes_skips_no_url(db):
    """Episodes with no stream_url are skipped by _play_all_selected_episodes."""
    host = _make_series_host(db)
    host._play_all_items = MagicMock()

    ep_no_url = _make_episode_dto("e_none", 1, url="")
    ep_ok = _make_episode_dto("e_ok", 2, url="http://x.com/ep2.ts")

    def make_item(ep):
        item = MagicMock()
        item.data = MagicMock(return_value={"type": "episode", "data": ep})
        return item

    host._play_all_selected_episodes([make_item(ep_no_url), make_item(ep_ok)])
    play_items = host._play_all_items.call_args[0][0]
    assert len(play_items) == 1
    assert play_items[0].content_id == "e_ok"


# ---------------------------------------------------------------------------
# 4. channel_menu ACTIONS "play_all" applies only to multi-select
# ---------------------------------------------------------------------------

def test_channel_menu_play_all_action_defined():
    """ACTIONS registry contains 'play_all' action."""
    from metatv.gui.channel_menu import ACTIONS
    assert "play_all" in ACTIONS, "play_all action not found in ACTIONS"


def test_channel_menu_play_all_applies_to_multi_not_single():
    """play_all applies when is_multi=True and does NOT apply when is_single=True."""
    from metatv.gui.channel_menu import ACTIONS, ChannelMenuContext
    action = ACTIONS["play_all"]

    multi_ctx = ChannelMenuContext(channel_ids=["c1", "c2", "c3"], surface="channel")
    single_ctx = ChannelMenuContext(channel_ids=["c1"], surface="channel")

    assert action.applies(multi_ctx) is True, "play_all should apply for multi-select"
    assert action.applies(single_ctx) is False, "play_all should NOT apply for single-select"


# ---------------------------------------------------------------------------
# 5. play_all label includes the count
# ---------------------------------------------------------------------------

def test_channel_menu_play_all_label_includes_count():
    """play_all label text includes the number of selected channels."""
    from metatv.gui.channel_menu import ACTIONS, ChannelMenuContext
    action = ACTIONS["play_all"]

    ctx = ChannelMenuContext(channel_ids=["c1", "c2", "c3", "c4"], surface="channel")
    label = action.label(ctx)
    assert "4" in label, f"expected count in label, got: {label!r}"


# ---------------------------------------------------------------------------
# 6. channel_menu "channel" surface layout includes play_all
# ---------------------------------------------------------------------------

def test_channel_surface_layout_includes_play_all():
    """SURFACE_LAYOUTS['channel'] includes 'play_all'."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "play_all" in SURFACE_LAYOUTS["channel"], (
        "play_all not in channel surface layout"
    )


# ---------------------------------------------------------------------------
# 7. _watch_tracking queue shape matches what _bg_capture_watch expects
# ---------------------------------------------------------------------------

def test_play_all_tracking_shape_is_queue_list_compatible(db):
    """The queue list shape from _play_all_items is the same as play_episode queued branch."""
    host = _make_series_host(db)

    items = [
        _make_play_all_item("http://x.com/1.ts", "Movie 1", "m1", media_type="movie"),
        _make_play_all_item("http://x.com/2.ts", "Movie 2", "m2", media_type="movie"),
    ]
    host._play_all_items(items)

    info = host._watch_tracking["__shared__"]
    # The _bg_capture_watch worker expects: info["queue"] is a list of {"content_id": ...}
    assert isinstance(info["queue"], list)
    for entry in info["queue"]:
        assert "content_id" in entry, "each queue entry must have content_id key"
    # last_seen_pos must be 0 (playlist-pos not yet advanced)
    assert info["last_seen_pos"] == 0
