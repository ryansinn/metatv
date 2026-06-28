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
open_ended_buffer_icon: str = "⏳"  # U+23F3 HOURGLASS NOT DONE — open-ended disk-backed buffer mode
play_from_beginning_icon: str = "⏮"  # U+23EE LAST TRACK BUTTON — force start from position 0
resume_from_icon: str = "⏩"  # U+23E9 BLACK RIGHT-POINTING DOUBLE TRIANGLE — resume from saved position
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
filter_only_icon: str = "◎"   # U+25CE BULLSEYE — "show only this group" affordance
show_all_icon: str = "⋯"    # U+22EF MIDLINE HORIZONTAL ELLIPSIS — "show all / expand" affordance
see_all_arrow_icon: str = "→"  # U+2192 RIGHTWARDS ARROW — "See all / Show all" drill-down affordance
hide_icon: str = "🚫"
hide_watched_filter_icon: str = "✓"   # Used in "Hide watched" toggle label
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

# Tag provenance indicators (details pane — DR-0006 display)
# source_given: provider explicitly supplied this value (solid square — asserted fact)
tag_source_given_icon: str = "■"    # U+25A0 BLACK SQUARE — "provider said so"
# inferred: MetaTV derived this from a secondary signal (hollow square — estimated)
tag_inferred_icon: str = "□"        # U+25A1 WHITE SQUARE — "MetaTV guessed this"
# tags section header
tag_section_icon: str = "🏷"        # tag/label icon for the Tags collapsible header

# Tag cloud — state mark prefixes (WeightedTagCloud)
tag_include_icon: str = "✓"   # U+2713 CHECK MARK — "this facet value is included in filter"
tag_exclude_icon: str = "⊘"   # U+2298 CIRCLED DIVISION SLASH — "this facet value is excluded"

# Tag cloud — sort / filter controls
sort_icon: str = "⇅"   # U+21C5 UPWARDS ARROW LEFTWARDS OF DOWNWARDS ARROW — sort toggle

# Content variant count badge (dedup Slice 2 — shown on collapsed cards with >1 variant)
variant_count_icon: str = "×"    # U+00D7 MULTIPLICATION SIGN — "×N" variant count badge prefix

# Recipe builder (task #56)
recipe_icon: str = "✦"          # U+2726 BLACK FOUR POINTED STAR — Recipe chip (same as whats_new star)
recipe_check_icon: str = "✓"    # U+2713 CHECK MARK — included ingredient indicator (alias of tag_include_icon)
recipe_omit_icon: str = "⊘"     # U+2298 CIRCLED DIVISION SLASH — omitted/excluded ingredient (alias of tag_exclude_icon)
recipe_save_icon: str = "＋"     # U+FF0B FULLWIDTH PLUS SIGN — Save recipe action
recipe_clear_icon: str = "×"    # U+00D7 MULTIPLICATION SIGN — Clear recipe action (alias of close_icon)
recipe_edit_icon: str = "✎"     # U+270E LOWER RIGHT PENCIL — edit/rename recipe (reserved for slice 4)

# Dev-only QA Testing Checklist
qa_checklist_icon: str = "🧪"      # Testing Checklist menu item / window header
qa_all_clear_icon: str = "🎉"      # Empty state — nothing left to test
qa_purge_icon: str = "✓"           # Purge / mark-all-done button
qa_archive_icon: str = "📦"        # Archive a single fully-checked entry
qa_unarchive_icon: str = "↩"       # Unarchive / restore an archived entry
qa_pass_icon: str = "✓"            # U+2713 CHECK MARK — mark a step PASSED (tri-state)
qa_fail_icon: str = "✗"            # U+2717 BALLOT X — mark a step FAILED (tri-state)
qa_attach_icon: str = "📎"         # Attach a screenshot to a failed step
qa_stale_icon: str = "⚠"           # Newer build available — re-test hint
qa_flag_icon: str = "🚩"            # Flagged Items section header + add-item indicator
qa_triaged_icon: str = "✔"         # U+2714 HEAVY CHECK MARK — flagged item triaged status
qa_retest_icon: str = "↻"          # U+21BB CLOCKWISE OPEN CIRCLE — Re-test log snapshot
qa_type_bug_icon: str = "🐛"       # Flagged item type: bug
qa_type_feature_icon: str = "✨"   # Flagged item type: feature request
qa_type_note_icon: str = "📝"      # Flagged item type: general note
qa_addressed_icon: str = "↺"       # U+21BA ANTICLOCKWISE OPEN CIRCLE — addressed-by-later-PR badge
qa_jump_icon: str = "↑"            # U+2191 UPWARDS ARROW — jump to the addressing entry

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


def effective_watch_pct(watch_percent: int, watch_progress: int) -> int:
    """Return the effective watch percentage for glyph selection.

    When ``watch_percent`` is 0 but ``watch_progress`` is nonzero, the item has
    started but no explicit % was captured (e.g. very short progress).  Promote
    it to 1 so the partial glyph shows rather than leaving the row blank.

    Args:
        watch_percent: 0–100 stored percentage.
        watch_progress: Resume position in seconds (0 = unwatched or completed).

    Returns:
        int: Effective percentage for ``watch_progress_glyph()``.
    """
    return watch_percent or (1 if watch_progress > 0 else 0)


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


# ---------------------------------------------------------------------------
# General glyph → QIcon helper (menu action icons)
# ---------------------------------------------------------------------------
# Renders any text glyph to a QIcon for use with QAction.setIcon().  Cached
# by glyph string — construction is deferred to first use so the module can be
# imported before a QApplication exists.

_GLYPH_ICON_CACHE: dict[str, object] = {}  # glyph -> QIcon


def glyph_icon(glyph: str) -> object:
    """Return a QIcon rendering *glyph* for use in QAction.setIcon().

    MUST be called on the main thread — builds a QPixmap on first use.
    The color is taken from the ``COLOR_TEXT`` design token.

    Args:
        glyph: Text glyph (emoji or symbol) to render.

    Returns:
        A cached ``QIcon`` instance.
    """
    if glyph in _GLYPH_ICON_CACHE:
        return _GLYPH_ICON_CACHE[glyph]

    from metatv.gui import theme as _theme  # local import to avoid circular at load
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication

    color = QColor(_theme.COLOR_TEXT)
    size = 16
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    phys = int(size * dpr)
    pixmap = QPixmap(phys, phys)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    font = QFont()
    font.setPixelSize(int(_theme.FONT_LG.replace("px", "")))
    painter.setFont(font)
    painter.setPen(color)
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()

    icon = QIcon(pixmap)
    _GLYPH_ICON_CACHE[glyph] = icon
    return icon


def _clear_glyph_icon_cache() -> None:
    """Discard all cached QIcon entries from :func:`glyph_icon`.

    Called after ``QApplication`` teardown (e.g. between tests) so stale
    QIcon objects from a previous ``QApplication`` instance are never reused.
    """
    _GLYPH_ICON_CACHE.clear()


def _clear_watch_icon_cache() -> None:
    """Discard all cached QIcon entries.

    Called after ``QApplication`` teardown (e.g. between tests) so stale
    QIcon objects from a previous ``QApplication`` instance are never reused.
    """
    _WATCH_ICON_CACHE.clear()


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

    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
    from PyQt6.QtWidgets import QApplication

    color_str = _theme.COLOR_MUTED if muted else _theme.COLOR_TEXT
    color = QColor(color_str)

    # Render the glyph HiDPI-aware: create the pixmap at physical resolution
    # and set the device pixel ratio so Qt renders it crisply on Retina displays.
    size = 14
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    phys = int(size * dpr)
    pixmap = QPixmap(phys, phys)
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    font = QFont()
    # Use the FONT_LG token (12px) — never a raw pixel literal.
    font.setPixelSize(int(_theme.FONT_LG.replace("px", "")))
    painter.setFont(font)
    painter.setPen(color)
    # Draw into the LOGICAL-size rect (size×size), not pixmap.rect() (which is
    # the device rect, e.g. 28×28 at dpr=2).  With setDevicePixelRatio the
    # painter works in logical coords, so using the device rect centers the
    # glyph in a box twice too big and pushes it into a corner.
    painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, glyph)
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
