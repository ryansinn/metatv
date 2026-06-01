"""Central icon registry for MetaTV UI.

All glyphs, emoji, and symbols used in the UI must be defined here.
Import and reference by name — never use a literal glyph in widget code:

    from metatv.gui import icons
    btn = QPushButton(icons.close_icon)

To add a new icon, add it here first, then reference it.
"""

# Media type indicators
live_icon: str = "📡"
movie_icon: str = "🎬"
series_icon: str = "📺"
season_icon: str = "📁"
episode_icon: str = "▶"
unknown_icon: str = "❓"

# Favorite / rating
favorite_icon: str = "★"
unfavorite_icon: str = "☆"
rating_star_icon: str = "★"
like_icon: str = "👍"
dislike_icon: str = "👎"
not_interested_icon: str = "🙅"
curious_icon: str = "❓"
watched_icon: str = "✓"

# Actions
play_icon: str = "▶"
close_icon: str = "×"
delete_icon: str = "🗑"
refresh_icon: str = "⟳"
settings_icon: str = "⚙"
search_icon: str = "🔍"
filter_icon: str = "⚡"
hide_icon: str = "🚫"
pin_icon: str = "📌"
manage_icon: str = "⚙"
visibility_toggle_icon: str = "👁"

# Navigation / collapse
expand_icon: str = ">"
collapse_icon: str = "⌄"
move_up_icon: str = "▲"
move_down_icon: str = "▼"
prev_icon: str = "◀"
next_icon: str = "▶"

# State
loading_icon: str = "⟳"
live_indicator_icon: str = "🟢"
stream_retry_pending_icon: str = "🔴"
stream_retry_online_icon: str = "🟢"
watchlist_on_icon: str = "🔔"
watchlist_off_icon: str = "🔕"
preferred_version_icon: str = "🎯"

# Section / navigation labels
history_icon: str = "🕒"
provider_icon: str = "📡"
watch_alerts_icon: str = "⚠"
info_icon: str = "ℹ"
watchlist_icon: str = "⏰"
calendar_icon: str = "📅"
discover_icon: str = "✨"
preferences_icon: str = "🎯"
queue_icon: str = "📋"

# View toggles
list_view_icon: str = "☰"
grid_view_icon: str = "⊞"

# Notification type indicators
notification_progress_icon: str = "⟳"
notification_success_icon: str = "✓"
notification_error_icon: str = "✗"
notification_warning_icon: str = "⚠"
notification_info_icon: str = ""
