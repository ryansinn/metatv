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
partial_watched_icon: str = "◐"      # U+25D0 CIRCLE WITH LEFT HALF BLACK — ~half watched (~37–62%)
partial_watched_q1_icon: str = "◔"   # U+25D4 CIRCLE WITH UPPER RIGHT QUADRANT BLACK — ~quarter watched (<37%)
partial_watched_q3_icon: str = "◕"   # U+25D5 CIRCLE WITH ALL BUT UPPER LEFT QUADRANT BLACK — ~three-quarter (62–99%)

# Actions
play_icon: str = "▶"
play_all_icon: str = "⏩"  # Play first + queue rest (multi-select "Play All")
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

# Discover zoom slider
zoom_icon: str = "⊞"   # card-resize affordance in the Discover header bar

# Poster lightbox
zoom_poster_icon: str = "⤢"   # U+2922 — diagonal arrow; "click to enlarge" affordance

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

# Migration progress indicators
migration_pending_icon: str = "◻"   # U+25FB WHITE MEDIUM SQUARE — task not yet done
migration_done_icon: str = "✓"      # U+2713 CHECK MARK — task complete

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


def watch_progress_glyph(
    watch_percent: int,
    watch_completed: bool,
    partial_threshold_pct: int = 10,
) -> str:
    """Map a stored ``watch_percent`` to the appropriate graduated progress glyph.

    Thresholds (percent):
        - 100 / watch_completed → ✓ (``watched_icon``)
        - ≥ partial_threshold_pct and < 37 → ◔ (``partial_watched_q1_icon``, ~quarter)
        - ≥ 37 and < 63                    → ◐ (``partial_watched_icon``,    ~half)
        - ≥ 63 and < complete              → ◕ (``partial_watched_q3_icon``, ~three-quarter)
        - below partial_threshold_pct       → "" (untouched / no glyph)

    Args:
        watch_percent: 0–100 stored percentage (0 = unwatched or duration unknown).
        watch_completed: Sticky completion flag; overrides percent when True.
        partial_threshold_pct: Lower bound (int, 0–100) below which no glyph is shown.
            Corresponds to ``Config.watch_partial_threshold * 100``.

    Returns:
        One of the four watch-state glyphs, or ``""`` when the item is untouched.
    """
    if watch_completed:
        return watched_icon
    if watch_percent >= 63:
        return partial_watched_q3_icon
    if watch_percent >= 37:
        return partial_watched_icon
    if watch_percent >= partial_threshold_pct:
        return partial_watched_q1_icon
    return ""


# ---------------------------------------------------------------------------
# Watch-indicator icon helpers (QIcon cache, lazily built on the main thread)
# ---------------------------------------------------------------------------
# The small set of watch state x provenance combinations (~8 entries) is cached
# so QPixmap/QIcon construction happens once per glyph x muted pair.  QPixmap is a
# GUI object and MUST be created on the main thread -- these helpers are only ever
# called from the model's data() method which runs on the main thread.

_WATCH_ICON_CACHE: dict[tuple[str, bool], object] = {}  # (glyph, muted) -> QIcon


def watch_icon(glyph: str, muted: bool) -> object:
    """Return a QIcon rendering *glyph* in solid or muted color.

    MUST be called on the main thread -- builds a QPixmap on first use.

    The color is taken from ``theme.COLOR_TEXT`` (solid, deliberate watch) or
    ``theme.COLOR_MUTED`` (muted, auto-advanced via queue).  Both come from
    design tokens -- no inline hex literals.

    Args:
        glyph: One of the watch-progress glyphs (checkmark and circle variants).
        muted: True -> muted/gray (queue-watched); False -> solid (manually-watched).

    Returns:
        A cached ``QIcon`` instance.
    """
    from metatv.gui import theme as _theme  # local import to avoid circular at module load

    cache_key = (glyph, muted)
    if cache_key in _WATCH_ICON_CACHE:
        return _WATCH_ICON_CACHE[cache_key]

    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap

    color_str = _theme.COLOR_MUTED if muted else _theme.COLOR_TEXT
    color = QColor(color_str)

    # Render the glyph at 12 px into a 14x14 transparent pixmap.
    size = 14
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    font = QFont()
    font.setPixelSize(12)
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()

    icon = QIcon(pixmap)
    _WATCH_ICON_CACHE[cache_key] = icon
    return icon


def watch_icon_for_channel(
    glyph: str | None,
    last_played_via: str | None,
) -> object | None:
    """Return a QIcon for a channel's watch state, or None if unwatched.

    Wraps ``watch_icon`` with the provenance mapping:
    - ``last_played_via == "queue"`` -> muted/gray icon (auto-advanced, passive).
    - anything else (manual, alert, None with a glyph) -> solid icon.
    - ``glyph`` is empty or None -> None (no icon; slot stays blank for unwatched rows).

    MUST be called on the main thread.

    Args:
        glyph: Result of ``watch_progress_glyph(...)``; empty-string or None = unwatched.
        last_played_via: Provenance string from the DTO (manual / queue / None).

    Returns:
        A ``QIcon`` or ``None``.
    """
    if not glyph:
        return None
    muted = (last_played_via == "queue")
    return watch_icon(glyph, muted)
