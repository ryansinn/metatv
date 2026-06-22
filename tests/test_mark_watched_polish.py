"""Behavioral tests for PR #129 follow-up + movie Mark-as-Watched feature.

Covers:
1. ChannelRepository.mark_watched sets all four fields + last_played_via="manual"
   and the change persists across a session close.
2. ChannelRepository.mark_watched(False) clears all fields correctly.
3. EpisodeRepository.mark_watched sets last_played_via="manual".
4. EpisodeRepository.mark_watched_bulk sets last_played_via="manual".
5. channel menu offers mark_watched for a movie — not for a live channel.
6. channel menu mark_watched label toggles by is_vod_watched.
7. _toggle_episodes_watched in-place DTO carries last_played_via="manual"
   so in-place icon agrees with a DB reload.
8. icons.effective_watch_pct — shared helper replaces both inline expressions.
9. icons.watch_icon FONT_LG token (no literal 12) in source.
10. icons._clear_watch_icon_cache removes all entries.
"""

from __future__ import annotations

import uuid

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _ch_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 1 & 2. ChannelRepository.mark_watched — full field set + session persistence
# ---------------------------------------------------------------------------

def test_channel_mark_watched_sets_all_fields(tmp_path):
    """mark_watched(True) sets is_watched, watch_completed, watch_percent, last_played_via.

    Uses a file-backed DB so the commit-and-reopen proves the data was actually
    persisted, not just held in memory by the same session.
    """
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ch.db'}")
    db.create_tables()

    cid = _ch_id()
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="1", provider_id="p", name="Test Movie",
            media_type="movie",
        ))

    # Mark as watched.
    with db.session_scope() as session:
        result = RepositoryFactory(session).channels.mark_watched(cid, watched=True)
    assert result is True

    # Verify in a fresh session — proves it was persisted, not just in-memory.
    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id(cid)
        assert ch.watch_completed is True
        assert ch.watch_percent == 100
        assert ch.last_played_via == "manual"
        # ChannelDB has no is_watched column (that is episode-only); the
        # "finished" flag is watch_completed.


def test_channel_mark_watched_false_clears_all_fields(tmp_path):
    """mark_watched(False) zeroes all watch fields and clears the resume point."""
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ch2.db'}")
    db.create_tables()

    cid = _ch_id()
    with db.session_scope() as session:
        session.add(ChannelDB(
            id=cid, source_id="1", provider_id="p", name="Test Movie",
            media_type="movie",
        ))

    # Pre-set watched state.
    with db.session_scope() as session:
        RepositoryFactory(session).channels.mark_watched(cid, watched=True)

    # Now unmark.
    with db.session_scope() as session:
        RepositoryFactory(session).channels.mark_watched(cid, watched=False)

    with db.session_scope(commit=False) as session:
        ch = RepositoryFactory(session).channels.get_by_id(cid)
        assert ch.watch_completed is False
        assert ch.watch_percent == 0
        assert ch.watch_progress == 0


def test_channel_mark_watched_returns_false_for_missing(tmp_path):
    """mark_watched on a nonexistent id returns False without raising."""
    from metatv.core.database import Database
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ch3.db'}")
    db.create_tables()

    with db.session_scope() as session:
        result = RepositoryFactory(session).channels.mark_watched("no-such-id", True)
    assert result is False


# ---------------------------------------------------------------------------
# 3. EpisodeRepository.mark_watched sets last_played_via="manual"
# ---------------------------------------------------------------------------

def test_episode_mark_watched_sets_last_played_via_manual(tmp_path):
    """mark_watched(True) on an episode must set last_played_via='manual'."""
    from metatv.core.database import Database, EpisodeDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ep.db'}")
    db.create_tables()

    eid = _ch_id()
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=eid,
            episode_id="ep1",
            series_id="s1",
            season_id="sn1",
            provider_id="p",
            series_name="Test Series",
            title="Episode 1",
            episode_num=1,
            season_num=1,
        ))

    with db.session_scope() as session:
        RepositoryFactory(session).episodes.mark_watched(eid, watched=True)

    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id(eid)
        assert ep.is_watched is True
        assert ep.watch_completed is True
        assert ep.watch_percent == 100
        assert ep.last_played_via == "manual"


# ---------------------------------------------------------------------------
# 4. EpisodeRepository.mark_watched_bulk sets last_played_via="manual"
# ---------------------------------------------------------------------------

def test_episode_mark_watched_bulk_sets_last_played_via_manual(tmp_path):
    """mark_watched_bulk sets last_played_via='manual' on every episode."""
    from metatv.core.database import Database, EpisodeDB
    from metatv.core.repositories import RepositoryFactory

    db = Database(f"sqlite:///{tmp_path / 'ep_bulk.db'}")
    db.create_tables()

    ids = [_ch_id() for _ in range(3)]
    with db.session_scope() as session:
        for i, eid in enumerate(ids):
            session.add(EpisodeDB(
                id=eid,
                episode_id=f"ep{i+1}",
                series_id="s1", season_id="sn1", provider_id="p",
                series_name="S", title=f"Ep {i+1}",
                episode_num=i + 1, season_num=1,
            ))

    with db.session_scope() as session:
        count = RepositoryFactory(session).episodes.mark_watched_bulk(ids, watched=True)
    assert count == 3

    with db.session_scope(commit=False) as session:
        for eid in ids:
            ep = RepositoryFactory(session).episodes.get_by_id(eid)
            assert ep.last_played_via == "manual", \
                f"Episode {eid} should have last_played_via='manual'"


# ---------------------------------------------------------------------------
# 5. Channel menu: mark_watched applies to movie/series, NOT live
# ---------------------------------------------------------------------------

def test_mark_watched_action_applies_for_movie_not_live(qapp):
    """mark_watched action must render for movies but not for live channels."""
    from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu, ACTIONS

    action_def = ACTIONS["mark_watched"]

    movie_ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="channel", media_type="movie",
        channel_found=True, is_hidden=False,
    )
    live_ctx = ChannelMenuContext(
        channel_ids=["ch2"], surface="channel", media_type="live",
        channel_found=True, is_hidden=False,
    )

    assert action_def.applies(movie_ctx) is True, "mark_watched must apply to movies"
    assert action_def.applies(live_ctx) is False, "mark_watched must NOT apply to live"


def test_mark_watched_present_in_channel_surface_layout():
    """'mark_watched' must appear in the channel SURFACE_LAYOUT."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS
    assert "mark_watched" in SURFACE_LAYOUTS["channel"], \
        "'mark_watched' missing from channel surface layout"


# ---------------------------------------------------------------------------
# 6. mark_watched label toggles on is_vod_watched
# ---------------------------------------------------------------------------

def test_mark_watched_label_when_not_watched(qapp):
    """Label is 'Mark as Watched' when is_vod_watched=False."""
    from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu

    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="channel", media_type="movie",
        channel_found=True, is_hidden=False, is_vod_watched=False,
    )
    menu = build_channel_menu(ctx, {"mark_watched": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "monitor_series": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Mark as Watched" in t for t in texts), \
        f"Expected 'Mark as Watched'; got {texts}"
    assert not any("Mark as Unwatched" in t for t in texts), \
        f"'Mark as Unwatched' should be absent; got {texts}"


def test_mark_watched_label_when_already_watched(qapp):
    """Label is 'Mark as Unwatched' when is_vod_watched=True."""
    from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu

    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="channel", media_type="movie",
        channel_found=True, is_hidden=False, is_vod_watched=True,
    )
    menu = build_channel_menu(ctx, {"mark_watched": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "monitor_series": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert any("Mark as Unwatched" in t for t in texts), \
        f"Expected 'Mark as Unwatched'; got {texts}"


# ---------------------------------------------------------------------------
# 7. _toggle_episodes_watched: in-place DTO carries last_played_via="manual"
# ---------------------------------------------------------------------------

def test_toggle_episodes_watched_dto_carries_manual_provenance(tmp_path, qapp):
    """In-place DTO from _toggle_episodes_watched has last_played_via='manual'.

    This prevents the provenance-on-toggle bug: a queue-watched episode (gray ◐)
    that the user manually toggles to watched must immediately render SOLID (✓),
    matching what a full DB reload would show — because EpisodeRepository
    also writes last_played_via='manual' on mark_watched.
    """
    from metatv.core.database import Database, EpisodeDB
    from metatv.core.repositories import RepositoryFactory
    from metatv.core.repositories.dtos import EpisodeDTO
    from metatv.gui.main_window_series import _SeriesMixin
    from PyQt6.QtWidgets import QTreeWidgetItem, QApplication
    from PyQt6.QtCore import Qt

    db = Database(f"sqlite:///{tmp_path / 'ep_toggle.db'}")
    db.create_tables()

    eid = _ch_id()
    with db.session_scope() as session:
        session.add(EpisodeDB(
            id=eid,
            episode_id="ep1",
            series_id="s1", season_id="sn1", provider_id="p",
            series_name="S", title="Ep 1",
            episode_num=1, season_num=1,
            # Simulate a queue-watched episode: last_played_via="queue"
            last_played_via="queue",
            watch_completed=False, watch_percent=50,
        ))

    # Build a minimal EpisodeDTO for the tree item.
    initial_dto = EpisodeDTO(
        id=eid, episode_num=1, season_num=1, title="Ep 1",
        series_name="S", stream_url="http://x", duration=None,
        is_watched=False, rating=None, series_id="s1",
        provider_id="p", season_id="sn1",
        watch_progress=0, watch_completed=False, watch_percent=50,
        last_played_via="queue",  # gray before toggle
    )

    # Create a real QTreeWidgetItem with the DTO in UserRole.
    ep_item = QTreeWidgetItem()
    ep_item.setData(0, Qt.ItemDataRole.UserRole, {"type": "episode", "data": initial_dto})

    # Create a minimal host via __new__ so we don't need a full MainWindow.
    from metatv.gui.main_window import MainWindow
    host = MainWindow.__new__(MainWindow)
    host.db = db
    host.config = type("C", (), {"watch_partial_threshold": 0.10})()
    # Avoid _update_season_item_icon / _find_episode_items side effects
    host._season_item_map = {}

    # We need series_tree for _update_episode_item_icon (calls setIcon/setText)
    from PyQt6.QtWidgets import QTreeWidget
    host.series_tree = QTreeWidget()

    # Call the method under test.
    _SeriesMixin._toggle_episodes_watched(host, [ep_item], watched=True)

    # The in-place DTO stored in UserRole must have last_played_via="manual".
    stored = ep_item.data(0, Qt.ItemDataRole.UserRole)
    assert stored is not None, "UserRole data should be present"
    new_dto: EpisodeDTO = stored["data"]
    assert new_dto.watch_completed is True
    assert new_dto.watch_percent == 100
    assert new_dto.last_played_via == "manual", (
        f"In-place DTO must have last_played_via='manual' after manual toggle, "
        f"got {new_dto.last_played_via!r}"
    )

    # Verify the DB also has last_played_via="manual" (repo side).
    with db.session_scope(commit=False) as session:
        ep = RepositoryFactory(session).episodes.get_by_id(eid)
        assert ep.last_played_via == "manual"


# ---------------------------------------------------------------------------
# 8. icons.effective_watch_pct — shared helper
# ---------------------------------------------------------------------------

def test_effective_watch_pct_returns_pct_when_nonzero():
    from metatv.gui.icons import effective_watch_pct
    assert effective_watch_pct(50, 0) == 50
    assert effective_watch_pct(100, 0) == 100


def test_effective_watch_pct_promotes_progress_when_pct_zero():
    """Zero percent with nonzero progress should return 1 (partial glyph shows)."""
    from metatv.gui.icons import effective_watch_pct
    assert effective_watch_pct(0, 120) == 1


def test_effective_watch_pct_zero_for_truly_unwatched():
    from metatv.gui.icons import effective_watch_pct
    assert effective_watch_pct(0, 0) == 0


# ---------------------------------------------------------------------------
# 9. icons.watch_icon uses FONT_LG token — no raw pixel literal
# ---------------------------------------------------------------------------

def test_watch_icon_uses_font_lg_token_not_literal():
    """icons.py must not contain a raw setPixelSize(12) call — use FONT_LG."""
    import inspect
    from metatv.gui import icons
    src = inspect.getsource(icons.watch_icon)
    assert "setPixelSize(12)" not in src, (
        "watch_icon must not use the hardcoded literal setPixelSize(12); "
        "use int(_theme.FONT_LG.replace('px','')) instead"
    )
    assert "FONT_LG" in src, "watch_icon must reference the FONT_LG token"


# ---------------------------------------------------------------------------
# 10. icons._clear_watch_icon_cache clears the cache dict
# ---------------------------------------------------------------------------

def test_clear_watch_icon_cache_empties_dict(qapp):
    """_clear_watch_icon_cache must discard all cached QIcon entries."""
    from metatv.gui import icons

    # Populate the cache with at least one entry.
    icons.watch_icon(icons.watched_icon, muted=False)
    assert len(icons._WATCH_ICON_CACHE) >= 1, "Cache should be non-empty after watch_icon call"

    icons._clear_watch_icon_cache()
    assert len(icons._WATCH_ICON_CACHE) == 0, "Cache must be empty after _clear_watch_icon_cache()"
