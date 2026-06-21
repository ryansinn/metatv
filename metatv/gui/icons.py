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
diagnose_icon: str = "∿"    # stream-diagnostics action (U+223F SINE WAVE — monochrome signal waveform)
split_icon: str = "⧉"       # U+29C9 TWO JOINED SQUARES — split-streams toggle (one window per source)
new_window_icon: str = "⧉"  # U+29C9 TWO JOINED SQUARES — open/replace a separate per-source window
close_icon: str = "×"
delete_icon: str = "🗑"
watch_later_icon: str = "👀"  # Watch Later quick-pick category
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
# Carousel / single-axis navigation (monochrome single chevrons — no colour bleed)
nav_prev_icon: str = "‹"   # U+2039 SINGLE LEFT-POINTING ANGLE QUOTATION MARK — "newer / forward"
nav_next_icon: str = "›"   # U+203A SINGLE RIGHT-POINTING ANGLE QUOTATION MARK — "older / back"

# State
loading_icon: str = "⟳"
epg_indicator_icon: str = "▦"   # EPG/guide status square; colored by freshness state
live_indicator_icon: str = "🟢"
stream_retry_pending_icon: str = "🔴"
stream_retry_online_icon: str = "🟢"
status_dot_icon: str = "●"      # filled status dot; colored by state (ok/err) at the call site
watchlist_on_icon: str = "🔔"
watchlist_off_icon: str = "🔕"
preferred_version_icon: str = "🎯"

# Alerts (siren — used for the Alerts sidebar section AND the new-episode alert action;
# not 📡, which is live/provider/events, nor ⚠, which stays for warnings)
new_episodes_icon: str = "🆕"   # "new episodes available" indicator
alert_icon: str = "🚨"          # the alert affordance — Alerts section header + "alert me to new episodes"
manage_icon: str = "⚙"          # manage/organize affordance (e.g. Manage alerts)

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
events_icon: str = "📡"         # EPG Events tab (platform-event / scheduled feeds)

# What's New
whats_new_icon: str = "✦"   # U+2726 BLACK FOUR POINTED STAR — monochrome, menu + dialog header
bullet_icon: str = "•"       # U+2022 BULLET — used in What's New item lists

# View toggles
list_view_icon: str = "☰"
grid_view_icon: str = "⊞"

# Notification type indicators
notification_progress_icon: str = "⟳"
notification_success_icon: str = "✓"
notification_error_icon: str = "✗"
notification_warning_icon: str = "⚠"
notification_info_icon: str = ""

# Provider icon palette — colored-circle glyphs offered when picking a source icon
provider_icon_palette: list[str] = [
    "🔴", "🟠", "🟡", "🟢", "🔵", "🟣", "🟤", "⚫", "⚪", "🔶", "🔷", "🔸", "🔹",
]


def pick_next_icon(used_icons: list[str]) -> str:
    """Return the first palette icon not already in use; cycle if palette exhausted."""
    for icon in provider_icon_palette:
        if icon not in used_icons:
            return icon
    return provider_icon_palette[len(used_icons) % len(provider_icon_palette)]
