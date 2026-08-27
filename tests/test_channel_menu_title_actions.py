"""Behavioral tests for the "Search this title" / "Copy title" menu actions.

Both are registry actions (``ACTIONS`` + ``SURFACE_LAYOUTS`` + ``build_channel_menu``)
— never a hand-rolled per-surface QMenu — and both resolve the title through the ONE
``ChannelMenuContext.title`` property so they can never disagree about what "this
title" is.

The title comes from the STORED ``detected_title`` (computed at ingestion), falling
back to the raw channel name.  ``parse_channel_name()`` must never be called on this
path (CLAUDE.md: name-derived fields are computed at ingestion, read at render).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from metatv.gui.channel_menu import (
    ACTIONS,
    SURFACE_LAYOUTS,
    ChannelMenuContext,
    build_channel_menu,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _ctx(**kwargs) -> ChannelMenuContext:
    defaults = {
        "channel_ids": ["ch1"],
        "surface": "channel",
        "media_type": "movie",
        "channel_name": "EN ★ The Matrix (1999) [HEVC]",
        "detected_title": "The Matrix",
        "channel_found": True,
    }
    defaults.update(kwargs)
    return ChannelMenuContext(**defaults)


def _texts(menu) -> list[str]:
    return [a.text() for a in menu.actions() if not a.isSeparator()]


def _action_by_fragment(menu, fragment: str):
    for act in menu.actions():
        if not act.isSeparator() and fragment.lower() in act.text().lower():
            return act
    return None


# ---------------------------------------------------------------------------
# Title resolution — one definition, stored field first
# ---------------------------------------------------------------------------

def test_title_prefers_the_stored_detected_title():
    ctx = _ctx()
    assert ctx.title == "The Matrix"


def test_title_falls_back_to_the_raw_name_when_undetected():
    ctx = _ctx(detected_title="")
    assert ctx.title == "EN ★ The Matrix (1999) [HEVC]"


def test_title_never_parses_the_channel_name_at_menu_time(qapp):
    """Reading the stored field is the rule — parsing at render is the bug."""
    handlers = {"search_title": lambda: None, "copy_title": lambda: None}
    with patch(
        "metatv.core.channel_name_utils.parse_channel_name",
        side_effect=AssertionError("parse_channel_name called while building the menu"),
    ):
        menu = build_channel_menu(_ctx(), handlers)
        assert _action_by_fragment(menu, "Search this title") is not None


# ---------------------------------------------------------------------------
# Registry wiring
# ---------------------------------------------------------------------------

def test_both_actions_are_registered_with_icons_and_tooltips():
    for action_id in ("search_title", "copy_title"):
        action = ACTIONS[action_id]
        assert action.icon, f"{action_id} must carry an icons.py glyph"
        assert action.tooltip, f"{action_id} must carry a tooltip"


def test_actions_use_registry_icons_from_icons_module():
    from metatv.gui import icons as _icons
    assert ACTIONS["search_title"].icon == _icons.search_icon
    assert ACTIONS["copy_title"].icon == _icons.copy_icon


@pytest.mark.parametrize(
    "surface", ["channel", "history", "favorites", "queue", "recommended", "alerts"]
)
def test_actions_listed_in_every_main_window_surface(surface):
    layout = SURFACE_LAYOUTS[surface]
    assert "search_title" in layout, f"{surface} must offer Search this title"
    assert "copy_title" in layout, f"{surface} must offer Copy title"


def test_actions_appear_in_the_built_menu(qapp):
    handlers = {"search_title": lambda: None, "copy_title": lambda: None}
    menu = build_channel_menu(_ctx(), handlers)
    texts = _texts(menu)
    assert "Search this title" in texts
    assert "Copy title" in texts


def test_actions_hidden_on_multi_select(qapp):
    """Both are single-select actions — a bulk "search 40 titles" is meaningless."""
    handlers = {"search_title": lambda: None, "copy_title": lambda: None}
    menu = build_channel_menu(_ctx(channel_ids=["a", "b", "c"]), handlers)
    texts = _texts(menu)
    assert "Search this title" not in texts
    assert "Copy title" not in texts


def test_actions_hidden_when_there_is_no_resolvable_title(qapp):
    handlers = {"search_title": lambda: None, "copy_title": lambda: None}
    menu = build_channel_menu(_ctx(detected_title="", channel_name=""), handlers)
    texts = _texts(menu)
    assert "Search this title" not in texts
    assert "Copy title" not in texts


def test_surface_without_handlers_silently_skips_them(qapp):
    """A surface opts out by not supplying a handler (registry contract)."""
    menu = build_channel_menu(_ctx(), {"play": lambda: None})
    texts = _texts(menu)
    assert "Search this title" not in texts
    assert "Copy title" not in texts


# ---------------------------------------------------------------------------
# The actions actually fire
# ---------------------------------------------------------------------------

def test_triggering_search_calls_the_handler(qapp):
    called: list[bool] = []
    handlers = {"search_title": lambda: called.append(True), "copy_title": lambda: None}
    menu = build_channel_menu(_ctx(), handlers)

    _action_by_fragment(menu, "Search this title").trigger()
    assert called == [True]


def test_triggering_copy_calls_the_handler(qapp):
    called: list[bool] = []
    handlers = {"search_title": lambda: None, "copy_title": lambda: called.append(True)}
    menu = build_channel_menu(_ctx(), handlers)

    _action_by_fragment(menu, "Copy title").trigger()
    assert called == [True]


# ---------------------------------------------------------------------------
# The MainWindow handlers do the real work
# ---------------------------------------------------------------------------

def _handler_host():
    """Minimal host exposing the real _build_handlers + _copy_title_to_clipboard."""
    from metatv.gui.main_window_channels import _ChannelListMixin

    host = SimpleNamespace()
    host.searched: list[str] = []
    host.search_for_title = lambda t: host.searched.append(t)
    host.status_bar = MagicMock()
    host.sidebar_sections = {}
    host.stream_retry_manager = MagicMock()
    host.config = MagicMock()
    host._copy_title_to_clipboard = lambda t: _ChannelListMixin._copy_title_to_clipboard(host, t)
    host._build_handlers = lambda ctx: _ChannelListMixin._build_handlers(host, ctx)
    return host


def test_search_handler_routes_through_search_for_title(qapp):
    """Reuses the existing seam (switches to the Search view + fills the box)."""
    host = _handler_host()
    handlers = host._build_handlers(_ctx())

    handlers["search_title"]()
    assert host.searched == ["The Matrix"], "must search the stored detected_title"


def test_copy_handler_puts_the_title_on_the_clipboard(qapp):
    from PyQt6.QtWidgets import QApplication

    host = _handler_host()
    handlers = host._build_handlers(_ctx())

    QApplication.clipboard().setText("something else")
    handlers["copy_title"]()
    assert QApplication.clipboard().text() == "The Matrix"


def test_copy_handler_uses_the_raw_name_when_there_is_no_detected_title(qapp):
    from PyQt6.QtWidgets import QApplication

    host = _handler_host()
    handlers = host._build_handlers(_ctx(detected_title=""))

    QApplication.clipboard().setText("something else")
    handlers["copy_title"]()
    assert QApplication.clipboard().text() == "EN ★ The Matrix (1999) [HEVC]"


def test_copy_handler_ignores_an_empty_title(qapp):
    from PyQt6.QtWidgets import QApplication

    host = _handler_host()
    QApplication.clipboard().setText("untouched")
    host._copy_title_to_clipboard("   ")
    assert QApplication.clipboard().text() == "untouched"


def test_copy_handler_confirms_in_the_status_bar(qapp):
    host = _handler_host()
    host._copy_title_to_clipboard("The Matrix")
    host.status_bar.showMessage.assert_called_once()
    assert "The Matrix" in host.status_bar.showMessage.call_args[0][0]
