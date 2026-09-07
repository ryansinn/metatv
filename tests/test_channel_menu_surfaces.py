"""Behavioral tests for MENU-1's four new/extended surfaces.

Every hand-rolled channel-shaped menu killed in this slice is proven here to
render the SAME action texts, in the SAME order, as the menu it replaced — a
user must see no regression from the consolidation onto the registry:

- "recommended": the "show N versions separately" mini-menu is gone; its verb
  is now the FIRST registry action.
- "alerts": the keyword-rule menu's "Clear this alert" / "View matches" pair.
- "alerts_series": the monitored-series menu (Watch Alerts sidebar's full
  four actions; the Watch Queue's Alerts-Matched copy only wires two of them
  — an id with no handler is silently skipped, which IS today's behaviour).
- "versions": the details-pane per-version chip menu's disabled header +
  play/show-details/reactivate, with the active/inactive branch order
  preserved exactly.
"""

from __future__ import annotations

import pytest

from metatv.gui import icons as _icons
from metatv.gui.channel_menu import (
    ChannelMenuContext,
    _resolve_menu_icon,
    ACTIONS,
    build_channel_menu,
)


@pytest.fixture(scope="module")
def qapp():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    yield app


def _texts(menu) -> list[str]:
    """Action texts, separators skipped — the "no regression" comparison in
    this file is against the OLD menus' verb labels, not separator placement
    (a couple of these surfaces deliberately fold two separated groups into
    one, per the brief; see the module docstring)."""
    return [a.text() for a in menu.actions() if not a.isSeparator()]


# ---------------------------------------------------------------------------
# "recommended": show_separately replaces the "show N versions separately" /
# "More options…" mini-menu
# ---------------------------------------------------------------------------

def test_show_separately_leads_the_recommended_menu(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="recommended", media_type="movie",
        channel_found=True, variant_count=3,
    )
    handlers = {"show_separately": lambda: None, "play": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts[0] == "Show 3 versions separately", texts


def test_show_separately_absent_when_no_other_versions(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="recommended", media_type="movie",
        channel_found=True, variant_count=1,
    )
    handlers = {"show_separately": lambda: None, "play": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert not any("versions separately" in t for t in texts), texts


def test_show_separately_icon_is_non_null(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="recommended", variant_count=2,
    )
    glyph, _color = _resolve_menu_icon(ACTIONS["show_separately"], ctx)
    assert glyph, "show_separately must render an icon"
    assert glyph == _icons.show_separately_icon


def test_show_separately_triggers_its_handler(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["ch1"], surface="recommended", variant_count=2,
        channel_found=True,
    )
    called = []
    handlers = {"show_separately": lambda: called.append(True)}
    menu = build_channel_menu(ctx, handlers, parent=None)
    act = next(a for a in menu.actions() if "separately" in a.text())
    act.trigger()
    assert called == [True]


# ---------------------------------------------------------------------------
# "alerts": view_matches joins the existing clear_alert
# ---------------------------------------------------------------------------

def test_alerts_rule_menu_offers_clear_then_view(qapp):
    """A keyword-rule row (config aggregate — has_unviewed_match gates
    clear_alert, no real channel behind it) — matches the pre-registry order:
    Clear this alert, then View matches."""
    ctx = ChannelMenuContext(
        channel_ids=["rule-1"], surface="alerts", channel_found=False,
        has_unviewed_match=True,
    )
    handlers = {"clear_alert": lambda: None, "view_matches": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == ["Clear alert — I've seen this", "View matches"], texts


def test_alerts_rule_menu_view_matches_only_when_no_unviewed(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["rule-1"], surface="alerts", channel_found=False,
        has_unviewed_match=False,
    )
    handlers = {"clear_alert": lambda: None, "view_matches": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == ["View matches"], texts


# ---------------------------------------------------------------------------
# "alerts_series": the monitored-series menu, two call sites
# ---------------------------------------------------------------------------

def _series_ctx(**overrides) -> ChannelMenuContext:
    defaults = {
        "channel_ids": ["s1"], "surface": "alerts_series", "media_type": "series",
        "channel_found": True, "is_series_monitored": True, "has_unviewed_match": True,
    }
    defaults.update(overrides)
    return ChannelMenuContext(**defaults)


def test_alerts_series_full_menu_matches_the_old_four_actions(qapp):
    """Watch Alerts sidebar's copy — all four ids handled."""
    ctx = _series_ctx()
    handlers = {
        "browse_series": lambda: None, "mark_seen": lambda: None,
        "monitor_series": lambda: None, "manage_alerts": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == ["Open series", "Mark seen", "Stop alerts", "Manage…"], texts


def test_alerts_series_mark_seen_hidden_when_nothing_unseen(qapp):
    ctx = _series_ctx(has_unviewed_match=False)
    handlers = {
        "browse_series": lambda: None, "mark_seen": lambda: None,
        "monitor_series": lambda: None, "manage_alerts": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == ["Open series", "Stop alerts", "Manage…"], texts


def test_alerts_series_queue_copy_only_offers_its_two_wired_actions(qapp):
    """Watch Queue's Alerts-Matched copy: no monitor_series/manage_alerts
    handler at that site — the registry skips them silently, which IS today's
    behaviour (no 'Stop alerts' / 'Manage…' there), never a regression."""
    ctx = _series_ctx()
    handlers = {"browse_series": lambda: None, "mark_seen": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == ["Open series", "Mark seen"], texts


def test_alerts_series_browse_action_triggers_handler(qapp):
    ctx = _series_ctx()
    called = []
    handlers = {"browse_series": lambda: called.append("browse"),
                "mark_seen": lambda: called.append("seen")}
    menu = build_channel_menu(ctx, handlers, parent=None)
    next(a for a in menu.actions() if a.text() == "Open series").trigger()
    assert called == ["browse"]


# ---------------------------------------------------------------------------
# "versions": details-pane per-version chip menu
# ---------------------------------------------------------------------------

def test_versions_header_renders_disabled_first_action(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["v1"], surface="versions", channel_found=True,
        header="US (Example Source)", version_prefix="US",
    )
    handlers = {"play": lambda: None, "favorite": lambda: None, "queue": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    actions = menu.actions()
    assert actions[0].text() == "US (Example Source)"
    assert not actions[0].isEnabled(), "the header action must be disabled"


def test_versions_active_source_order_matches_the_old_menu(qapp):
    """Active source: Play, Show details — reactivate_play absent."""
    ctx = ChannelMenuContext(
        channel_ids=["v1"], surface="versions", channel_found=True,
        header="US", version_prefix="US", source_inactive=False,
    )
    handlers = {
        "play": lambda: None, "reactivate_play": lambda: None,
        "show_details": lambda: None, "favorite": lambda: None, "queue": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == [
        "US", "Play US version", "Show details for US version",
        "Add to Favorites", "Add to Watch Later",
    ], texts


def test_versions_inactive_source_order_matches_the_old_menu(qapp):
    """Inactive source: Reactivate & play FIRST, then Show details — matching
    the pre-registry menu's branch order (play never shown when inactive)."""
    ctx = ChannelMenuContext(
        channel_ids=["v1"], surface="versions", channel_found=True,
        header="US", version_prefix="US", source_inactive=True,
    )
    handlers = {
        "play": lambda: None, "reactivate_play": lambda: None,
        "show_details": lambda: None, "favorite": lambda: None, "queue": lambda: None,
    }
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert texts == [
        "US", "Reactivate source & play", "Show details for US version",
        "Add to Favorites", "Add to Watch Later",
    ], texts


def test_versions_queue_label_reflects_state(qapp):
    ctx = ChannelMenuContext(
        channel_ids=["v1"], surface="versions", channel_found=True,
        in_queue=True,
    )
    handlers = {"play": lambda: None, "favorite": lambda: None, "queue": lambda: None}
    menu = build_channel_menu(ctx, handlers, parent=None)
    texts = _texts(menu)
    assert any("Remove from Watch Later" in t for t in texts), texts
