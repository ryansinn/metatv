"""Behavioral tests for EPG view context-menu migration onto the unified registry.

Covers:
- build_channel_menu with surface="epg_on_now", single-id context → core + EPG extras present.
- Same surface, multi-id context → core actions absent, bulk EPG extras present with plural labels.
- epg_unwatch / epg_remove_override absent when omitted from handlers dict.
- EpgView._on_now_context_menu builds a menu without error; triggering "Play" calls host method.
- EpgView._on_now_context_menu triggering EPG extras calls the right EpgView methods.
- EpgView._on_browse_context_menu builds a menu without error; verifies Play and Track actions.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.gui.channel_menu import (
    ChannelMenuContext,
    build_channel_menu,
    SURFACE_LAYOUTS,
    ACTIONS,
)
from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _action_texts(menu) -> list[str]:
    texts = []
    for act in menu.actions():
        if act.isSeparator():
            texts.append("---SEP---")
        else:
            texts.append(act.text())
    return texts


def _non_sep(menu) -> list[str]:
    return [t for t in _action_texts(menu) if t != "---SEP---"]


def _action_by_fragment(menu, fragment: str):
    for act in menu.actions():
        if not act.isSeparator() and fragment.lower() in act.text().lower():
            return act
    return None


def _epg_on_now_single_ctx(**kwargs) -> ChannelMenuContext:
    defaults = dict(
        channel_ids=["ch1"],
        surface="epg_on_now",
        media_type="movie",
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        channel_name="Test Channel",
        channel_found=True,
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def _all_epg_on_now_handlers() -> dict:
    """Return a full handlers dict for epg_on_now with all possible EPG actions."""
    return {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "epg_watch": lambda: None,
        "epg_unwatch": lambda: None,
        "epg_track_show": lambda: None,
        "epg_assign_category": lambda: None,
        "epg_remove_override": lambda: None,
        "epg_hide_channel": lambda: None,
        "epg_hide_show": lambda: None,
    }


# ---------------------------------------------------------------------------
# 1. epg_on_now single-select: core + EPG extras all present
# ---------------------------------------------------------------------------

def test_epg_on_now_single_core_actions_present(qapp):
    """Single-id epg_on_now: Play, New Window, Favorite, Queue, Like, Dislike present."""
    ctx = _epg_on_now_single_ctx(media_type="movie")
    menu = build_channel_menu(ctx, _all_epg_on_now_handlers(), parent=None)
    texts = _non_sep(menu)

    assert any("Play" in t and "New Window" not in t for t in texts), \
        f"Expected Play: {texts}"
    assert any("New Window" in t for t in texts), f"Expected New Window: {texts}"
    assert any("Favorites" in t for t in texts), f"Expected Favorites: {texts}"
    assert any("Queue" in t for t in texts), f"Expected Queue: {texts}"
    assert any("Like" in t for t in texts), f"Expected Like (movie): {texts}"
    assert any("Dislike" in t for t in texts), f"Expected Dislike (movie): {texts}"


def test_epg_on_now_single_epg_extras_present(qapp):
    """Single-id epg_on_now: EPG-extra actions are all present when handlers provided."""
    ctx = _epg_on_now_single_ctx(media_type="live")
    menu = build_channel_menu(ctx, _all_epg_on_now_handlers(), parent=None)
    texts = _non_sep(menu)

    assert any("Watch this channel" in t for t in texts), f"Expected epg_watch: {texts}"
    assert any("Stop watching" in t for t in texts), f"Expected epg_unwatch: {texts}"
    assert any("Track show" in t for t in texts), f"Expected epg_track_show: {texts}"
    assert any("Assign category" in t for t in texts), f"Expected epg_assign_category: {texts}"
    assert any("Remove category override" in t for t in texts), \
        f"Expected epg_remove_override: {texts}"
    assert any("Hide channel" in t for t in texts), f"Expected epg_hide_channel: {texts}"
    assert any("Hide show" in t for t in texts), f"Expected epg_hide_show: {texts}"


def test_epg_on_now_single_order_core_before_epg_extras(qapp):
    """Core actions (Play) must appear before EPG extras (epg_watch) in the layout."""
    ctx = _epg_on_now_single_ctx(media_type="live")
    menu = build_channel_menu(ctx, _all_epg_on_now_handlers(), parent=None)
    texts = _non_sep(menu)

    play_idx = next(
        (i for i, t in enumerate(texts) if "Play" in t and "New Window" not in t), None
    )
    watch_idx = next((i for i, t in enumerate(texts) if "Watch this channel" in t), None)
    assert play_idx is not None, f"Play not found: {texts}"
    assert watch_idx is not None, f"epg_watch not found: {texts}"
    assert play_idx < watch_idx, \
        f"Play (idx={play_idx}) must come before epg_watch (idx={watch_idx}): {texts}"


# ---------------------------------------------------------------------------
# 2. epg_on_now multi-select: core absent, bulk EPG extras present with plural labels
# ---------------------------------------------------------------------------

def test_epg_on_now_multi_core_actions_absent(qapp):
    """Multi-id epg_on_now: core single-select actions must be absent."""
    ctx = ChannelMenuContext(
        channel_ids=["a", "b"],
        surface="epg_on_now",
        channel_found=True,
    )
    # Provide core handlers — applies=is_single so they won't render
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "epg_assign_category": lambda: None,
        "epg_hide_channel": lambda: None,
        "epg_hide_show": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _non_sep(menu)

    assert not any(
        t.strip() == "Play"
        or (t.strip().startswith(_icons.play_icon) and "New Window" not in t)
        for t in texts
    ), f"Play should be absent for multi: {texts}"
    assert not any("Favorites" in t for t in texts), f"Fav should be absent for multi: {texts}"
    assert not any("Queue" in t for t in texts), f"Queue should be absent for multi: {texts}"
    assert not any("Like" in t for t in texts), f"Like should be absent for multi: {texts}"


def test_epg_on_now_multi_epg_extras_present(qapp):
    """Multi-id epg_on_now: EPG bulk extras are rendered for multi selection."""
    ctx = ChannelMenuContext(
        channel_ids=["a", "b", "c"],
        surface="epg_on_now",
        channel_found=True,
    )
    handlers = {
        "epg_watch": lambda: None,
        "epg_track_show": lambda: None,
        "epg_assign_category": lambda: None,
        "epg_hide_channel": lambda: None,
        "epg_hide_show": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _non_sep(menu)

    assert any("Watch channels" in t for t in texts), f"Expected plural epg_watch: {texts}"
    assert any("Track shows" in t for t in texts), f"Expected plural epg_track_show: {texts}"
    assert any("Assign category" in t for t in texts), f"Expected epg_assign_category: {texts}"
    assert any("Hide channels" in t for t in texts), f"Expected plural epg_hide_channel: {texts}"
    assert any("Hide shows" in t for t in texts), f"Expected plural epg_hide_show: {texts}"


# ---------------------------------------------------------------------------
# 3. Absent handlers → absent actions (composer skips ids not in handlers)
# ---------------------------------------------------------------------------

def test_epg_unwatch_absent_when_not_in_handlers(qapp):
    """epg_unwatch must not appear when omitted from handlers dict."""
    ctx = _epg_on_now_single_ctx()
    handlers = {k: v for k, v in _all_epg_on_now_handlers().items() if k != "epg_unwatch"}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _non_sep(menu)
    assert not any("Stop watching" in t for t in texts), \
        f"epg_unwatch should be absent when not in handlers: {texts}"


def test_epg_remove_override_absent_when_not_in_handlers(qapp):
    """epg_remove_override must not appear when omitted from handlers dict."""
    ctx = _epg_on_now_single_ctx()
    handlers = {k: v for k, v in _all_epg_on_now_handlers().items() if k != "epg_remove_override"}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _non_sep(menu)
    assert not any("Remove category" in t for t in texts), \
        f"epg_remove_override should be absent when not in handlers: {texts}"


# ---------------------------------------------------------------------------
# 4. epg_browse surface
# ---------------------------------------------------------------------------

def test_epg_browse_single_actions_present(qapp):
    """epg_browse: Play, New Window, Fav, Queue present for single; epg_watch + epg_track_show."""
    ctx = _epg_on_now_single_ctx(surface="epg_browse", media_type="live")
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "epg_watch": lambda: None,
        "epg_track_show": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _non_sep(menu)

    assert any("Play" in t and "New Window" not in t for t in texts), f"Play expected: {texts}"
    assert any("New Window" in t for t in texts), f"New Window expected: {texts}"
    assert any("Favorites" in t for t in texts), f"Favorites expected: {texts}"
    assert any("Queue" in t for t in texts), f"Queue expected: {texts}"
    assert any("Watch this channel" in t for t in texts), f"epg_watch expected: {texts}"
    assert any("Track show" in t for t in texts), f"epg_track_show expected: {texts}"


def test_epg_browse_no_assign_category_or_hide(qapp):
    """epg_browse layout does not include assign_category or hide actions."""
    assert "epg_assign_category" not in SURFACE_LAYOUTS["epg_browse"]
    assert "epg_hide_channel" not in SURFACE_LAYOUTS["epg_browse"]
    assert "epg_hide_show" not in SURFACE_LAYOUTS["epg_browse"]


# ---------------------------------------------------------------------------
# 5 & 6. EpgView._on_now_context_menu and _on_browse_context_menu behavioral drive
#
# The EpgView is constructed via __new__ (not __init__), so it has no Qt widget
# hierarchy.  We patch build_channel_menu to avoid calling QMenu(parent=self)
# with an uninitialized widget.  The spy intercepts (ctx, handlers) before
# returning a bare QMenu() so we can assert on what the view built.
# ---------------------------------------------------------------------------

class _FakeConfig:
    epg_watchlist_channels: list = []
    epg_category_overrides: dict = {}
    epg_hidden_channels: list = []
    epg_hidden_titles: list = []
    epg_watchlist_patterns: list = []

    def save(self):
        pass


class _FakeChannel:
    def __init__(self, cid: str = "ch1"):
        self.id = cid
        self.name = "Test Ch"
        self.media_type = "movie"
        self.is_favorite = False
        self.is_hidden = False


class _FakeRepos:
    def __init__(self, channel):
        self.channels = SimpleNamespace(get_by_id=lambda _: channel)
        self.queue = SimpleNamespace(is_queued=lambda _: False)
        self.ratings = SimpleNamespace(get=lambda _: 0)


class _FakeDB:
    """Minimal db stub whose session_scope() yields itself as the session."""

    def __init__(self, channel):
        self._channel = channel

    def session_scope(self, commit=True):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def get_session(self):
        return self

    def query(self, *_):
        return self

    def filter_by(self, **_):
        return self

    def first(self):
        return self._channel


def _make_epg_view(channel=None, config=None):
    """Construct EpgView via __new__ with fakes injected; avoids real Qt setup."""
    from metatv.gui.epg_view import EpgView

    view = EpgView.__new__(EpgView)
    view.config = config or _FakeConfig()
    view.db = _FakeDB(channel or _FakeChannel())
    return view


def _make_fake_item(ch_id: str, show_title: str = "My Show") -> object:
    """Minimal fake QTreeWidgetItem for on_now_list."""
    item = MagicMock()
    item.data.side_effect = lambda col, role: ch_id if col == 0 else None
    item.text.side_effect = lambda col: show_title if col == 3 else ""
    return item


def _make_fake_browse_item(ch_id: str, show_title: str = "Browse Show") -> object:
    """Minimal fake QTreeWidgetItem for browse_list."""
    item = MagicMock()
    item.data.side_effect = lambda col, role: ch_id if col == 0 else None
    item.text.side_effect = lambda col: show_title if col == 2 else ""
    return item


def _spy_build_factory():
    """Return (spy_fn, captured_list) where spy_fn replaces build_channel_menu."""
    from PyQt6.QtWidgets import QMenu

    captured: list[dict] = []

    def _spy(ctx, handlers, parent=None):
        captured.append({"ctx": ctx, "handlers": handlers})
        return QMenu()  # bare QMenu, no uninitialized parent

    return _spy, captured


def test_on_now_context_menu_builds_without_error(qapp, monkeypatch):
    """_on_now_context_menu must call build_channel_menu with surface='epg_on_now'."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_now_context_menu(MagicMock())

    assert len(captured) == 1, "build_channel_menu should be called once"
    assert captured[0]["ctx"].surface == "epg_on_now"
    assert "play" in captured[0]["handlers"]


def test_on_now_context_menu_play_calls_host(qapp, monkeypatch):
    """Triggering the play handler must call host.play_channel_by_id('ch1')."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    fake_host = MagicMock()
    view._host = lambda: fake_host

    view._on_now_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "play" in handlers, f"play handler must be present: {list(handlers)}"
    handlers["play"]()
    fake_host.play_channel_by_id.assert_called_once_with("ch1")


def test_on_now_context_menu_epg_assign_category_calls_method(qapp, monkeypatch):
    """Triggering epg_assign_category must call _bulk_assign_category with the items."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)
    view._bulk_assign_category = MagicMock()

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_now_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_assign_category" in handlers, \
        f"epg_assign_category must be in handlers: {list(handlers)}"
    handlers["epg_assign_category"]()
    view._bulk_assign_category.assert_called_once()


def test_on_now_context_menu_epg_hide_show_calls_method(qapp, monkeypatch):
    """Triggering epg_hide_show must call _bulk_hide_titles with the items."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)
    view._bulk_hide_titles = MagicMock()

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_now_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_hide_show" in handlers, \
        f"epg_hide_show must be in handlers: {list(handlers)}"
    handlers["epg_hide_show"]()
    view._bulk_hide_titles.assert_called_once()


def test_on_now_context_menu_epg_unwatch_absent_when_no_watched(qapp, monkeypatch):
    """epg_unwatch handler absent when no selected channels are in watchlist."""
    channel = _FakeChannel()
    config = _FakeConfig()
    config.epg_watchlist_channels = []  # ch1 not watched → no unwatch handler
    view = _make_epg_view(channel=channel, config=config)

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_now_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_unwatch" not in handlers, \
        f"epg_unwatch should be absent when channel not in watchlist: {list(handlers)}"


def test_on_now_context_menu_epg_remove_override_absent_when_no_override(qapp, monkeypatch):
    """epg_remove_override handler absent when no selected channels have category overrides."""
    channel = _FakeChannel()
    config = _FakeConfig()
    config.epg_category_overrides = {}  # no overrides
    view = _make_epg_view(channel=channel, config=config)

    item = _make_fake_item("ch1")
    fake_list = MagicMock()
    fake_list.selectedItems.return_value = [item]
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.on_now_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_now_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_remove_override" not in handlers, \
        f"epg_remove_override should be absent when no overrides: {list(handlers)}"


def test_on_browse_context_menu_builds_without_error(qapp, monkeypatch):
    """_on_browse_context_menu must call build_channel_menu with surface='epg_browse'."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)

    item = _make_fake_browse_item("ch1")
    fake_list = MagicMock()
    fake_list.itemAt.return_value = item
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.browse_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_browse_context_menu(MagicMock())

    assert len(captured) == 1
    assert captured[0]["ctx"].surface == "epg_browse"


def test_on_browse_context_menu_play_calls_host(qapp, monkeypatch):
    """Triggering Play in _on_browse_context_menu calls host.play_channel_by_id."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)

    item = _make_fake_browse_item("ch1")
    fake_list = MagicMock()
    fake_list.itemAt.return_value = item
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.browse_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    fake_host = MagicMock()
    view._host = lambda: fake_host

    view._on_browse_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "play" in handlers, f"play handler expected: {list(handlers)}"
    handlers["play"]()
    fake_host.play_channel_by_id.assert_called_once_with("ch1")


def test_on_browse_context_menu_track_show_calls_prompt_track(qapp, monkeypatch):
    """Triggering epg_track_show in browse must call _prompt_track with the title."""
    channel = _FakeChannel()
    view = _make_epg_view(channel=channel)
    view._prompt_track = MagicMock()

    item = _make_fake_browse_item("ch1", show_title="The Grand Show")
    fake_list = MagicMock()
    fake_list.itemAt.return_value = item
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.browse_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_browse_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_track_show" in handlers, f"epg_track_show expected: {list(handlers)}"
    handlers["epg_track_show"]()
    view._prompt_track.assert_called_once_with("The Grand Show")


def test_on_browse_context_menu_watch_absent_when_already_watched(qapp, monkeypatch):
    """epg_watch handler absent when channel already in watchlist."""
    channel = _FakeChannel()
    config = _FakeConfig()
    config.epg_watchlist_channels = ["ch1"]  # already watched
    view = _make_epg_view(channel=channel, config=config)

    item = _make_fake_browse_item("ch1")
    fake_list = MagicMock()
    fake_list.itemAt.return_value = item
    fake_list.viewport.return_value.mapToGlobal.return_value = MagicMock()
    view.browse_list = fake_list

    monkeypatch.setattr(
        "metatv.core.repositories.RepositoryFactory",
        lambda session: _FakeRepos(channel),
    )
    spy, captured = _spy_build_factory()
    monkeypatch.setattr("metatv.gui.epg_view.build_channel_menu", spy)

    from PyQt6.QtWidgets import QMenu
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    view._host = lambda: MagicMock()
    view._on_browse_context_menu(MagicMock())

    handlers = captured[0]["handlers"]
    assert "epg_watch" not in handlers, \
        f"epg_watch should be absent when already in watchlist: {list(handlers)}"
