"""Behavioral tests for PR: context-menu icons (QAction.setIcon) + multi-select bulk actions.

Covers:
1. Frequent action rows (Play, Favorite, Queue, MarkWatched, Hide) have non-null QIcons.
2. Admin/rare rows (Watch, Track — no icon in registry) have null QIcons.
3. Multi-select menu includes bulk_mark_watched and other bulk actions.
4. Triggering bulk_mark_watched marks all selected channels watched (via _bulk_mark_watched).
5. icons.glyph_icon returns a non-null QIcon for a text glyph.
6. icons._clear_glyph_icon_cache empties the cache.
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


def _single_ctx(media_type: str = "movie", **kwargs):
    from metatv.gui.channel_menu import ChannelMenuContext
    defaults = dict(
        channel_ids=["ch1"],
        surface="channel",
        media_type=media_type,
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        is_watched=False,
        has_unavailable=False,
        channel_name="Test Channel",
        channel_found=True,
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def _multi_ctx(**kwargs):
    from metatv.gui.channel_menu import ChannelMenuContext
    defaults = dict(
        channel_ids=["a", "b", "c"],
        surface="channel",
        channel_found=True,
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def _all_single_handlers() -> dict:
    """Return a handler dict covering all single-select actions."""
    return {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "play_open_ended_buffer": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "mark_watched": lambda: None,
        "monitor_series": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }


def _action_by_fragment(menu, fragment: str):
    """Return the first non-separator action whose text contains fragment."""
    for act in menu.actions():
        if not act.isSeparator() and fragment.lower() in act.text().lower():
            return act
    return None


# ---------------------------------------------------------------------------
# 1 & 2. Icon column: frequent rows have icons, admin rows do not
# ---------------------------------------------------------------------------

def test_play_action_has_non_null_icon(qapp):
    """Play action must carry a QIcon (non-null) so Qt renders the icon column."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx()
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Play")
    assert act is not None, "Play action must be present"
    assert not act.icon().isNull(), "Play action icon must not be null"


def test_favorite_add_action_has_non_null_icon(qapp):
    """Add to Favorites action must carry a non-null QIcon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx(is_favorite=False)
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Favorites")
    assert act is not None, "Favorites action must be present"
    assert not act.icon().isNull(), "Favorites action icon must not be null"


def test_favorite_remove_action_has_non_null_icon(qapp):
    """Remove from Favorites action must also carry a non-null QIcon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx(is_favorite=True)
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Favorites")
    assert act is not None
    assert not act.icon().isNull(), "Remove Favorites icon must not be null"


def test_queue_action_has_non_null_icon(qapp):
    """Add/Remove Queue action must carry a non-null QIcon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx()
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Queue")
    assert act is not None, "Queue action must be present"
    assert not act.icon().isNull(), "Queue action icon must not be null"


def test_mark_watched_action_has_non_null_icon(qapp):
    """Mark as Watched action (movie surface) must carry a non-null QIcon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx(media_type="movie", is_vod_watched=False)
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Mark as Watched")
    assert act is not None, "Mark as Watched action must be present for movies"
    assert not act.icon().isNull(), "Mark as Watched icon must not be null"


def test_hide_action_has_non_null_icon(qapp):
    """Hide action must carry a non-null QIcon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx()
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Hide")
    assert act is not None, "Hide action must be present"
    assert not act.icon().isNull(), "Hide action icon must not be null"


def test_watch_epg_action_has_null_icon(qapp):
    """'Watch this channel (EPG alerts)' is an admin/rare row — icon must be null."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx(is_watched=False)
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Watch this channel")
    assert act is not None, "Watch this channel action must be present"
    assert act.icon().isNull(), "Watch EPG action must NOT have an icon (admin row)"


def test_track_keyword_action_has_null_icon(qapp):
    """'Track keyword…' is an admin row — icon must be null."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _single_ctx()
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)
    act = _action_by_fragment(menu, "Track keyword")
    assert act is not None, "Track keyword action must be present"
    assert act.icon().isNull(), "Track keyword must NOT have an icon (admin row)"


def test_action_label_text_does_not_contain_icon_glyph(qapp):
    """Icons must be set via setIcon(), not embedded as text in the label."""
    from metatv.gui.channel_menu import build_channel_menu
    from metatv.gui import icons as _icons

    ctx = _single_ctx(media_type="movie")
    menu = build_channel_menu(ctx, _all_single_handlers(), parent=None)

    play_act = _action_by_fragment(menu, "Play")
    assert play_act is not None
    # The glyph must NOT be in the label text (it lives in setIcon now)
    assert _icons.play_icon not in play_act.text(), (
        f"play_icon glyph must not appear in label text; got {play_act.text()!r}"
    )

    queue_act = _action_by_fragment(menu, "Queue")
    assert queue_act is not None
    assert _icons.queue_icon not in queue_act.text(), (
        f"queue_icon glyph must not appear in label text; got {queue_act.text()!r}"
    )


# ---------------------------------------------------------------------------
# 3. Multi-select menu includes bulk actions
# ---------------------------------------------------------------------------

def test_multi_select_includes_bulk_mark_watched(qapp):
    """Multi-select menu must include a 'Mark as Watched' bulk action."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _multi_ctx()
    handlers = {
        "play_all": lambda: None,
        "bulk_mark_watched": lambda: None,
        "bulk_favorite": lambda: None,
        "bulk_queue": lambda: None,
        "bulk_hide": lambda: None,
        "quickpick_trash": lambda: None,
        "quickpick_watch_later": lambda: None,
        "quickpick_explore": lambda: None,
        "bulk_category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Mark as Watched")
    assert act is not None, (
        "bulk_mark_watched must appear in multi-select menu; "
        f"actions: {[a.text() for a in menu.actions() if not a.isSeparator()]}"
    )


def test_multi_select_bulk_mark_watched_has_non_null_icon(qapp):
    """Bulk Mark as Watched must also carry a non-null icon."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _multi_ctx()
    handlers = {
        "bulk_mark_watched": lambda: None,
        "quickpick_trash": lambda: None,
        "quickpick_watch_later": lambda: None,
        "quickpick_explore": lambda: None,
        "bulk_category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Mark as Watched")
    assert act is not None
    assert not act.icon().isNull(), "bulk_mark_watched icon must not be null"


def test_multi_select_includes_bulk_favorite(qapp):
    """Multi-select menu must include an 'Add to Favorites' bulk action."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _multi_ctx()
    handlers = {"bulk_favorite": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Add to Favorites")
    assert act is not None, "bulk_favorite must appear in multi-select menu"


def test_multi_select_includes_bulk_queue(qapp):
    """Multi-select menu must include an 'Add to Queue' bulk action."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _multi_ctx()
    handlers = {"bulk_queue": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Add to Queue")
    assert act is not None, "bulk_queue must appear in multi-select menu"


def test_multi_select_includes_bulk_hide(qapp):
    """Multi-select menu must include a 'Hide Selected' bulk action."""
    from metatv.gui.channel_menu import build_channel_menu

    ctx = _multi_ctx()
    handlers = {"bulk_hide": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Hide Selected")
    assert act is not None, "bulk_hide must appear in multi-select menu"


def test_bulk_mark_watched_action_triggers_handler(qapp):
    """Triggering the bulk_mark_watched action must call the bound handler."""
    from metatv.gui.channel_menu import build_channel_menu

    called = {"n": 0}
    ctx = _multi_ctx()
    handlers = {"bulk_mark_watched": lambda: called.update(n=called["n"] + 1)}
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Mark as Watched")
    assert act is not None
    act.trigger()
    assert called["n"] == 1, "bulk_mark_watched handler must be called once on trigger"


# ---------------------------------------------------------------------------
# 4. DB integration: _bulk_mark_watched marks all channels watched
# ---------------------------------------------------------------------------

def test_bulk_mark_watched_persists_to_db(tmp_path):
    """_bulk_mark_watched must mark every supplied channel as watched in the DB.

    Uses a real file-backed Database (not :memory:) per project test rules.
    """
    from metatv.core.database import Database, ChannelDB
    from metatv.core.repositories import RepositoryFactory
    from metatv.gui.main_window_favorites import _FavoritesMixin

    db = Database(f"sqlite:///{tmp_path / 'bulk.db'}")
    db.create_tables()

    ids = [_ch_id() for _ in range(3)]
    with db.session_scope() as session:
        for i, cid in enumerate(ids):
            session.add(ChannelDB(
                id=cid, source_id=f"s{i}", provider_id="p",
                name=f"Movie {i}", media_type="movie",
            ))

    # Build minimal host via __new__ to avoid full MainWindow init.
    class _FakeHost(_FavoritesMixin):
        def __init__(self, database):
            self.db = database
            self._load_channels_calls = 0

        def load_channels(self):
            self._load_channels_calls += 1

    host = _FakeHost(db)
    host._bulk_mark_watched(ids)

    # Verify all channels are now marked watched in a fresh session.
    with db.session_scope(commit=False) as session:
        repos = RepositoryFactory(session)
        for cid in ids:
            ch = repos.channels.get_by_id(cid)
            assert ch is not None
            assert ch.watch_completed is True, f"Channel {cid} should be watch_completed"
            assert ch.watch_percent == 100, f"Channel {cid} should have watch_percent=100"
            assert ch.last_played_via == "manual", f"Channel {cid} should have last_played_via='manual'"

    assert host._load_channels_calls == 1, "load_channels must be called once after bulk mark"


# ---------------------------------------------------------------------------
# 5 & 6. glyph_icon helper
# ---------------------------------------------------------------------------

def test_glyph_icon_returns_non_null_icon(qapp):
    """icons.glyph_icon must return a non-null QIcon for a valid glyph."""
    from metatv.gui.icons import glyph_icon
    from PyQt6.QtGui import QIcon

    icon = glyph_icon("▶")
    assert isinstance(icon, QIcon), "glyph_icon must return a QIcon"
    assert not icon.isNull(), "glyph_icon must not return a null QIcon"


def test_glyph_icon_caches_result(qapp):
    """Calling glyph_icon twice with the same glyph must return the same object."""
    from metatv.gui.icons import glyph_icon

    icon1 = glyph_icon("★")
    icon2 = glyph_icon("★")
    assert icon1 is icon2, "glyph_icon must cache and return the same QIcon object"


def test_clear_glyph_icon_cache_empties_dict(qapp):
    """_clear_glyph_icon_cache must discard all cached QIcon entries."""
    from metatv.gui import icons

    # Populate with at least one entry.
    icons.glyph_icon("✓")
    assert len(icons._GLYPH_ICON_CACHE) >= 1, "Cache must be non-empty after glyph_icon call"

    icons._clear_glyph_icon_cache()
    assert len(icons._GLYPH_ICON_CACHE) == 0, "Cache must be empty after _clear_glyph_icon_cache()"


# ---------------------------------------------------------------------------
# 7. SURFACE_LAYOUTS: verify bulk actions present in "channel" layout
# ---------------------------------------------------------------------------

def test_bulk_actions_in_channel_surface_layout():
    """All four bulk actions must appear in the channel SURFACE_LAYOUT."""
    from metatv.gui.channel_menu import SURFACE_LAYOUTS

    layout = SURFACE_LAYOUTS["channel"]
    for action_id in ("bulk_mark_watched", "bulk_favorite", "bulk_queue", "bulk_hide"):
        assert action_id in layout, (
            f"'{action_id}' missing from channel surface layout"
        )


def test_bulk_actions_apply_only_to_multi_select():
    """Bulk action 'applies' must return True for multi and False for single."""
    from metatv.gui.channel_menu import ACTIONS, ChannelMenuContext

    multi_ctx = ChannelMenuContext(channel_ids=["a", "b"], surface="channel", channel_found=True)
    single_ctx = ChannelMenuContext(channel_ids=["a"], surface="channel", channel_found=True)

    for action_id in ("bulk_mark_watched", "bulk_favorite", "bulk_queue", "bulk_hide"):
        action = ACTIONS[action_id]
        assert action.applies(multi_ctx) is True, (
            f"'{action_id}' must apply to multi-select context"
        )
        assert action.applies(single_ctx) is False, (
            f"'{action_id}' must NOT apply to single-select context"
        )
