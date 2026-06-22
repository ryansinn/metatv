"""Unified channel context-menu registry and composer for MetaTV.

All channel context menus in the MainWindow family are built through
``build_channel_menu``.  A registry of ``ChannelAction`` objects plus
per-surface ``SURFACE_LAYOUTS`` define what actions appear and in what order.
The composer handles separator hygiene (no leading / trailing / doubled seps).

Usage::

    from metatv.gui.channel_menu import ChannelMenuContext, build_channel_menu

    ctx = ChannelMenuContext(
        channel_ids=[channel_id],
        surface="channel",
        media_type=channel.media_type,
        is_favorite=channel.is_favorite,
        ...
    )
    handlers = {"play": lambda: play_channel_by_id(cid), ...}
    menu = build_channel_menu(ctx, handlers, parent=self)
    menu.exec(QPoint(gx, gy))
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QMenu

from metatv.gui import icons as _icons


# ---------------------------------------------------------------------------
# Context dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChannelMenuContext:
    """All state needed to build a channel context menu.

    Populated in two passes:
    * DB pass (off-thread): channel fields, queue/rating DB lookups.
    * Main-thread pass: config-derived fields (is_watched, has_unavailable).
    """

    channel_ids: list[str]
    surface: str  # "channel"|"history"|"favorites"|"queue"|"recommended"|"alerts"|"retry"
    media_type: str = ""
    is_favorite: bool = False
    in_queue: bool = False
    rating: int = 0
    is_hidden: bool = False
    is_watched: bool = False          # channel_id in config.epg_watchlist_channels
    is_vod_watched: bool = False      # channel.watch_completed (VOD manual-watched state)
    is_series_monitored: bool = False  # channel_id in config.monitored_series
    has_unavailable: bool = False     # favorites/queue Clear-Unavailable enablement
    channel_name: str = ""
    user_category: str | None = None
    entry_id: str = ""                # retry surface: identifies the StreamRetryEntry
    channel_found: bool = True        # retry surface: False when lookup returned None

    @property
    def is_single(self) -> bool:
        return len(self.channel_ids) == 1

    @property
    def is_multi(self) -> bool:
        return len(self.channel_ids) > 1

    @property
    def channel_id(self) -> str | None:
        return self.channel_ids[0] if self.channel_ids else None


# ---------------------------------------------------------------------------
# Action dataclass
# ---------------------------------------------------------------------------

@dataclass
class ChannelAction:
    """Definition of one context-menu action."""

    id: str
    label: Callable[[ChannelMenuContext], str]
    icon: str = ""                                         # icons.py value or ""
    tooltip: str = ""
    checkable: bool = False
    checked: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: False)
    )
    applies: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: True)
    )
    enabled: Callable[[ChannelMenuContext], bool] = field(
        default_factory=lambda: (lambda c: True)
    )
    disabled_tooltip: str = ""


# ---------------------------------------------------------------------------
# Action registry
# ---------------------------------------------------------------------------

def _fav_label(c: ChannelMenuContext) -> str:
    return "Remove from Favorites" if c.is_favorite else "Add to Favorites"


def _fav_icon(c: ChannelMenuContext) -> str:
    return _icons.unfavorite_icon if c.is_favorite else _icons.favorite_icon


def _queue_label(c: ChannelMenuContext) -> str:
    return "Remove from Queue" if c.in_queue else "Add to Queue"


def _watch_label(c: ChannelMenuContext) -> str:
    return "Stop watching this channel" if c.is_watched else "Watch this channel (EPG alerts)"


def _monitor_label(c: ChannelMenuContext) -> str:
    return "Stop new-episode alerts" if c.is_series_monitored else "Alert me to new episodes"


def _mark_watched_label(c: ChannelMenuContext) -> str:
    return "Mark as Unwatched" if c.is_vod_watched else "Mark as Watched"


def _category_label(c: ChannelMenuContext) -> str:
    if c.user_category:
        return f"Category: {c.user_category}  (change…)"
    return "Add to Category…"


def _bulk_category_label(c: ChannelMenuContext) -> str:
    n = len(c.channel_ids)
    s = "s" if n != 1 else ""
    return f"Add {n:,} selected channel{s} to Category…"


ACTIONS: dict[str, ChannelAction] = {
    # ── Core ────────────────────────────────────────────────────────────────
    "play": ChannelAction(
        id="play",
        label=lambda c: "Play",
        icon=_icons.play_icon,
        tooltip="Play this channel",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "play_new_window": ChannelAction(
        id="play_new_window",
        label=lambda c: "Play in New Window",
        icon=_icons.new_window_icon,
        tooltip="Open in a separate player window (per-source)",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "favorite": ChannelAction(
        id="favorite",
        label=_fav_label,
        icon="",   # icon chosen dynamically in builder (fav_icon / unfavorite_icon)
        tooltip="Toggle this channel in your Favorites sidebar",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "queue": ChannelAction(
        id="queue",
        label=_queue_label,
        icon=_icons.queue_icon,
        tooltip="Toggle this channel in your Watch Queue",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    "like": ChannelAction(
        id="like",
        label=lambda c: "Like",
        icon=_icons.like_icon,
        tooltip="Rate this title positively",
        checkable=True,
        checked=lambda c: c.rating == 1,
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    "dislike": ChannelAction(
        id="dislike",
        label=lambda c: "Dislike",
        icon=_icons.dislike_icon,
        tooltip="Rate this title negatively",
        checkable=True,
        checked=lambda c: c.rating == -1,
        applies=lambda c: c.is_single and c.channel_found and c.media_type in ("movie", "series"),
    ),
    # ── Series monitor ──────────────────────────────────────────────────────
    "monitor_series": ChannelAction(
        id="monitor_series",
        label=_monitor_label,
        icon=_icons.alert_icon,
        tooltip="Alert me when this series has new episodes",
        applies=lambda c: (
            c.is_single and c.channel_found
            and not c.is_hidden
            and c.media_type == "series"
        ),
    ),
    # ── VOD mark watched ────────────────────────────────────────────────────
    "mark_watched": ChannelAction(
        id="mark_watched",
        label=_mark_watched_label,
        icon=_icons.watched_icon,
        tooltip="Mark this movie or series as watched / unwatched",
        applies=lambda c: (
            c.is_single and c.channel_found
            and not c.is_hidden
            and c.media_type in ("movie", "series")
        ),
    ),
    # ── Channel extras ──────────────────────────────────────────────────────
    "watch": ChannelAction(
        id="watch",
        label=_watch_label,
        icon="",
        tooltip="Toggle EPG watchlist alerts for this channel",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "track": ChannelAction(
        id="track",
        label=lambda c: "Track keyword…",
        icon="",
        tooltip="Add a keyword pattern to your EPG watchlist",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "unhide": ChannelAction(
        id="unhide",
        label=lambda c: "Unhide",
        icon=_icons.hide_icon,
        tooltip="Un-hide this channel so it appears in the channel list",
        applies=lambda c: c.is_single and c.channel_found and c.is_hidden,
    ),
    "hide": ChannelAction(
        id="hide",
        label=lambda c: "Hide",
        icon=_icons.hide_icon,
        tooltip="Hide this channel from the channel list",
        applies=lambda c: c.is_single and c.channel_found and not c.is_hidden,
    ),
    "category": ChannelAction(
        id="category",
        label=_category_label,
        icon=_icons.queue_icon,
        tooltip=(
            "Assign this channel to a user-defined category.\n"
            "Categories appear as shelves in the Discover view."
        ),
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── History extras ──────────────────────────────────────────────────────
    "remove_history": ChannelAction(
        id="remove_history",
        label=lambda c: "Remove from History",
        icon=_icons.delete_icon,
        tooltip="Remove this entry from your playback history",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── Favorites extras ────────────────────────────────────────────────────
    "clear_unavailable": ChannelAction(
        id="clear_unavailable",
        label=lambda c: "Clear Unavailable",
        icon="",
        tooltip="Remove all unavailable items",
        applies=lambda c: True,  # always shown; disabled when none
        enabled=lambda c: c.has_unavailable,
        disabled_tooltip="No unavailable content",
    ),
    # ── Recommended extras ──────────────────────────────────────────────────
    "not_interested": ChannelAction(
        id="not_interested",
        label=lambda c: "Not Interested",
        icon=_icons.not_interested_icon,
        tooltip="Suppress this title from recommendations",
        applies=lambda c: c.is_single and c.channel_found,
    ),
    # ── Retry extras ────────────────────────────────────────────────────────
    "remove_retry": ChannelAction(
        id="remove_retry",
        label=lambda c: "Remove from Stream Monitoring",
        icon=_icons.close_icon,
        tooltip="Stop monitoring this stream for reconnection",
        applies=lambda c: True,
    ),
    "clear_retry": ChannelAction(
        id="clear_retry",
        label=lambda c: "Clear all from Stream Monitoring",
        icon="",
        tooltip="Remove all entries from the Stream Monitoring list",
        applies=lambda c: True,
    ),
    # ── EPG extras ──────────────────────────────────────────────────────────
    "epg_watch": ChannelAction(
        id="epg_watch",
        label=lambda c: (
            "Watch this channel (EPG alerts)" if c.is_single
            else "Watch channels…"
        ),
        icon=_icons.watchlist_on_icon,
        tooltip="Add this channel to your EPG watchlist for alerts",
        applies=lambda c: True,
    ),
    "epg_unwatch": ChannelAction(
        id="epg_unwatch",
        label=lambda c: (
            "Stop watching this channel" if c.is_single
            else "Unwatch channels…"
        ),
        icon=_icons.watchlist_off_icon,
        tooltip="Remove this channel from your EPG watchlist",
        applies=lambda c: True,
    ),
    "epg_track_show": ChannelAction(
        id="epg_track_show",
        label=lambda c: "Track show…" if c.is_single else "Track shows…",
        icon=_icons.watchlist_icon,
        tooltip="Add the current show title as a watchlist pattern",
        applies=lambda c: True,
    ),
    "epg_assign_category": ChannelAction(
        id="epg_assign_category",
        label=lambda c: "Assign category…",
        icon=_icons.queue_icon,
        tooltip=(
            "Assign this channel to a user-defined EPG category.\n"
            "Categories appear as shelves in the On Now view."
        ),
        applies=lambda c: True,
    ),
    "epg_remove_override": ChannelAction(
        id="epg_remove_override",
        label=lambda c: "Remove category override",
        icon="",
        tooltip="Remove the manually-assigned category override for this channel",
        applies=lambda c: True,
    ),
    "epg_hide_channel": ChannelAction(
        id="epg_hide_channel",
        label=lambda c: (
            "Hide channel" if c.is_single else "Hide channels…"
        ),
        icon=_icons.hide_icon,
        tooltip="Hide this channel from the EPG On Now view",
        applies=lambda c: True,
    ),
    "epg_hide_show": ChannelAction(
        id="epg_hide_show",
        label=lambda c: (
            "Hide show" if c.is_single else "Hide shows…"
        ),
        icon=_icons.hide_icon,
        tooltip="Hide this show title from the EPG On Now view",
        applies=lambda c: True,
    ),
    # ── Multi-select play ───────────────────────────────────────────────────
    "play_all": ChannelAction(
        id="play_all",
        label=lambda c: f"Play All ({len(c.channel_ids)})",
        icon=_icons.play_all_icon,
        tooltip="Play first selected item, queue the rest in selection order",
        applies=lambda c: c.is_multi,
    ),
    # ── Multi-select (channel surface only) ─────────────────────────────────
    "quickpick_trash": ChannelAction(
        id="quickpick_trash",
        label=lambda c: f"{_icons.delete_icon} Trash",
        icon="",
        tooltip="Assign to Trash — Dislike mood, added to Global Exclusions",
        applies=lambda c: c.is_multi,
    ),
    "quickpick_watch_later": ChannelAction(
        id="quickpick_watch_later",
        label=lambda c: f"{_icons.watch_later_icon} Watch Later",
        icon="",
        tooltip="Assign to Watch Later — Neutral mood",
        applies=lambda c: c.is_multi,
    ),
    "quickpick_explore": ChannelAction(
        id="quickpick_explore",
        label=lambda c: f"{_icons.curious_icon} Explore",
        icon="",
        tooltip="Assign to Explore — Curious mood, surfaces more like this",
        applies=lambda c: c.is_multi,
    ),
    "bulk_category": ChannelAction(
        id="bulk_category",
        label=_bulk_category_label,
        icon=_icons.queue_icon,
        tooltip="Assign a user-defined category to the selected channels",
        applies=lambda c: c.is_multi,
    ),
}

# ---------------------------------------------------------------------------
# Surface layouts
# ---------------------------------------------------------------------------
# Each list contains action ids and the literal "sep" for separator positions.
# The builder emits separators lazily (never leading, trailing, or doubled).

SURFACE_LAYOUTS: dict[str, list[str]] = {
    "channel": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "mark_watched",
        "sep",
        "monitor_series",
        "sep",
        "watch", "track", "unhide", "hide",
        "sep",
        "category",
        # Multi-select extras (applies = is_multi; single-select actions apply = is_single)
        "sep",
        "play_all",
        "sep",
        "quickpick_trash", "quickpick_watch_later", "quickpick_explore",
        "sep",
        "bulk_category",
    ],
    "history": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "monitor_series",
        "sep",
        "remove_history", "hide",
    ],
    "favorites": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "monitor_series",
        "sep",
        "clear_unavailable",
    ],
    "queue": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "monitor_series",
        "sep",
        "hide",
        "sep",
        "clear_unavailable",
    ],
    "recommended": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "monitor_series",
        "sep",
        "not_interested", "hide",
    ],
    "alerts": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "watch",
        "sep",
        "hide",
    ],
    "retry": [
        "play", "play_new_window",
        "sep",
        "favorite",
        "sep",
        "like", "dislike",
        "sep",
        "remove_retry", "clear_retry",
    ],
    "epg_on_now": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "epg_watch", "epg_unwatch", "epg_track_show",
        "sep",
        "epg_assign_category", "epg_remove_override",
        "sep",
        "epg_hide_channel", "epg_hide_show",
    ],
    "epg_browse": [
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "epg_watch", "epg_track_show",
    ],
}


# ---------------------------------------------------------------------------
# Composer
# ---------------------------------------------------------------------------

def build_channel_menu(
    ctx: ChannelMenuContext,
    handlers: dict[str, Callable[[], None]],
    parent=None,
) -> QMenu:
    """Build and return a QMenu for *ctx* using *handlers*.

    Args:
        ctx: Populated ``ChannelMenuContext`` describing the target channel(s)
            and surface.
        handlers: Mapping from action id → zero-argument callable.  Actions
            whose id is NOT in this dict are silently skipped.
        parent: Qt parent widget for the ``QMenu``.

    Returns:
        A ``QMenu`` ready to ``.exec()``.  The caller is responsible for
        positioning and executing it.

    Separator hygiene:
        * A separator is emitted only when at least one real action has already
          been added AND at least one more real action will follow.
        * This eliminates leading, trailing, and doubled separators regardless
          of which actions are skipped due to ``applies`` / handler absence.
    """
    layout = SURFACE_LAYOUTS.get(ctx.surface, [])
    menu = QMenu(parent)

    pending_sep = False   # a "sep" token was seen but not yet emitted
    added_any = False     # at least one real QAction has been added

    for token in layout:
        if token == "sep":
            if added_any:
                pending_sep = True
            continue

        action_def = ACTIONS.get(token)
        if action_def is None:
            continue
        if not action_def.applies(ctx):
            continue
        if token not in handlers:
            continue

        # Emit the pending separator now that we know a real action follows.
        if pending_sep:
            menu.addSeparator()
            pending_sep = False

        # Build the label with icon prefix when applicable.
        # For "favorite" the icon flips depending on is_favorite — compute it
        # separately so the label function itself stays icon-free.
        if token == "favorite":
            raw_label = action_def.label(ctx)
            icon_prefix = (_icons.unfavorite_icon if ctx.is_favorite else _icons.favorite_icon)
            label_text = f"{icon_prefix} {raw_label}"
        elif action_def.icon:
            label_text = f"{action_def.icon} {action_def.label(ctx)}"
        else:
            label_text = action_def.label(ctx)

        # Parent the QAction to the menu (not to parent widget) so Qt owns
        # the object and it is not garbage-collected while the menu is open.
        act = QAction(label_text, menu)
        act.setToolTip(action_def.tooltip)

        if action_def.checkable:
            act.setCheckable(True)
            act.setChecked(action_def.checked(ctx))

        is_enabled = action_def.enabled(ctx)
        act.setEnabled(is_enabled)
        if not is_enabled and action_def.disabled_tooltip:
            act.setToolTip(action_def.disabled_tooltip)

        handler = handlers[token]
        # Absorb optional checkable bool so handlers are uniformly no-arg.
        act.triggered.connect(lambda *_a, h=handler: h())

        menu.addAction(act)
        added_any = True

    return menu
