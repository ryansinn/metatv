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

# ── 1. Design tokens ────────────────────────────────────────────────────────────
# Text colors, light → faint
COLOR_TEXT_HI   = "#fff"        # emphasized / active text
COLOR_TEXT      = "#ccc"        # primary light text
COLOR_TEXT_2    = "#ddd"        # hover text
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
COLOR_BORDER    = "#444"
COLOR_LINE      = "#333"        # separators / panel bg
# Accent + status
COLOR_ACCENT       = "#2288dd"
COLOR_ACCENT_HOVER = "#55aaff"
COLOR_OK    = "#4CAF50"
COLOR_WARN  = "#FFC107"
COLOR_ERR   = "#F44336"
COLOR_GOLD  = "gold"
# White overlays (alpha)
OVERLAY_03 = "rgba(255,255,255,0.03)"
OVERLAY_05 = "rgba(255,255,255,0.05)"
OVERLAY_10 = "rgba(255,255,255,0.10)"
OVERLAY_18 = "rgba(255,255,255,0.18)"

# Type scale
FONT_XS  = "9px"
FONT_SM  = "10px"
FONT_MD  = "11px"
FONT_LG  = "12px"
FONT_XL  = "13px"
FONT_2XL = "14px"
FONT_3XL = "18px"


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
RATING_BTN = (
    "QPushButton { border: none; border-radius: 3px; padding: 2px 6px;"
    " font-size: " + FONT_XL + "; color: " + COLOR_MUTED + "; }"
    "QPushButton:checked { background: " + OVERLAY_18 + "; color: " + COLOR_TEXT_HI + "; }"
    "QPushButton:hover { background: " + OVERLAY_10 + "; color: " + COLOR_TEXT + "; }"
)

# Channel-name labels (EPG rows)
CHANNEL_NAME          = "font-size: " + FONT_MD + ";"
CHANNEL_NAME_LIVE     = "color: " + COLOR_TEXT + "; font-size: " + FONT_MD + ";"
CHANNEL_NAME_UPCOMING = "color: " + COLOR_DIM_2 + "; font-size: " + FONT_MD + ";"
CHANNEL_NAME_DIM      = "color: " + COLOR_MUTED + "; font-size: " + FONT_MD + ";"

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

# Separators / surfaces
SEPARATOR_LINE = "background: " + COLOR_LINE + "; margin-top: 4px; margin-bottom: 2px;"
SEPARATOR_H    = "border: none; border-top: 1px solid " + COLOR_LINE + "; margin: 8px 0;"
SEP_DARK       = "color: " + COLOR_BORDER + "; margin-top: 4px; margin-bottom: 4px;"
CARD_BG        = "QWidget { background: " + OVERLAY_03 + "; border-radius: 6px; }"
HEADER_TINT    = "background-color: " + OVERLAY_05 + ";"
BG_TRANSPARENT = "background: transparent;"
