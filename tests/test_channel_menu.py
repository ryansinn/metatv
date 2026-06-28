"""Behavioral tests for the unified channel context-menu registry + composer.

Covers:
- build_channel_menu action texts and order for surface "channel" single-select.
- Triggering an action invokes the bound handler.
- Toggle labels (favorite, queue, watch, hidden).
- like/dislike absent for "live" media_type; present+checkable for movie/series.
- Multi-select: core actions absent, quick-picks + bulk category present.
- Separator hygiene: no leading/trailing/doubled separators.
- clear_unavailable: disabled when has_unavailable=False; enabled when True.
- Action whose id is NOT in handlers dict is skipped (no orphan actions).
- _on_ctx_data_ready builds a menu without error and calls the right handler.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from metatv.gui.channel_menu import (
    ChannelMenuContext,
    build_channel_menu,
    SURFACE_LAYOUTS,
    ACTIONS,
)
from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _single_channel_ctx(**kwargs) -> ChannelMenuContext:
    """Return a single-channel context with sensible defaults for 'channel' surface."""
    defaults = dict(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        is_watched=False,
        has_unavailable=False,
        channel_name="Test Channel",
        user_category=None,
        entry_id="",
        channel_found=True,
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def _action_texts(menu) -> list[str]:
    """Collect action texts (skip separators which have empty text)."""
    from PyQt6.QtGui import QAction
    texts = []
    for act in menu.actions():
        if act.isSeparator():
            texts.append("---SEP---")
        else:
            texts.append(act.text())
    return texts


def _action_by_fragment(menu, fragment: str):
    """Return the first action whose text contains *fragment* (case-insensitive)."""
    for act in menu.actions():
        if not act.isSeparator() and fragment.lower() in act.text().lower():
            return act
    return None


# ---------------------------------------------------------------------------
# 1. Basic action set and order for surface "channel" single-select (movie)
# ---------------------------------------------------------------------------

def test_channel_surface_movie_contains_expected_actions(qapp):
    """channel surface with movie: Play, New Window, Fav, Queue, Like, Dislike, Watch, Track, Hide, Category."""
    called = {}
    ctx = _single_channel_ctx(media_type="movie")
    handlers = {
        "play": lambda: called.update(play=True),
        "play_new_window": lambda: called.update(new_window=True),
        "favorite": lambda: called.update(fav=True),
        "queue": lambda: called.update(queue=True),
        "like": lambda: called.update(like=True),
        "dislike": lambda: called.update(dislike=True),
        "watch": lambda: called.update(watch=True),
        "track": lambda: called.update(track=True),
        "hide": lambda: called.update(hide=True),
        "category": lambda: called.update(cat=True),
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]

    assert any("Play" == t.strip() or t.strip().startswith(_icons.play_icon) for t in non_sep), \
        f"Expected Play action, got: {non_sep}"
    assert any("New Window" in t for t in non_sep), f"Expected New Window, got: {non_sep}"
    # Favorite label — unfavorite icon prefix when is_favorite=False → "Add to Favorites"
    assert any("Favorites" in t for t in non_sep), f"Expected Favorites, got: {non_sep}"
    # Queue
    assert any("Queue" in t for t in non_sep), f"Expected Queue, got: {non_sep}"
    # Like / Dislike (media_type=movie)
    assert any("Like" in t for t in non_sep), f"Expected Like, got: {non_sep}"
    assert any("Dislike" in t for t in non_sep), f"Expected Dislike, got: {non_sep}"
    # Watch / Track / Hide (not hidden)
    assert any("watching" in t.lower() or "Watch this" in t for t in non_sep), \
        f"Expected Watch, got: {non_sep}"
    assert any("Track" in t for t in non_sep), f"Expected Track, got: {non_sep}"
    assert any("Hide" in t for t in non_sep), f"Expected Hide, got: {non_sep}"
    # Category
    assert any("Category" in t for t in non_sep), f"Expected Category, got: {non_sep}"


def test_play_new_window_action_invokes_handler(qapp):
    """Triggering 'Play in New Window' must call the bound handler exactly once."""
    tracker = {"count": 0}
    ctx = _single_channel_ctx()
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: tracker.update(count=tracker["count"] + 1),
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "New Window")
    assert act is not None, "Expected a 'New Window' action"
    act.trigger()
    assert tracker["count"] == 1


# ---------------------------------------------------------------------------
# 2. Toggle labels
# ---------------------------------------------------------------------------

def test_favorite_label_when_not_favorite(qapp):
    ctx = _single_channel_ctx(is_favorite=False)
    menu = build_channel_menu(ctx, {"favorite": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Favorites")
    assert act is not None
    assert "Add" in act.text(), f"Expected 'Add to Favorites', got {act.text()!r}"


def test_favorite_label_when_already_favorite(qapp):
    ctx = _single_channel_ctx(is_favorite=True)
    menu = build_channel_menu(ctx, {"favorite": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Favorites")
    assert act is not None
    assert "Remove" in act.text(), f"Expected 'Remove from Favorites', got {act.text()!r}"


def test_queue_label_when_not_in_queue(qapp):
    ctx = _single_channel_ctx(in_queue=False)
    menu = build_channel_menu(ctx, {"queue": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Queue")
    assert act is not None
    assert "Add" in act.text(), f"Expected 'Add to Queue', got {act.text()!r}"


def test_queue_label_when_in_queue(qapp):
    ctx = _single_channel_ctx(in_queue=True)
    menu = build_channel_menu(ctx, {"queue": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "watch": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Queue")
    assert act is not None
    assert "Remove" in act.text(), f"Expected 'Remove from Queue', got {act.text()!r}"


def test_watch_label_when_not_watched(qapp):
    ctx = _single_channel_ctx(is_watched=False)
    menu = build_channel_menu(ctx, {"watch": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Watch this")
    assert act is not None, "Expected 'Watch this channel' action when not watched"


def test_watch_label_when_watched(qapp):
    ctx = _single_channel_ctx(is_watched=True)
    menu = build_channel_menu(ctx, {"watch": lambda: None,
                                    "play": lambda: None,
                                    "play_new_window": lambda: None,
                                    "favorite": lambda: None,
                                    "queue": lambda: None,
                                    "like": lambda: None,
                                    "dislike": lambda: None,
                                    "track": lambda: None,
                                    "hide": lambda: None,
                                    "category": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Stop watching")
    assert act is not None, "Expected 'Stop watching' action when watched"


def test_hidden_channel_shows_unhide_not_watch_track_hide(qapp):
    """Hidden channel: Unhide present; Watch / Track / Hide absent."""
    ctx = _single_channel_ctx(is_hidden=True)
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "unhide": lambda: None,
        # watch, track, hide intentionally absent (won't apply anyway)
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]

    assert any("Unhide" in t for t in non_sep), f"Expected Unhide action: {non_sep}"
    assert not any("Watch this" in t for t in non_sep), "Hide channel should suppress Watch"
    assert not any("Track keyword" in t for t in non_sep), "Hidden channel should suppress Track"
    # "Hide" action itself should not appear (applies = not is_hidden)
    assert not any(t.strip() in ("🚫 Hide", "Hide") for t in non_sep), \
        f"Hide should be absent for hidden channel: {non_sep}"


# ---------------------------------------------------------------------------
# 3. Like/Dislike gating by media type
# ---------------------------------------------------------------------------

def test_like_dislike_absent_for_live_media_type(qapp):
    ctx = _single_channel_ctx(media_type="live")
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,    # handler present but action should not apply
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]
    assert not any("Like" in t for t in non_sep), f"Like should be absent for live: {non_sep}"
    assert not any("Dislike" in t for t in non_sep), f"Dislike should be absent for live: {non_sep}"


def test_like_present_and_checkable_for_movie(qapp):
    ctx = _single_channel_ctx(media_type="movie", rating=1)
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    like_act = _action_by_fragment(menu, "Like")
    assert like_act is not None, "Expected Like action for movie"
    assert like_act.isCheckable(), "Like must be checkable"
    assert like_act.isChecked(), "Like must be checked when rating==1"


def test_dislike_checked_when_rating_minus_one(qapp):
    ctx = _single_channel_ctx(media_type="series", rating=-1)
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    dislike_act = _action_by_fragment(menu, "Dislike")
    assert dislike_act is not None
    assert dislike_act.isCheckable()
    assert dislike_act.isChecked(), "Dislike must be checked when rating==-1"


def test_like_unchecked_when_rating_zero(qapp):
    ctx = _single_channel_ctx(media_type="movie", rating=0)
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    like_act = _action_by_fragment(menu, "Like")
    assert like_act is not None
    assert not like_act.isChecked(), "Like must be unchecked when rating==0"


# ---------------------------------------------------------------------------
# 4. Multi-select
# ---------------------------------------------------------------------------

def test_multi_select_hides_core_actions(qapp):
    """Multi-select: core single-select actions (play, fav, queue, like) must be absent."""
    ctx = ChannelMenuContext(
        channel_ids=["a", "b", "c"],
        surface="channel",
        channel_found=True,
    )
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "quickpick_trash": lambda: None,
        "quickpick_watch_later": lambda: None,
        "quickpick_explore": lambda: None,
        "bulk_category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]

    # Core single-select items must not appear
    assert not any("Play" == t.strip() or (t.strip().startswith(_icons.play_icon) and "New Window" not in t)
                   for t in non_sep), f"Play should be absent for multi: {non_sep}"
    assert not any("Favorites" in t for t in non_sep), f"Fav should be absent for multi: {non_sep}"
    assert not any("Queue" in t for t in non_sep), f"Queue should be absent for multi: {non_sep}"
    assert not any("Like" in t for t in non_sep), f"Like should be absent for multi: {non_sep}"


def test_multi_select_shows_quick_picks_and_bulk_category(qapp):
    """Multi-select: quick-picks (Trash/Watch Later/Explore) and bulk Category present."""
    ctx = ChannelMenuContext(
        channel_ids=["a", "b"],
        surface="channel",
        channel_found=True,
    )
    handlers = {
        "quickpick_trash": lambda: None,
        "quickpick_watch_later": lambda: None,
        "quickpick_explore": lambda: None,
        "bulk_category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]

    assert any("Trash" in t for t in non_sep), f"Expected Trash: {non_sep}"
    assert any("Watch Later" in t for t in non_sep), f"Expected Watch Later: {non_sep}"
    assert any("Explore" in t for t in non_sep), f"Expected Explore: {non_sep}"
    assert any("Category" in t for t in non_sep), f"Expected bulk Category: {non_sep}"


# ---------------------------------------------------------------------------
# 5. Separator hygiene
# ---------------------------------------------------------------------------

def test_no_leading_separator(qapp):
    """Menu must not start with a separator."""
    ctx = _single_channel_ctx(media_type="live")
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    first = menu.actions()[0] if menu.actions() else None
    assert first is not None and not first.isSeparator(), \
        "Menu must not start with a separator"


def test_no_trailing_separator(qapp):
    """Menu must not end with a separator."""
    ctx = _single_channel_ctx(media_type="live")
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    last = menu.actions()[-1] if menu.actions() else None
    assert last is not None and not last.isSeparator(), \
        "Menu must not end with a separator"


def test_no_doubled_separator(qapp):
    """Two consecutive separators must never appear in the rendered menu."""
    ctx = _single_channel_ctx(media_type="movie")
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    actions = menu.actions()
    for i in range(len(actions) - 1):
        assert not (actions[i].isSeparator() and actions[i + 1].isSeparator()), \
            f"Doubled separator at index {i}"


# ---------------------------------------------------------------------------
# 6. clear_unavailable enablement
# ---------------------------------------------------------------------------

def test_clear_unavailable_disabled_when_none_available(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["f1"],
        surface="favorites",
        has_unavailable=False,
        channel_found=True,
    )
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "clear_unavailable": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Clear Unavailable")
    assert act is not None, "clear_unavailable should always render"
    assert not act.isEnabled(), "clear_unavailable should be disabled when has_unavailable=False"


def test_clear_unavailable_enabled_when_some_available(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["f1"],
        surface="favorites",
        has_unavailable=True,
        channel_found=True,
    )
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "like": lambda: None,
        "dislike": lambda: None,
        "clear_unavailable": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Clear Unavailable")
    assert act is not None
    assert act.isEnabled(), "clear_unavailable should be enabled when has_unavailable=True"


# ---------------------------------------------------------------------------
# 7. Missing handler → action skipped
# ---------------------------------------------------------------------------

def test_missing_handler_skips_action(qapp):
    """An action id absent from handlers must not appear in the menu."""
    ctx = _single_channel_ctx(media_type="movie")
    # Deliberately omit "like" and "dislike" handlers
    handlers = {
        "play": lambda: None,
        "play_new_window": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        # "like" deliberately absent
        # "dislike" deliberately absent
        "watch": lambda: None,
        "track": lambda: None,
        "hide": lambda: None,
        "category": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _action_texts(menu)
    non_sep = [t for t in texts if t != "---SEP---"]
    assert not any("Like" in t for t in non_sep), \
        f"Like should be absent when handler not in dict: {non_sep}"
    assert not any("Dislike" in t for t in non_sep), \
        f"Dislike should be absent when handler not in dict: {non_sep}"


# ---------------------------------------------------------------------------
# 8. _on_ctx_data_ready — main-thread builder (behavioral)
# ---------------------------------------------------------------------------

class _FakeConfig:
    epg_watchlist_channels: list = []
    epg_watchlist_patterns: list = []
    save_calls: int = 0

    def save(self):
        self.save_calls += 1


class _FakeSection:
    """Minimal sidebar section stub."""
    def __init__(self, has_unavail: bool = False):
        self._has_unavail = has_unavail
        self.emit_calls = 0

    def has_unavailable(self) -> bool:
        return self._has_unavail

    class clearUnavailableClicked:
        @staticmethod
        def emit():
            pass


class _FakeStreamRetryManager:
    def remove(self, entry_id: str) -> None:
        pass

    def clear_all(self) -> None:
        pass


def _make_main_window_host(surface: str = "channel") -> object:
    """Create a minimal MainWindow-like host via __new__ for testing _on_ctx_data_ready."""
    from metatv.gui.main_window import MainWindow

    host = MainWindow.__new__(MainWindow)
    host.config = _FakeConfig()
    host.sidebar_sections = {
        "favorites": _FakeSection(has_unavail=False),
        "queue": _FakeSection(has_unavail=False),
    }
    host.stream_retry_manager = _FakeStreamRetryManager()

    # Mock all the handler methods so we can track calls
    host.play_channel_by_id = MagicMock()
    host.play_from_history_id = MagicMock()
    host.play_favorite_id = MagicMock()
    host.play_queue_item_id = MagicMock()
    host.play_channel_new_window_by_id = MagicMock()
    host._toggle_favorite_by_id = MagicMock()
    host._add_to_queue = MagicMock()
    host._remove_from_queue = MagicMock()
    host._toggle_rating = MagicMock()
    host._watch_channel_from_list = MagicMock()
    host._unwatch_channel_from_list = MagicMock()
    host._prompt_track_from_list = MagicMock()
    host._unhide_channel = MagicMock()
    host._hide_channel_from_recommendations = MagicMock()
    host._hide_channel_from_history = MagicMock()
    host._hide_channel_from_alerts = MagicMock()
    host.remove_from_history = MagicMock()
    host._not_interested = MagicMock()
    host._open_category_picker = MagicMock()
    host._quick_assign_category = MagicMock()

    return host


def test_on_ctx_data_ready_builds_menu_without_error(qapp, monkeypatch):
    """_on_ctx_data_ready builds a menu and calls exec; the built_handlers dict has 'play'."""
    from metatv.gui.main_window import MainWindow
    from PyQt6.QtWidgets import QMenu

    host = _make_main_window_host()
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="movie",
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        is_watched=False,
        has_unavailable=False,
        channel_name="Test",
        channel_found=True,
    )

    # Patch build_channel_menu to capture what is passed and return a real QMenu
    import metatv.gui.channel_menu as _cm
    captured_calls: list[dict] = []

    def _fake_build(ctx, handlers, parent=None):
        captured_calls.append({"ctx": ctx, "handlers": handlers})
        # Return a real QMenu with a dummy action so exec can be called
        m = QMenu()
        from PyQt6.QtGui import QAction
        a = QAction("dummy", m)
        m.addAction(a)
        return m

    monkeypatch.setattr(_cm, "build_channel_menu", _fake_build)
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **kw: None)

    MainWindow._on_ctx_data_ready(host, ctx, 100, 100)

    assert len(captured_calls) == 1, "build_channel_menu must be called exactly once"
    assert "play" in captured_calls[0]["handlers"], "handlers must contain 'play'"
    assert captured_calls[0]["ctx"].channel_id == "ch1"


def test_on_ctx_data_ready_play_calls_play_channel_by_id(qapp, monkeypatch):
    """_build_handlers for 'channel' surface routes 'play' to play_channel_by_id."""
    from metatv.gui.main_window import MainWindow

    host = _make_main_window_host()
    ctx = ChannelMenuContext(
        channel_ids=["ch1"],
        surface="channel",
        media_type="live",
        is_favorite=False,
        in_queue=False,
        rating=0,
        is_hidden=False,
        is_watched=False,
        has_unavailable=False,
        channel_name="Test Live",
        channel_found=True,
    )

    # Test _build_handlers directly (avoids needing a real QWidget parent)
    handlers = MainWindow._build_handlers(host, ctx)
    assert "play" in handlers, "handlers must contain 'play'"

    # Trigger the play handler and verify it calls play_channel_by_id("ch1")
    handlers["play"]()
    host.play_channel_by_id.assert_called_once_with("ch1")


# ---------------------------------------------------------------------------
# 9. Queue surface — Mark as Watched + queue-state-aware queue label
# ---------------------------------------------------------------------------

def _queue_ctx(**kwargs) -> ChannelMenuContext:
    """Single-item context on the 'queue' surface with sensible defaults."""
    defaults = dict(
        channel_ids=["q1"],
        surface="queue",
        media_type="movie",
        channel_found=True,
        channel_name="Queued Movie",
    )
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def test_queue_surface_layout_includes_mark_watched():
    """Regression: the queue SURFACE_LAYOUT must include 'mark_watched'."""
    assert "mark_watched" in SURFACE_LAYOUTS["queue"], (
        "Watch Queue items need a Mark-as-Watched action in their context menu"
    )


def test_queue_surface_movie_shows_mark_watched(qapp):
    """A queued movie's menu renders the Mark-as-Watched action wired to its handler."""
    calls = {"mark": 0}
    ctx = _queue_ctx(media_type="movie", is_vod_watched=False)
    handlers = {
        "play": lambda: None,
        "favorite": lambda: None,
        "queue": lambda: None,
        "mark_watched": lambda: calls.update(mark=calls["mark"] + 1),
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = _action_by_fragment(menu, "Mark as Watched")
    assert act is not None, "Queued movie should offer 'Mark as Watched'"
    act.trigger()
    assert calls["mark"] == 1, "Triggering mark_watched must call its handler exactly once"


def test_queue_surface_mark_watched_label_flips_when_watched(qapp):
    """When the queued item is already watched the label reads 'Mark as Unwatched'."""
    ctx = _queue_ctx(media_type="movie", is_vod_watched=True)
    menu = build_channel_menu(ctx, {"mark_watched": lambda: None}, parent=None)
    act = _action_by_fragment(menu, "Mark as")
    assert act is not None
    assert "Unwatched" in act.text(), f"Expected 'Mark as Unwatched', got {act.text()!r}"


def test_queue_surface_mark_watched_absent_for_live(qapp):
    """Live channels in the queue must not offer Mark-as-Watched (movie/series only)."""
    ctx = _queue_ctx(media_type="live")
    menu = build_channel_menu(ctx, {"play": lambda: None, "mark_watched": lambda: None}, parent=None)
    assert _action_by_fragment(menu, "Mark as Watched") is None, (
        "Mark-as-Watched should not apply to live queue items"
    )


def test_queue_surface_queue_label_flips_with_queue_state(qapp):
    """The queue action on the queue surface reflects in_queue state (Add/Remove)."""
    not_queued = build_channel_menu(
        _queue_ctx(in_queue=False), {"queue": lambda: None}, parent=None
    )
    act = _action_by_fragment(not_queued, "Queue")
    assert act is not None and "Add" in act.text(), f"Expected 'Add to Queue', got {act.text()!r}"

    queued = build_channel_menu(
        _queue_ctx(in_queue=True), {"queue": lambda: None}, parent=None
    )
    act = _action_by_fragment(queued, "Queue")
    assert act is not None and "Remove" in act.text(), f"Expected 'Remove from Queue', got {act.text()!r}"
