"""EPG → My Channels: a pinned channel card must actually do something.

Owner report, 2026-08-23: "My Channels under EPG is useless. It just shows
'My Channels' but right click nor left click does anything."

It was accurate. ``_make_channel_item`` built a card with:

* no click handler — the sibling ``_make_recommendation_item`` thirty lines
  below sets ``mousePressEvent`` and ``cursor_affordance.set_clickable``; this
  one set neither, so clicking a pinned channel did nothing at all;
* no context menu — every other channel surface in the app has one;
* a Play button gated on ``prog``, i.e. on whether the GUIDE happened to know
  what was on. A pinned channel showing "No EPG data" therefore rendered a
  single ``✕`` and nothing else.

Playability and guide coverage are unrelated facts. These tests assert the
rendered widget, not that a method exists.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QPushButton, QWidget


class _FakeConfig:
    epg_watchlist_channels: list = []
    epg_watchlist_patterns: list = []
    epg_dismissed_channels: dict = {}
    epg_category_overrides: dict = {}
    epg_hidden_channels: list = []
    epg_hidden_titles: list = []
    epg_link_blocklist: list = []
    close_icon = "×"
    play_icon = "▶"
    live_indicator_icon = "🟢"
    watchlist_icon = "⏰"
    series_icon = "📺"
    move_up_icon = "▲"
    move_down_icon = "▼"


def _make_view(qapp):
    from metatv.gui.epg_view import EpgView

    view = EpgView.__new__(EpgView)
    QWidget.__init__(view)
    view.config = _FakeConfig()
    view.db = None
    view._executor = ThreadPoolExecutor(max_workers=1)
    view._provider_ids = ["p1"]
    for name in ("_channel_name_map", "_channel_quality_map", "_channel_prefix_map",
                 "_channel_title_map", "_channel_region_map", "_channel_year_map",
                 "_channel_audio_map"):
        setattr(view, name, {})
    return view


@pytest.fixture()
def card(qapp):
    """One pinned card for a channel with NO guide data — the reported case."""
    view = _make_view(qapp)
    view._channel_title_map = {"ch1": "RO| KISS TV"}
    return view, view._make_channel_item("ch1", "RO| KISS TV", None)


def _buttons(widget):
    return widget.findChildren(QPushButton)


def _left_click(widget) -> None:
    """Deliver a REAL left-press to *widget*.

    A real event, never ``mousePressEvent(None)``: on the pre-fix widget the
    handler is Qt's own C++ implementation, and handing that a ``None`` event
    SEGFAULTS the interpreter — which reads as a crash rather than as the clean
    red this test is supposed to produce against the old code.
    """
    event = QMouseEvent(
        QEvent.Type.MouseButtonPress,
        QPointF(widget.rect().center()),
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def test_the_card_selects_the_channel_when_clicked(card):
    """Left-click routes to the details pane, like every other channel row.

    PRE-FIX: ``_make_channel_item`` never assigned ``mousePressEvent``, so the
    default ``QWidget`` implementation swallowed the click.
    """
    view, widget = card
    seen = []
    view._emit_channel_selected = lambda cid: seen.append(cid)
    _left_click(widget)
    assert seen == ["ch1"], "clicking the card did not select its channel"


def test_the_card_offers_a_context_menu(card):
    """Right-click has to reach a menu. Asserted on the widget's CustomContextMenu
    policy plus a connected receiver — a policy with nothing wired to it is the
    same dead click with extra steps."""
    _view, widget = card
    assert widget.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    assert widget.receivers(widget.customContextMenuRequested) > 0, (
        "the card declares a custom context menu and connects nothing to it"
    )


def test_the_context_menu_routes_through_the_shared_epg_seam(card):
    """…and it is the SAME menu On Now uses, not a second per-surface copy.

    ``show_epg_channel_menu`` is the seam both surfaces call
    (``epg_on_now_mixin``); growing a private menu here would have been the
    third copy of that wiring.
    """
    view, widget = card
    calls = []
    view.show_epg_channel_menu = (
        lambda ids, surface, pos, **kw: calls.append((ids, surface))
    )
    widget.customContextMenuRequested.emit(widget.rect().center())
    assert calls and calls[0][0] == ["ch1"]


def test_play_is_offered_even_with_no_guide_data(card):
    """The reported symptom. A channel is playable whether or not the guide
    knows what is on it.

    PRE-FIX: the Play button was built inside ``if prog:``, so this card — the
    "No EPG data" case — had only the ✕.
    """
    view, widget = card
    labels = [b.text() for b in _buttons(widget)]
    assert any("Play" in label for label in labels), (
        f"no Play button on a card with no guide data; buttons were {labels}"
    )
    assert len(_buttons(widget)) >= 2, "the card still has only its ✕"


def test_play_button_plays_that_channel(card):
    view, widget = card
    played = []
    view._play_channel = lambda cid: played.append(cid)
    play_btn = next(b for b in _buttons(widget) if "Play" in b.text())
    play_btn.click()
    assert played == ["ch1"]


def test_remove_button_still_unwatches(card):
    """The one thing that already worked must keep working."""
    view, widget = card
    removed = []
    view._unwatch_channel = lambda cid: removed.append(cid)
    close_btn = next(b for b in _buttons(widget) if b.text() == "×")
    close_btn.click()
    assert removed == ["ch1"]


def test_every_button_carries_a_tooltip(card):
    """Project rule: icon-only and action controls need hover copy."""
    _view, widget = card
    for button in _buttons(widget):
        assert button.toolTip(), f"button {button.text()!r} has no tooltip"
