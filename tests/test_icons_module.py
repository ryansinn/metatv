"""Characterization tests for metatv/gui/icons.py (B3-4).

Pins that:
1. The icons module exports the same named constants as Config's icon fields
2. Values are non-empty strings
3. Key constants match the values in Config defaults (so migration is transparent)
"""

import pytest

# Expected icon names that must exist in the icons module
REQUIRED_ICONS = [
    "expand_icon", "collapse_icon", "play_icon", "close_icon", "delete_icon",
    "refresh_icon", "favorite_icon", "unfavorite_icon", "hide_icon",
    "live_icon", "movie_icon", "series_icon", "season_icon", "episode_icon",
    "unknown_icon", "loading_icon", "settings_icon", "search_icon", "filter_icon",
    "history_icon", "provider_icon", "watch_alerts_icon",
    "stream_retry_pending_icon", "stream_retry_online_icon",
    "info_icon", "watchlist_icon", "live_indicator_icon", "calendar_icon",
    "discover_icon", "move_up_icon", "move_down_icon", "visibility_toggle_icon",
    "watched_icon", "rating_star_icon", "like_icon", "dislike_icon",
    "not_interested_icon", "curious_icon", "preferences_icon",
    "preferred_version_icon", "queue_icon", "pin_icon", "manage_icon",
    "watchlist_on_icon", "watchlist_off_icon", "prev_icon", "next_icon",
    "list_view_icon", "grid_view_icon",
    "notification_progress_icon", "notification_success_icon",
    "notification_error_icon", "notification_warning_icon", "notification_info_icon",
]

# Icons that are intentionally empty strings
_ALLOWED_EMPTY = {"notification_info_icon"}


def test_icons_module_has_all_required_names():
    """Every icon used in the codebase must be exported from icons.py."""
    import metatv.gui.icons as icons
    missing = [name for name in REQUIRED_ICONS if not hasattr(icons, name)]
    assert not missing, f"Missing icons: {missing}"


def test_icons_are_strings():
    """Every icon constant must be a string (may be empty for intentional no-icon cases)."""
    import metatv.gui.icons as icons
    bad = [
        name for name in REQUIRED_ICONS
        if not isinstance(getattr(icons, name, None), str)
        or (not getattr(icons, name) and name not in _ALLOWED_EMPTY)
    ]
    assert not bad, f"Non-string or unexpectedly empty icons: {bad}"


def test_icons_match_config_defaults():
    """Icon values must match Config defaults so migration is transparent."""
    import metatv.gui.icons as icons
    from metatv.core.config import Config
    cfg = Config()
    mismatched = []
    for name in REQUIRED_ICONS:
        if hasattr(cfg, name):
            cfg_val = getattr(cfg, name)
            icon_val = getattr(icons, name, None)
            if cfg_val != icon_val:
                mismatched.append(f"{name}: config={cfg_val!r} icons={icon_val!r}")
    assert not mismatched, "Icons don't match Config defaults:\n" + "\n".join(mismatched)
