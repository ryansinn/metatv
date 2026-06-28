"""Shared Qt stylesheet tokens and constants.

Two layers — keep them separate:

1. **Design tokens** (``COLOR_*``, ``FONT_*``, ``OVERLAY_*``) — the *only* place raw
   palette values (hex, rgba, px) are allowed to live. They describe the design scale,
   so token names may be appearance-based (``FONT_MD``, ``COLOR_MUTED``).

2. **Semantic constants** — full stylesheet strings composed *from tokens*, named by the
   **role** they play in the UI (``STATUS_OK``, ``SECTION_HINT``, ``LOADING_TEXT``), never
   by their appearance (no ``TEXT_SM`` / ``GREY_11``). A role name localizes intent and
   prevents two unrelated widgets from accidentally coupling to the same literal.

Rules (also in CLAUDE.md; rationale in docs/UI_UX_GUIDELINES.md → "Theming & style tokens"):
- Never hardcode a hex/rgba/px literal in widget code *or* in a new semantic constant.
  Reuse a token, or add one here, then compose.
- Any stylesheet string used by more than one widget must be a named, role-based constant
  here. A genuinely single-use style may stay inline, but should still build from tokens.
- Dynamic styles (color chosen at runtime) compose a token into an f-string at the call
  site — that is fine; the literal still comes from a token.
"""

from __future__ import annotations

from PyQt6.QtGui import QFont


def zoomed_font(token: str, zoom: float, *, bold: bool = False) -> QFont:
    """Return a QFont whose pixel size is the token's px value scaled by *zoom*.

    The token must be one of the ``FONT_*`` constants defined below (e.g.
    ``FONT_MD = "11px"``).  This is the sanctioned way to scale fonts by the
    Discover zoom level without violating the "no inline px literals" rule —
    the token remains the base/source-of-truth; zoom is a user transform
    applied via QFont (not a stray stylesheet literal).

    Args:
        token: A ``FONT_*`` constant string, e.g. ``FONT_MD``.
        zoom:  Zoom multiplier (will be clamped to the card-zoom range 0.6–1.8
               by the caller; no clamping here).
        bold:  When True, the returned font is bold.

    Returns:
        A ``QFont`` with ``pixelSize`` set to ``max(6, round(px * zoom))``.
    """
    px = int(token.replace("px", ""))
    f = QFont()
    f.setPixelSize(max(6, round(px * zoom)))
    if bold:
        f.setBold(True)
    return f


# ── 1. Design tokens ────────────────────────────────────────────────────────────
# Text colors, light → faint
COLOR_TEXT_HI   = "#fff"        # emphasized / active text
COLOR_TEXT      = "#ccc"        # primary light text
COLOR_TEXT_2    = "#ddd"        # hover text
COLOR_TEXT_LOW  = "#bbb"        # slightly dimmer than primary (group labels)
COLOR_DIM       = "#aaa"        # dim text / icon buttons
COLOR_DIM_2     = "#999"        # dimmer (upcoming)
COLOR_MUTED     = "#888"        # secondary text
COLOR_DISABLED  = "#777"        # disabled / clear buttons
COLOR_MUTED_2   = "#666"        # tertiary text / counts
COLOR_FAINT     = "#555"        # faint hints / empty states
# Named CSS colors (deliberately distinct from the hex greys above)
COLOR_GRAY      = "gray"        # dim meta / loading text
COLOR_LIGHTGRAY = "lightgray"   # detail body text
# Structural
COLOR_BORDER     = "#444"
COLOR_LINE       = "#333"        # separators / panel bg
COLOR_LINE_DARK  = "#2a2a2a"     # fainter hairline separators
COLOR_BG_BAR     = "#1e1e1e"     # bottom nav bar / sidebar footer panel background
COLOR_BG_SECTION = "#1a1a1a"     # filter section header background
# Accent + status
COLOR_ACCENT       = "#2288dd"
COLOR_ACCENT_HOVER = "#55aaff"
COLOR_OK    = "#4CAF50"
COLOR_WARN  = "#FFC107"
COLOR_ERR   = "#F44336"
COLOR_ERR_2 = "#e05050"        # softer red — destructive buttons / test-fail badges
COLOR_GOLD  = "gold"
# Section / category accent palette (filter groups, icon picker)
COLOR_ACCENT_BLUE         = "#4488ff"
COLOR_ACCENT_BLUE_2       = "#88aaff"     # lighter — link hover
COLOR_ACCENT_BLUE_3       = "#99bbff"     # lighter — info hover
COLOR_ACCENT_GREEN        = "#44aa77"
COLOR_ACCENT_PURPLE       = "#9966cc"
COLOR_ACCENT_ORANGE       = "#f0a040"
COLOR_ACCENT_ORANGE_FADED = "#f0a04077"   # orange @ ~47% alpha (AND-filter hint)
COLOR_ACCENT_TEAL         = "#33bb88"
COLOR_ACCENT_BROWN        = "#cc7722"
COLOR_BTN_SAVE       = "#2255cc"
COLOR_BTN_SAVE_HOVER = "#3366dd"
# Exclusions chip — dedicated teal (slightly cooler than COLOR_ACCENT_TEAL)
COLOR_EXCLUSIONS_ACTIVE = "#2a9d8f"
# White overlays (alpha)
OVERLAY_ORANGE_12 = "rgba(240,160,64,0.12)"   # amber tint — context filter chip bg
OVERLAY_EXCLUSIONS_10  = "rgba(42,157,143,0.10)"  # teal tint — Exclusions chip active bg
OVERLAY_EXCLUSIONS_18  = "rgba(42,157,143,0.18)"  # teal tint — Exclusions chip hover
OVERLAY_ORANGE_10      = "rgba(240,160,64,0.10)"  # amber tint — Exclusions chip paused bg
OVERLAY_ORANGE_18      = "rgba(240,160,64,0.18)"  # amber tint — Exclusions chip paused hover

OVERLAY_03 = "rgba(255,255,255,0.03)"
OVERLAY_04 = "rgba(255,255,255,0.04)"
OVERLAY_05 = "rgba(255,255,255,0.05)"
OVERLAY_08 = "rgba(255,255,255,0.08)"
OVERLAY_10 = "rgba(255,255,255,0.10)"
OVERLAY_15 = "rgba(255,255,255,0.15)"
OVERLAY_18 = "rgba(255,255,255,0.18)"
OVERLAY_POPUP = "rgba(40,40,50,0.97)"   # opaque popup surface (icon palette)
# Blue (COLOR_ACCENT_BLUE) tints
OVERLAY_BLUE_10 = "rgba(68,136,255,0.1)"
OVERLAY_BLUE_15 = "rgba(68,136,255,0.15)"
OVERLAY_BLUE_20 = "rgba(68,136,255,0.2)"
OVERLAY_BLUE_25 = "rgba(68,136,255,0.25)"
OVERLAY_BLUE_40 = "rgba(68,136,255,0.4)"
OVERLAY_BLUE_60 = "rgba(68,136,255,0.6)"
# Red (COLOR_ERR_2) tints — destructive hover
OVERLAY_ERR    = "rgba(224,80,80,0.2)"
OVERLAY_ERR_15 = "rgba(224,80,80,0.15)"

# --- Quality / badge palette (badge_utils) ---
OVERLAY_PLATFORM_BADGE = "rgba(60,120,180,0.5)"   # steel-blue tint for streaming platform codes
COLOR_QUALITY_UHD  = "#7755cc"
COLOR_QUALITY_FHD  = "#3388dd"
COLOR_QUALITY_HD   = "#229977"
COLOR_QUALITY_RAW  = "#cc8822"
COLOR_QUALITY_LIVE = "#bb9900"
COLOR_AUDIO_BADGE  = "#556633"

# --- Mood palette (category_picker) ---
COLOR_MOOD_LIKE_BG     = "#2ecc71"
COLOR_MOOD_LIKE_FG     = "#1a7a43"
COLOR_MOOD_CURIOUS_BG  = "#27ae60"
COLOR_MOOD_CURIOUS_FG  = "#155a2e"
COLOR_MOOD_NOTFORME_BG = "#c0392b"
COLOR_MOOD_NOTFORME_FG = "#f5a5a0"
COLOR_MOOD_DISLIKE_BG  = "#e74c3c"
COLOR_MOOD_TRASH_BG    = "#5a1a1a"
COLOR_MOOD_WATCH_BG    = "#1a3a5a"
COLOR_MOOD_EXPLORE_BG  = "#1a3a1a"
COLOR_MOOD_EXPLORE_FG  = "#88cc88"

# --- Notification severity ---
COLOR_NOTIFY_ERR_BG     = "#2c1515"
COLOR_NOTIFY_ERR_BORDER = "#ff4444"
COLOR_NOTIFY_OK_BG      = "#152c15"
COLOR_NOTIFY_OK_BORDER  = "#44ff44"
COLOR_NOTIFY_WARN_BG     = "#2c2415"
COLOR_NOTIFY_WARN_BORDER = "#ffaa44"
COLOR_NOTIFY_INFO_BG    = "#1a1a2e"

# --- Similar-titles lightbox theme ---
COLOR_LIGHTBOX_BG     = "#1e1e2e"
COLOR_LIGHTBOX_HEADER = "#2a2a3e"

# --- Yellow alert banner (main_window) ---
COLOR_BANNER_YEL_BG            = "#3a3a1a"
COLOR_BANNER_YEL_FG            = "#e8d44d"
COLOR_BANNER_YEL_BORDER        = "#7a7a30"
COLOR_BANNER_YEL_BG_HOVER      = "#4a4a22"
COLOR_BANNER_YEL_BORDER_HOVER  = "#aaaa50"

# --- PPV ---
COLOR_PPV_ACCENT = "#ff6b35"

# --- Recipe builder — facet accent palette ---
# Each facet in the Recipe Pantry sidebar gets a distinct accent color.
# These are the ONLY place these hex values may appear; all other code
# references the token name (COLOR_FACET_*).
COLOR_FACET_GENRE      = "#7bd88f"   # soft green — genre
COLOR_FACET_CATEGORY   = COLOR_ACCENT_ORANGE   # warm orange — live-channel kind (Sports/News/Kids…)
COLOR_FACET_LANGUAGE   = "#34d3c0"   # teal — language
COLOR_FACET_SUBTITLE   = "#5bc4b0"   # muted teal — subtitle language (softer sibling of language)
COLOR_FACET_DUB        = "#4db8e8"   # sky blue — dub language
COLOR_FACET_FORMAT     = "#c8a96e"   # warm sand — audio format (Dub/Original/Multi/Dual)
COLOR_FACET_REGION     = "#f5b73d"   # amber/gold — region
COLOR_FACET_PLATFORM   = "#a78bfa"   # purple — platform
COLOR_FACET_DECADE     = "#6ea8ff"   # periwinkle — decade
COLOR_FACET_QUALITY    = "#9fb9d4"   # steel-blue — quality
COLOR_FACET_COLLECTION = "#ef7faa"   # pink — collection

# Recipe builder backgrounds / surfaces (Broadcast Noir palette)
COLOR_RECIPE_BG        = "#07080b"   # near-black body
COLOR_RECIPE_PANEL_BG  = "#0a0d12"   # slightly lighter panel bg
COLOR_RECIPE_TEXT      = "#edeae0"   # warm off-white body text
COLOR_RECIPE_MUTED     = "#9aa0ad"   # secondary text / labels
COLOR_RECIPE_MUTED_2   = "#5b626f"   # tertiary / very dim text

# Recipe builder overlays
OVERLAY_RECIPE_SELECTED  = "rgba(245,183,61,0.08)"   # amber tint — selected facet row

# Hyperlink color — used for clickable QLabel rich-text links (e.g. PR# in QA checklist).
# Intentionally reuses the same blue as other interactive link elements in the app.
COLOR_LINK = COLOR_ACCENT_BLUE

# --- misc preserved accents ---
COLOR_RED_BRIGHT        = "#ff8888"
COLOR_ERR_MUTED         = "#aa6666"
COLOR_GOLD_LIGHT        = "#ffe566"
COLOR_PREF_NUDGE        = "#8fca8f"
COLOR_ACCENT_BLUE_LIGHT = "#aad4ff"
COLOR_BG_CARD           = "#252525"
COLOR_BG_DEEP           = "#111111"
COLOR_SURFACE_LIGHT     = "#f5f5f5"
COLOR_SURFACE_LIGHT_2   = "#e0e0e0"
COLOR_SURFACE_LIGHT_3   = "#d0d0d0"

# --- card backdrop tints (discover_card) ---
BACKDROP_TINTS = ["#1a3a5c", "#2d4a1e", "#4a1e2d", "#2d1e4a", "#1e4a3a", "#3a2d1e"]

# --- brown/amber tint (hidden-mode banner) ---
OVERLAY_BROWN_08 = "rgba(204,136,0,0.08)"

# --- green pref-nudge tints (details_versions) ---
OVERLAY_GREEN_15 = "rgba(80,160,80,0.15)"
OVERLAY_GREEN_40 = "rgba(80,160,80,0.4)"

# --- err2 tint (categories_dialog / details_sections adult badge) ---
OVERLAY_ERR2_15 = "rgba(204,68,68,0.15)"

# --- warn/amber tint (epg_agenda_widget now-card) ---
OVERLAY_WARN_06 = "rgba(255,200,0,0.06)"

# --- black + extra blue overlays ---
OVERLAY_BLACK_30   = "rgba(0,0,0,0.3)"
OVERLAY_BLACK_55   = "rgba(0,0,0,0.55)"
OVERLAY_BLACK_60   = "rgba(0,0,0,0.6)"
OVERLAY_BLACK_65   = "rgba(0,0,0,0.65)"
OVERLAY_BLUE_LT_25 = "rgba(136,170,255,0.25)"

# Type scale
FONT_XS  = "9px"
FONT_SM  = "10px"
FONT_MD  = "11px"
FONT_LG  = "12px"
FONT_XL  = "13px"
FONT_2XL = "14px"
FONT_3XL = "18px"
FONT_4XL = "20px"
# One-off larger sizes (provider editor / icon picker)
FONT_HEADING = "15px"   # provider-name input
FONT_INPUT   = "16px"   # custom-emoji input
FONT_ICON    = "17px"   # icon-palette buttons
FONT_ICON_LG = "24px"   # main icon button

# Tag-cloud sizing ladder (WeightedTagCloud — log-bucketed by catalogue count)
# FONT_CLOUD_1 is the smallest tier (rare/niche tags); FONT_CLOUD_6 is the largest
# (dominant tags with the highest catalogue weight).  These are the ONLY place
# cloud px sizes are defined — widget code picks a token via _count_to_font_token().
FONT_CLOUD_1 = "11px"   # smallest — rare tags
FONT_CLOUD_2 = "13px"
FONT_CLOUD_3 = "15px"
FONT_CLOUD_4 = "18px"
FONT_CLOUD_5 = "22px"
FONT_CLOUD_6 = "27px"   # largest — dominant tags


# ── 2. Semantic constants (composed from tokens, named by role) ──────────────────

# Play / action buttons
PLAY_BTN = (
    "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT +
    "; font-size: " + FONT_XL + "; padding: 0 2px; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
)
PLAY_BTN_SMALL = (
    "QPushButton { background: transparent; border: none; color: " + COLOR_ACCENT +
    "; font-size: " + FONT_LG + "; padding: 0; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_HOVER + "; }"
)
CLEAR_BTN = "border: none; color: " + COLOR_DISABLED + "; font-size: " + FONT_SM + ";"
CLOSE_BTN = "color: " + COLOR_MUTED_2 + "; border: none; background: transparent; font-size: " + FONT_2XL + ";"
EYE_BTN = "border: none; padding: 0; color: " + COLOR_DIM + ";"
PANEL_BTN = (
    "QPushButton { background:" + COLOR_LINE + "; color:" + COLOR_DIM + "; border:1px solid " + COLOR_BORDER + ";"
    " border-radius:3px; padding:0 7px; font-size:" + FONT_MD + "; }"
    "QPushButton:hover { background:" + COLOR_BORDER + "; color:" + COLOR_TEXT_2 + "; }"
)
# Compact inline "Only" link-button for filter group rows
FILTER_ONLY_BTN = (
    "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED_2 + ";"
    " font-size: " + FONT_SM + "; padding: 0 2px; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
)
# "Show all (N)" / "Show less" expander link inside large filter facet sections
FILTER_SHOW_ALL_BTN = (
    "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED + ";"
    " font-size: " + FONT_MD + "; padding: 4px 8px; text-align: left; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
)
# Flat full-bleed nav button on a bar/footer panel (sidebar Settings, bottom-nav Diagnose)
FLAT_NAV_BTN = (
    "QPushButton { font-size: " + FONT_XL + "; color: " + COLOR_TEXT_LOW +
    "; padding: 7px 12px; border-top: 1px solid " + COLOR_LINE +
    "; background: " + COLOR_BG_BAR + "; }"
    "QPushButton:hover { color: " + COLOR_TEXT_2 + "; background: " + COLOR_LINE_DARK + "; }"
)
# Checkable flat nav-bar toggle button (e.g. Split Streams).  Off state mirrors
# FLAT_NAV_BTN; checked state highlights with the accent color so ON is obvious.
NAV_TOGGLE_BTN = (
    "QPushButton { font-size: " + FONT_XL + "; color: " + COLOR_TEXT_LOW +
    "; padding: 7px 12px; border-top: 1px solid " + COLOR_LINE +
    "; background: " + COLOR_BG_BAR + "; }"
    "QPushButton:hover { color: " + COLOR_TEXT_2 + "; background: " + COLOR_LINE_DARK + "; }"
    "QPushButton:checked { color: " + COLOR_ACCENT + "; border-top: 1px solid " + COLOR_ACCENT + "; }"
    "QPushButton:checked:hover { color: " + COLOR_ACCENT_HOVER + "; background: " + COLOR_LINE_DARK + "; }"
)
RATING_BTN = (
    "QPushButton { border: none; border-radius: 3px; padding: 2px 6px;"
    " font-size: " + FONT_XL + "; color: " + COLOR_MUTED + "; }"
    "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + "; }"
)

# Details-pane action rail — one shared role for every icon-only button in the
# vertical rail left of the poster (favorite/play/queue/sentiment/alert/watchlist/
# hide).  State is conveyed via :checked + icon-swap + tooltip (no text labels), so
# all rail buttons read uniformly as distinct interactive targets.
DETAIL_RAIL_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
    " padding: 4px 2px; font-size: " + FONT_2XL + "; background: transparent;"
    " color: " + COLOR_DIM + "; }"
    "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_DIM + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + ";"
    " border-color: " + COLOR_DIM + "; }"
)

# Alert/monitor rail button — inactive reads like a normal rail button; active
# (:checked, "alerting") glows red so the siren clearly turns on.
DETAIL_RAIL_BTN_ALERT = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
    " padding: 4px 2px; font-size: " + FONT_2XL + "; background: transparent;"
    " color: " + COLOR_DIM + "; }"
    "QPushButton:checked { background: " + OVERLAY_ERR + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_ERR + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + ";"
    " border-color: " + COLOR_DIM + "; }"
)

# Details-pane PRIMARY action buttons — full-size, labeled (icon + text), shown in
# a row directly below the poster (the most-used actions get the prominent slot).
# Play is the SECONDARY/outline action (always starts from the beginning); Resume
# is the DOMINANT filled-orange action (continue from the saved position).  Orange,
# never green — green is reserved for a future "currently playing" indicator.
DETAIL_PLAY_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
    " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
    " background: transparent; color: " + COLOR_TEXT + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_DIM + "; }"
)
DETAIL_RESUME_BTN = (
    "QPushButton { border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 4px;"
    " padding: 8px 12px; font-size: " + FONT_XL + "; font-weight: bold;"
    " background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
    "QPushButton:hover { background: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_TEXT_HI + "; }"
)

# Details-pane SECONDARY action button — the full-width labeled "Watch Later"
# (queue) promoted out of the rail to sit directly under the primary Play/Resume
# row.  Outline by default; :checked (already queued) fills subtly so the state
# reads at a glance.  Neutral palette — orange is reserved for Resume, green for a
# future "now playing" indicator.
DETAIL_QUEUE_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; border-radius: 4px;"
    " padding: 6px 12px; font-size: " + FONT_LG + "; background: transparent;"
    " color: " + COLOR_TEXT + "; }"
    "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_DIM + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_DIM + "; }"
)

# Poster watched badge — a corner check overlay (Plex/Jellyfin convention).
# WATCHED: a persistent SOLID badge (hover tints red = "click to unmark").
# UNWATCHED: a FAINT badge revealed only on poster hover (hover brightens =
# "click to mark watched").  Neutral palette — NOT green (reserved as above).
POSTER_WATCHED_BADGE = (
    "QPushButton { background: " + OVERLAY_BLACK_65 + "; color: " + COLOR_TEXT_HI + ";"
    " border: 1px solid " + COLOR_TEXT_HI + "; border-radius: 13px;"
    " font-size: " + FONT_XL + "; font-weight: bold; }"
    "QPushButton:hover { background: " + OVERLAY_ERR + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_ERR + "; }"
)
POSTER_UNWATCHED_BADGE = (
    "QPushButton { background: " + OVERLAY_BLACK_30 + "; color: " + COLOR_DIM + ";"
    " border: 1px solid " + COLOR_DIM + "; border-radius: 13px;"
    " font-size: " + FONT_XL + "; }"
    "QPushButton:hover { background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_TEXT_HI + ";"
    " border-color: " + COLOR_TEXT_HI + "; }"
)

# Channel-name labels (EPG rows)
CHANNEL_NAME          = "font-size: " + FONT_MD + ";"
CHANNEL_NAME_LIVE     = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
CHANNEL_NAME_UPCOMING = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + ";"
CHANNEL_NAME_DIM      = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"

# Channel-list row — ForegroundRole color for fully-watched (non-live) rows.
# Dimmed so completed content recedes; in-progress and unwatched rows use the
# default (delegate) foreground.  Build a QBrush from this at the call site:
#   QBrush(QColor(CHANNEL_ROW_WATCHED_FG))
CHANNEL_ROW_WATCHED_FG: str = COLOR_MUTED

# Time labels
TIME_LABEL          = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
TIME_LABEL_UPCOMING = "color: " + COLOR_DISABLED + "; font-size: " + FONT_MD + ";"

# Section headers / hints / items
SECTION_HDR = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 +
    "; letter-spacing: 1px; padding: 6px 4px 4px 4px;"
)
SECTION_HDR_LG = (
    "font-size: " + FONT_MD + "; font-weight: bold; color: " + COLOR_MUTED_2 +
    "; letter-spacing: 1px; padding: 4px 0;"
)
SECTION_HINT      = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + "; padding: 2px 0 6px 0;"
# Warning banner for stale/out-of-date EPG guide data (EPG view).
EPG_STALE_NOTICE  = (
    "color: " + COLOR_WARN + "; font-size: " + FONT_MD + ";"
    " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 6px 10px;"
)
SECTION_ITEM      = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + "; padding: 4px 0;"
SECTION_TITLE_SM  = "font-size: " + FONT_LG + "; font-weight: bold; padding-top: 4px;"

# Generic labels
EMPTY_LABEL  = "color: " + COLOR_FAINT + "; font-size: " + FONT_XL + "; padding: 20px;"
LABEL_MUTED  = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + ";"
LIST_TITLE   = "font-weight: bold; font-size: " + FONT_XL + ";"
FIELD_LABEL  = "font-weight: 600;"
DETAIL_TITLE = "font-size: " + FONT_3XL + "; font-weight: bold;"
DETAIL_TEXT  = "color: " + COLOR_LIGHTGRAY + ";"
META_DIM     = "color: " + COLOR_GRAY + ";"
LOADING_TEXT = "color: " + COLOR_GRAY + "; font-style: italic;"

# Filter dialog / panel
FILTER_CHECKBOX  = "QCheckBox { color: " + COLOR_TEXT + "; }"
FILTER_ITEM_TEXT = "font-size: " + FONT_LG + ";"
ITEM_COUNT       = "font-size: " + FONT_MD + "; color: " + COLOR_FAINT + ";"
EXPAND_HINT      = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_XS + ";"
INFO_LABEL       = "color: " + COLOR_MUTED + "; font-size: " + FONT_LG + "; padding-left: 4px; padding-top: 4px;"

# Provider editor
META_HINT = "color: " + COLOR_MUTED + "; font-size: " + FONT_SM + ";"
STATUS_OK   = "color: " + COLOR_OK + "; font-size: " + FONT_LG + "; font-weight: 600;"
STATUS_WARN = "color: " + COLOR_WARN + "; font-size: " + FONT_LG + "; font-weight: 600;"
STATUS_ERR  = "color: " + COLOR_ERR + "; font-size: " + FONT_LG + "; font-weight: 600;"

# Provider editor — URL-test result badge (smaller than STATUS_*)
URL_BADGE         = "font-size: " + FONT_SM + "; font-weight: 600;"
URL_BADGE_TESTING = "font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
URL_BADGE_OK      = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_OK + ";"
URL_BADGE_ERR     = "font-size: " + FONT_SM + "; font-weight: 600; color: " + COLOR_ERR_2 + ";"
URL_REMOVE_BTN    = (
    "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_FAINT + "; border-radius: 3px; }"
    "QPushButton:hover { background: " + OVERLAY_ERR + "; }"
)

# Provider editor — icon picker
ICON_PICK_BTN = (
    "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid transparent;"
    " border-radius: 5px; padding: 0; }"
    " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
    " background: " + OVERLAY_BLUE_15 + "; }"
)
ICON_PICK_BTN_SELECTED = (
    "QPushButton { font-size: " + FONT_ICON + "; border: 2px solid " + COLOR_ACCENT_BLUE + ";"
    " border-radius: 5px; padding: 0;"
    " background: " + OVERLAY_BLUE_20 + "; }"
    " QPushButton:hover { border: 2px solid " + COLOR_ACCENT_BLUE + ";"
    " background: " + OVERLAY_BLUE_25 + "; }"
)
ICON_PICK_MAIN_BTN = (
    "QPushButton { font-size: " + FONT_ICON_LG + "; border: 1px solid " + OVERLAY_15 + ";"
    " border-radius: 6px; }"
    " QPushButton:hover { border: 1px solid " + COLOR_ACCENT_BLUE + ";"
    " background: " + OVERLAY_BLUE_10 + "; }"
)
ICON_PICK_POPUP = (
    "QFrame { background: " + OVERLAY_POPUP + ";"
    " border: 1px solid " + OVERLAY_18 + "; border-radius: 8px; }"
)

# Provider editor — top bar + footer buttons
PROVIDER_TOPBAR = "background: " + OVERLAY_04 + "; border-bottom: 1px solid " + OVERLAY_08 + ";"
LINK_BTN = (
    "QPushButton { border: none; color: " + COLOR_ACCENT_BLUE + "; font-size: " + FONT_XL + "; padding: 4px 8px; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_2 + "; }"
)
DELETE_BTN = (
    "QPushButton { color: " + COLOR_ERR_2 + "; border: 1px solid " + COLOR_ERR_2 + "; border-radius: 4px; padding: 6px 14px; }"
    "QPushButton:hover { background: " + OVERLAY_ERR_15 + "; }"
)
SAVE_BTN = (
    "QPushButton { background: " + COLOR_BTN_SAVE + "; color: " + COLOR_TEXT_HI + "; border-radius: 4px; padding: 6px 18px; font-weight: 600; }"
    "QPushButton:hover { background: " + COLOR_BTN_SAVE_HOVER + "; }"
    "QPushButton:disabled { background: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
)

# Category / prefix chips (version chips, similar-title chips, title-area prefix badge)
CATEGORY_CHIP = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_DIM + ";"
    " background: " + OVERLAY_05 + "; }"
)
CATEGORY_CHIP_SM = (
    "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_DIM + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 1px 6px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_DIM + ";"
    " background: " + OVERLAY_05 + "; }"
)
# Quality badge in the details pane title bar (amber/gold, next to language chip)
QUALITY_CHIP = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
    " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 2px 8px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_WARN + ";"
    " background: " + OVERLAY_08 + "; }"
)

# Genre chips — details pane metadata genre buttons (blue / link-like, flow-layout row)
GENRE_CHIP = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_ACCENT_BLUE_2 + ";"
    " border: 1px solid " + COLOR_FAINT + "; border-radius: 4px; padding: 2px 8px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_ACCENT_BLUE_2 + ";"
    " background: " + OVERLAY_BLUE_10 + "; }"
)

# Variant-count badge (content-collapse Slice 2) — bottom-left overlay on poster cards.
# Shown only when variant_count > 1; styled to be unobtrusive (muted + slight tint).
VARIANT_BADGE = (
    "background: " + OVERLAY_BLACK_55 + "; color: " + COLOR_DIM
    + "; border-radius: 3px; padding: 1px 4px;"
)

# Separators / surfaces
SEPARATOR_LINE = "background: " + COLOR_LINE + "; margin-top: 4px; margin-bottom: 2px;"
SEPARATOR_H    = "border: none; border-top: 1px solid " + COLOR_LINE + "; margin: 8px 0;"
SEP_DARK       = "color: " + COLOR_BORDER + "; margin-top: 4px; margin-bottom: 4px;"
CARD_BG        = "QWidget { background: " + OVERLAY_03 + "; border-radius: 6px; }"
HEADER_TINT    = "background-color: " + OVERLAY_05 + ";"
BG_TRANSPARENT = "background: transparent;"

# Exclusions chip (FilterChip in bottom nav bar) — three visual states.
# Active (teal): global exclusions are enabled and applying.
# Paused (amber): exclusions exist but are temporarily bypassed.
# Hover and pressed fill the chip solid so feedback is visible over the text, not just in
# the padding area. Text flips to the dark background color so contrast is maintained.
EXCL_CHIP_ACTIVE = (
    "QPushButton { background-color: " + OVERLAY_EXCLUSIONS_10 + "; color: " + COLOR_EXCLUSIONS_ACTIVE + ";"
    " border: 1px solid " + COLOR_EXCLUSIONS_ACTIVE + "; border-radius: 12px;"
    " padding: 6px 14px; font-weight: bold; }"
    "QPushButton:hover { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
    "QPushButton:pressed { background-color: " + COLOR_EXCLUSIONS_ACTIVE + "; color: " + COLOR_BG_SECTION + "; }"
)
EXCL_CHIP_PAUSED = (
    "QPushButton { background-color: " + OVERLAY_ORANGE_10 + "; color: " + COLOR_ACCENT_ORANGE + ";"
    " border: 1px solid " + COLOR_ACCENT_ORANGE + "; border-radius: 12px;"
    " padding: 6px 14px; font-weight: bold; }"
    "QPushButton:hover { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
    "QPushButton:pressed { background-color: " + COLOR_ACCENT_ORANGE + "; color: " + COLOR_BG_SECTION + "; }"
)

# Context filter chip — inline in the search bar when a details-pane filter is active
# (genre click, person click). Amber/orange so it's clearly distinct from a normal search.
CONTEXT_FILTER_CHIP = (
    "QWidget { background: " + OVERLAY_ORANGE_12 + ";"
    " border: 1px solid " + COLOR_ACCENT_ORANGE + ";"
    " border-radius: 4px; }"
)
CONTEXT_FILTER_CHIP_LABEL = (
    "color: " + COLOR_ACCENT_ORANGE + "; font-size: " + FONT_MD + "; font-weight: bold;"
    " background: transparent; border: none;"
)
CONTEXT_FILTER_CHIP_BTN = (
    "QPushButton { color: " + COLOR_ACCENT_ORANGE + "; font-size: " + FONT_MD + ";"
    " background: transparent; border: none; padding: 0 2px; font-weight: bold; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; }"
)

# Stream-diagnostics dialog
# Warning banner shown when a stream is already playing (single-connection providers
# can't be probed concurrently). Amber, bordered — distinct from the verdict headline.
DIAG_PLAYING_WARNING = (
    "color: " + COLOR_WARN + "; font-size: " + FONT_LG + ";"
    " border: 1px solid " + COLOR_WARN + "; border-radius: 4px; padding: 6px 10px;"
)
# Verdict headline base — color is interpolated at runtime per verdict (see dialog).
DIAG_VERDICT_HEADLINE = "font-size: " + FONT_2XL + "; font-weight: bold;"
# Plain-language summary paragraph under the headline.
DIAG_SUMMARY = "color: " + COLOR_LIGHTGRAY + "; font-size: " + FONT_LG + ";"
# Metrics block (throughput / bitrate / headroom / ttfb / codec / resolution).
DIAG_METRICS = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
# Recommended-args / placeholder line.
DIAG_RECOMMEND = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + "; font-style: italic;"
# Saved-confirmation line after applying tuning.
DIAG_SAVED = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

# Live playback-health readout in the bottom nav bar (buffer · speed · dropped frames).
# Dim/muted at-a-glance line; only visible while mpv is actively playing.
NAV_HEALTH = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"

# Discover / recommendation rows (EPG Watchlist tab)
# DISCOVER_REC_NAME        — channel name label in a recommendation row
# DISCOVER_REC_PILL_BTN    — "± Channel" and Play pill buttons (outlined accent pill)
# DISCOVER_REC_SKIP_BTN    — ghost "skip" dismiss button
# DISCOVER_REC_COUNT       — clickable "{n} matches" toggle label (pointing-hand cursor)
# DISCOVER_REC_MATCH_ROW   — compact programme sub-row revealed on expand
DISCOVER_REC_NAME = "font-size: " + FONT_LG + ";"
DISCOVER_REC_PILL_BTN = (
    "QPushButton { color: " + COLOR_ACCENT_HOVER + "; font-size: " + FONT_MD + ";"
    " border: 1px solid " + COLOR_ACCENT_HOVER + "; border-radius: 3px;"
    " padding: 1px 4px; background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; background: " + OVERLAY_BLUE_15 + "; }"
)
DISCOVER_REC_SKIP_BTN = (
    "QPushButton { color: " + COLOR_MUTED_2 + "; font-size: " + FONT_MD + ";"
    " border: none; background: transparent; }"
    "QPushButton:hover { color: " + COLOR_DIM + "; }"
)
DISCOVER_REC_COUNT = (
    "color: " + COLOR_ACCENT + "; font-size: " + FONT_MD + "; text-decoration: underline;"
)
DISCOVER_REC_MATCH_ROW = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + "; padding-left: 4px;"

# What's New dialog
WHATS_NEW_TITLE = (
    "font-size: " + FONT_2XL + "; font-weight: bold; color: " + COLOR_TEXT_HI + ";"
)
WHATS_NEW_META = (
    "font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
)
WHATS_NEW_ITEM = (
    "font-size: " + FONT_LG + "; color: " + COLOR_TEXT + ";"
)
WHATS_NEW_CARD = (
    "QWidget { background: " + OVERLAY_04 + "; border: 1px solid " + COLOR_LINE + ";"
    " border-radius: 6px; }"
)
# What's New carousel — navigation chevron buttons (large, monochrome, minimal border)
WHATS_NEW_NAV_BTN = (
    "QPushButton { font-size: " + FONT_3XL + "; color: " + COLOR_DIM + ";"
    " background: transparent; border: 1px solid " + COLOR_LINE + "; border-radius: 4px;"
    " padding: 2px 10px; }"
    "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_BORDER + "; }"
    "QPushButton:disabled { color: " + COLOR_FAINT + "; border-color: " + COLOR_LINE_DARK + "; }"
)
# What's New carousel — "1 / 4" position indicator label
WHATS_NEW_POS_LABEL = (
    "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
)

# Tag provenance + confidence chips (details pane — DR-0006 display)
# SOURCE-GIVEN chips: solid border + slightly brighter text → "provider said so"
TAG_CHIP_SOURCE = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_TEXT + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 1px 6px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_HI + "; border-color: " + COLOR_DIM + ";"
    " background: " + OVERLAY_05 + "; }"
)
# INFERRED chips: dashed border + muted text → "MetaTV guessed this"
TAG_CHIP_INFERRED = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_MUTED + ";"
    " border: 1px dashed " + COLOR_FAINT + "; border-radius: 4px; padding: 1px 6px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT + "; border-color: " + COLOR_BORDER + ";"
    " background: " + OVERLAY_05 + "; }"
)
# LOW-CONFIDENCE modifier: further dims any chip whose confidence < 0.5
TAG_CHIP_LOW_CONF_EXTRA = (
    "QPushButton { opacity: 0.6; color: " + COLOR_DISABLED + ";"
    " border-color: " + COLOR_LINE + "; }"
)
# Facet group label inside the Tags section
TAG_FACET_LABEL = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 + ";"
    " letter-spacing: 1px;"
)

# Events tab — segmented view-mode toggle (Timeline / By Network)
EVENTS_SEG_INACTIVE = (
    "QPushButton { color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px;"
    " padding: 3px 10px; background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT + "; border-color: " + COLOR_DIM + "; }"
)
EVENTS_SEG_ACTIVE = (
    "QPushButton { color: " + COLOR_TEXT_HI + "; font-size: " + FONT_MD + "; font-weight: 600;"
    " border: 1px solid " + COLOR_ACCENT + "; border-radius: 3px;"
    " padding: 3px 10px; background: " + OVERLAY_BLUE_15 + "; }"
)
# Event row group header (bold, non-selectable section label inside the list)
EVENTS_GROUP_HEADER = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_MUTED_2 + ";"
    " letter-spacing: 1px; padding: 4px 2px 2px 2px;"
)
# Time/availability hint label on each event row
EVENTS_TIME_HINT = "color: " + COLOR_DIM + "; font-size: " + FONT_MD + ";"
EVENTS_TIME_HINT_PASSED = "color: " + COLOR_FAINT + "; font-size: " + FONT_MD + ";"
EVENTS_TIME_ON_NOW = "color: " + COLOR_OK + "; font-size: " + FONT_MD + "; font-weight: 600;"

# WeightedTagCloud — role-named semantic constants
# Count badge next to each tag value (small, muted, non-clickable)
CLOUD_COUNT = "color: " + COLOR_MUTED_2 + "; font-size: " + FONT_SM + ";"
# State-mark prefix on include-state tags (green checkmark)
CLOUD_INCLUDE_MARK = "color: " + COLOR_OK + ";"
# State-mark prefix on exclude-state tags (orange/red ⊘)
CLOUD_EXCLUDE_MARK = "color: " + COLOR_WARN + ";"
# Header label for the tag cloud ("Genre · N values · sized by catalogue weight")
CLOUD_HEADER_LABEL = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"
# Sort-toggle and filter search controls in the cloud header
CLOUD_CTRL_BTN = (
    "QPushButton { font-size: " + FONT_SM + "; color: " + COLOR_MUTED + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px; padding: 1px 6px;"
    " background: transparent; }"
    "QPushButton:hover { color: " + COLOR_TEXT_2 + "; border-color: " + COLOR_DIM + "; }"
    "QPushButton:checked { color: " + COLOR_ACCENT + "; border-color: " + COLOR_ACCENT + "; }"
)
# "+N more" expand button at the tail of the cloud
CLOUD_MORE_BTN = (
    "QPushButton { border: none; background: transparent; color: " + COLOR_MUTED + ";"
    " font-size: " + FONT_MD + "; padding: 4px 2px; text-align: left; }"
    "QPushButton:hover { color: " + COLOR_ACCENT_BLUE_3 + "; }"
)

# ── Recipe builder (Broadcast Noir, task #56 slice 3) ──────────────────────────

# Left Pantry sidebar background
RECIPE_PANTRY_BG = "QWidget { background: " + COLOR_RECIPE_PANEL_BG + "; }"

# Pantry "THE PANTRY" and "SAVED RECIPES" section headers
RECIPE_PANTRY_HDR = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
    " letter-spacing: 2px; padding: 6px 4px 4px 4px;"
)

# A facet row in the pantry — idle state
RECIPE_FACET_ROW = (
    "QPushButton { border: none; background: transparent;"
    " color: " + COLOR_RECIPE_TEXT + "; font-size: " + FONT_MD + ";"
    " text-align: left; padding: 5px 8px; border-radius: 4px; }"
    "QPushButton:hover { background: " + OVERLAY_05 + "; }"
)

# A facet row in the pantry — selected/active state
RECIPE_FACET_ROW_SELECTED = (
    "QPushButton { border: none; background: " + OVERLAY_RECIPE_SELECTED + ";"
    " color: " + COLOR_RECIPE_TEXT + "; font-size: " + FONT_MD + ";"
    " text-align: left; padding: 5px 8px; border-radius: 4px;"
    " border-left: 2px solid " + COLOR_FACET_REGION + "; }"
)

# Center stage header (facet name + count subtitle)
RECIPE_STAGE_HDR = (
    "font-size: " + FONT_2XL + "; font-weight: bold; color: " + COLOR_RECIPE_TEXT + ";"
)
RECIPE_STAGE_SUBTITLE = (
    "font-size: " + FONT_MD + "; color: " + COLOR_RECIPE_MUTED + ";"
)

# Right recipe rail background
RECIPE_RAIL_BG = "QWidget { background: " + COLOR_RECIPE_PANEL_BG + "; }"

# "TONIGHT'S RECIPE" header
RECIPE_RAIL_HDR = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
    " letter-spacing: 2px; padding: 4px 0;"
)

# Auto-generated recipe name (editorial title)
RECIPE_EDITORIAL_NAME = (
    "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_RECIPE_TEXT + ";"
    " padding: 4px 0 8px 0;"
)

# Role label in the recipe ingredient list (BASE / IN / FROM / ON / ERA / FINISH / SET / OMIT)
RECIPE_ROLE_LABEL = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
    " letter-spacing: 1px;"
)

# An ingredient chip in the recipe rail (include)
RECIPE_INGREDIENT_CHIP = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_RECIPE_TEXT + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
    " background: " + OVERLAY_05 + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; }"
)

# An omit (exclude) chip — strikethrough appearance via text decoration
RECIPE_OMIT_CHIP = (
    "QPushButton { font-size: " + FONT_MD + "; color: " + COLOR_WARN + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 4px; padding: 2px 8px;"
    " background: transparent; text-decoration: line-through; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; }"
)

# YIELDS count label
RECIPE_YIELDS = (
    "font-size: " + FONT_LG + "; color: " + COLOR_RECIPE_TEXT + "; font-weight: 600;"
    " padding: 4px 0;"
)

# "Now plating" strip header
RECIPE_NOW_PLATING_HDR = (
    "font-size: " + FONT_SM + "; font-weight: bold; color: " + COLOR_RECIPE_MUTED + ";"
    " letter-spacing: 2px; padding: 4px 0 2px 0;"
)

# Save recipe button — present but disabled for slice 4
RECIPE_SAVE_BTN = (
    "QPushButton { background: " + COLOR_BTN_SAVE + "; color: " + COLOR_TEXT_HI + ";"
    " border-radius: 4px; padding: 6px 14px; font-weight: 600; font-size: " + FONT_MD + "; }"
    "QPushButton:disabled { background: " + COLOR_LINE + "; color: " + COLOR_MUTED_2 + "; }"
)

# Clear button — ghost style
RECIPE_CLEAR_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
    " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 6px 14px;"
    " font-size: " + FONT_MD + "; }"
    "QPushButton:hover { background: " + OVERLAY_05 + "; color: " + COLOR_TEXT_2 + "; }"
)


# ── Dev-only QA Testing Checklist — tri-state pass/fail ───────────────────────
# Pass/fail toggle buttons.  Each has an inactive (ghost) and active state; the
# active state tints to the OK (green) / ERR (red) palette so the chosen state
# reads at a glance.  Composed from existing tokens — no new colour literals.
QA_PASS_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
    " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 0 8px;"
    " font-size: " + FONT_MD + "; }"
    "QPushButton:hover { background: " + OVERLAY_GREEN_15 + "; color: " + COLOR_OK + "; }"
)
QA_PASS_BTN_ACTIVE = (
    "QPushButton { border: 1px solid " + COLOR_OK + "; background: " + OVERLAY_GREEN_15 + ";"
    " color: " + COLOR_OK + "; border-radius: 4px; padding: 0 8px;"
    " font-size: " + FONT_MD + "; font-weight: bold; }"
)
QA_FAIL_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
    " color: " + COLOR_MUTED + "; border-radius: 4px; padding: 0 8px;"
    " font-size: " + FONT_MD + "; }"
    "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
)
QA_FAIL_BTN_ACTIVE = (
    "QPushButton { border: 1px solid " + COLOR_ERR_2 + "; background: " + OVERLAY_ERR2_15 + ";"
    " color: " + COLOR_ERR_2 + "; border-radius: 4px; padding: 0 8px;"
    " font-size: " + FONT_MD + "; font-weight: bold; }"
)

# Fail comment box — revealed beneath a failed step.
QA_FAIL_NOTE_BOX = (
    "QPlainTextEdit { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_TEXT + ";"
    " border: 1px solid " + COLOR_ERR_2 + "; border-radius: 4px; padding: 4px;"
    " font-size: " + FONT_MD + "; }"
)

# Attachment chip — small removable label for a saved screenshot / log path.
QA_ATTACHMENT_CHIP = (
    "QPushButton { background: " + OVERLAY_05 + "; color: " + COLOR_DIM + ";"
    " border: 1px solid " + COLOR_BORDER + "; border-radius: 3px; padding: 0 6px;"
    " font-size: " + FONT_SM + "; }"
    "QPushButton:hover { background: " + OVERLAY_ERR2_15 + "; color: " + COLOR_ERR_2 + "; }"
)
QA_ATTACH_BTN = (
    "QPushButton { border: 1px solid " + COLOR_BORDER + "; background: transparent;"
    " color: " + COLOR_DIM + "; border-radius: 4px; padding: 0 8px;"
    " font-size: " + FONT_MD + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + "; }"
)

# "Newer build — re-test" amber hint (a step's stored sha differs from current HEAD).
QA_STALE_HINT = "color: " + COLOR_WARN + "; font-size: " + FONT_SM + "; font-weight: 600;"

# Failed-entry header badge — red flag on the entry title row.
QA_ENTRY_FAILED_TITLE = (
    "font-size: " + FONT_LG + "; font-weight: bold; color: " + COLOR_ERR_2 + ";"
)
QA_FAIL_BADGE = (
    "color: " + COLOR_ERR_2 + "; font-size: " + FONT_SM + "; font-weight: bold;"
    " padding-left: 4px;"
)
# "Addressed in PR #NNN — re-test" green badge on a failed step that a newer PR fixes.
QA_ADDRESSED_BADGE = (
    "color: " + COLOR_OK + "; font-size: " + FONT_SM + "; font-weight: bold;"
    " padding-left: 4px;"
)
