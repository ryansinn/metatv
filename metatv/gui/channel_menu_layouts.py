"""Per-surface channel context-menu layouts.

``SURFACE_LAYOUTS`` maps a menu surface name to the ordered list of action ids
(plus the literal ``"sep"`` for separator positions) that
``metatv.gui.channel_menu.build_channel_menu`` composes into a ``QMenu``. Each
id is looked up in ``channel_menu.ACTIONS`` at build time — this module holds
only the ordering data, so it imports nothing from ``channel_menu``.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Surface layouts
# ---------------------------------------------------------------------------
# Each list contains action ids and the literal "sep" for separator positions.
# The builder emits separators lazily (never leading, trailing, or doubled).

# Download/record/record_programme are listed on every surface that can show
# a VOD/live/programme row respectively — each action's own ``applies`` does
# the media-type/programme gating, so listing it costs nothing where it can't
# apply (a movie in Favorites offers Download, a live channel there does not).
# (Owner, on "download" shipping on "channel" alone: "all vod channel context
# menus should be the same and have download available.") Discover/Recipe/
# Recommendations share the "recommended" layout. Deliberate omission: "retry"
# (nothing to save from a stream that failed to open). record_programme
# (REC-3) schedules the ROW's own start/stop, which is what makes it correct
# on epg_browse's future programmes too, not just epg_on_now/alerts.
# record_window (Option B) is listed beside "record" wherever THAT is.
SURFACE_LAYOUTS: dict[str, list[str]] = {
    "channel": [
        "play", "play_new_window", "play_open_ended_buffer", "play_deep_cache",
        "play_from_beginning", "resume_from",
        "sep",
        "download",
        "record", "record_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "mark_watched",
        "sep",
        "browse_series", "monitor_series",
        "sep",
        "clear_alert",
        "sep",
        "watch", "track", "clear_epg_link", "unhide", "hide",
        "sep",
        "search_title", "copy_title", "show_versions",
        "sep",
        "category",
        # Multi-select extras (applies = is_multi; single-select actions apply = is_single)
        "sep",
        "play_all",
        "sep",
        "bulk_favorite", "bulk_queue", "bulk_mark_watched", "bulk_hide",
        "sep",
        "quickpick_trash", "quickpick_watch_later", "quickpick_explore",
        "sep",
        "bulk_category",
    ],
    "history": [
        "download",
        "sep",
        "play", "play_new_window", "play_open_ended_buffer", "play_deep_cache",
        "play_from_beginning", "resume_from",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "browse_series", "monitor_series",
        "sep",
        "clear_alert",
        "sep",
        "search_title", "copy_title",
        "sep",
        "remove_history", "hide",
    ],
    "favorites": [
        "download",
        "sep",
        "play", "play_new_window", "play_open_ended_buffer", "play_deep_cache",
        "play_from_beginning", "resume_from",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "mark_watched",
        "sep",
        "browse_series", "monitor_series",
        "sep",
        "clear_alert",
        "sep",
        "search_title", "copy_title",
        "sep",
        "category",
        "sep",
        "clear_unavailable",
    ],
    "queue": [
        "download",
        "sep",
        "play", "play_new_window", "play_open_ended_buffer", "play_deep_cache",
        "play_from_beginning", "resume_from",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "mark_watched",
        "sep",
        "browse_series", "monitor_series",
        "sep",
        "clear_alert",
        "sep",
        "search_title", "copy_title",
        "sep",
        "category", "hide",
        "sep",
        "clear_unavailable",
    ],
    # Shared by every Discover-family movie surface (Discover shelves/browse,
    # sidebar Recommended, Recipe "Now Plating", Preferences dashboard) — the
    # FULL standard movie menu, same block as "channel"; `applies=` hides
    # what doesn't fit (mark_watched/category/monitor_series on non-VOD, etc).
    "recommended": [
        "download",
        "sep",
        "play", "play_new_window", "play_open_ended_buffer", "play_deep_cache",
        "play_from_beginning", "resume_from",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "mark_watched",
        "sep",
        "browse_series", "monitor_series",
        "sep",
        "clear_alert",
        "sep",
        "search_title", "copy_title",
        "sep",
        "not_interested", "category", "hide",
    ],
    "alerts": [
        "download",
        "record_programme",
        "sep",
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "watch",
        "sep",
        "clear_alert",
        "sep",
        "search_title", "copy_title",
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
        "record", "record_window", "record_programme",
        "sep",
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
        "sep",
        "clear_epg_link",
    ],
    "epg_browse": [
        "record_programme",
        "sep",
        "play", "play_new_window",
        "sep",
        "favorite", "queue",
        "sep",
        "like", "dislike",
        "sep",
        "epg_watch", "epg_track_show",
        "sep",
        "clear_epg_link",
    ],
}
