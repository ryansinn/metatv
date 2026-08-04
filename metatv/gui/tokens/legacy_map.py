"""Legacy ``COLOR_*``/``OVERLAY_*`` names → the DTCG token layer.

Migration debt, deliberately explicit and countable. ~140 token names predate
the Radix/DTCG restructure (#295) and are referenced across ~1800 lines of role
constants plus every widget, so renaming them all at once would be one
unreviewable diff. Instead the names survive and their VALUES now come from the
scale.

Two kinds of entry:

``"on-surface.default"``
    A SEMANTIC ROLE. Preferred: the meaning travels between themes, so a palette
    that chooses different scales still gets the right thing here. New code
    should use these role names directly and never add to this table.

``"{neutral.7}"``
    A raw scale coordinate, for the long tail where no role exists yet. Neutral
    references use the palette's OWN neutral scale (``$scales.neutral``) rather
    than a hard-coded hue, so they follow a theme swap.

How this table was built: every legacy value was SNAPPED to its nearest Radix
step — hue family chosen first (so a saturated green can never land on a grey,
which a plain RGB distance did do), then the step by lightness, with alpha
tokens matched on alpha level rather than RGB. The snap independently
rediscovered Radix's published step semantics: borders landed on step 7,
app backgrounds on step 2, text on 11/12. The hand-tuned palette had been
approximating the structure Radix formalises, which is the strongest evidence
that adopting it is not a change of intent.

Shrink this file. Every entry converted to a role name is one less coordinate.
"""

from __future__ import annotations

LEGACY_TOKEN_MAP: dict[str, str] = {

    "COLOR_ACCENT": "primary.default",
    "COLOR_ACCENT_BLUE": "{indigo.12}",
    "COLOR_ACCENT_BLUE_2": "{indigo.12}",
    "COLOR_ACCENT_BLUE_3": "{indigo.12}",
    "COLOR_ACCENT_BLUE_LIGHT": "{blue.11}",
    "COLOR_ACCENT_BROWN": "{orange.8}",
    "COLOR_ACCENT_GREEN": "{green.11}",
    "COLOR_ACCENT_HOVER": "primary.hover",
    "COLOR_ACCENT_ORANGE": "{amber.12}",
    "COLOR_ACCENT_ORANGE_FADED": "{amber.12}",
    "COLOR_ACCENT_PURPLE": "{purple.10}",
    "COLOR_ACCENT_TEAL": "{teal.11}",
    "COLOR_AUDIO_BADGE": "{yellow.7}",
    "COLOR_BANNER_YEL_BG": "{yellow.4}",
    "COLOR_BANNER_YEL_BG_HOVER": "{yellow.5}",
    "COLOR_BANNER_YEL_BORDER": "{yellow.8}",
    "COLOR_BANNER_YEL_BORDER_HOVER": "{yellow.8}",
    "COLOR_BANNER_YEL_FG": "{yellow.11}",
    "COLOR_BG_BAR": "surface.base",
    "COLOR_BG_CARD": "surface.container",
    "COLOR_BG_DEEP": "surface.dim",
    "COLOR_BG_SECTION": "surface.base",
    "COLOR_BORDER": "outline.default",
    "COLOR_BTN_SAVE": "{indigo.9}",
    "COLOR_BTN_SAVE_HOVER": "{indigo.9}",
    "COLOR_DIM": "{neutral.10}",
    "COLOR_DIM_2": "{neutral.11}",
    "COLOR_DISABLED": "on-surface.disabled",
    "COLOR_ERR": "state.err",
    "COLOR_ERR_2": "{red.9}",
    "COLOR_ERR_MUTED": "{red.8}",
    "COLOR_EXCLUSIONS_ACTIVE": "{teal.9}",
    "COLOR_FACET_COLLECTION": "meta.collection",
    "COLOR_FACET_DECADE": "{indigo.11}",
    "COLOR_FACET_DUB": "{cyan.11}",
    "COLOR_FACET_FORMAT": "{amber.12}",
    "COLOR_FACET_GENRE": "facet.genre",
    "COLOR_FACET_LANGUAGE": "facet.language",
    "COLOR_FACET_PLATFORM": "facet.platform",
    "COLOR_FACET_QUALITY": "{blue.8}",
    "COLOR_FACET_REGION": "facet.region",
    "COLOR_FACET_SUBTITLE": "{teal.10}",
    "COLOR_FAINT": "on-surface.placeholder",
    "COLOR_GOLD": "{amber.9}",
    "COLOR_GOLD_LIGHT": "{yellow.9}",
    "COLOR_GRAY": "{neutral.9}",
    "COLOR_LIGHTGRAY": "{neutral.11}",
    "COLOR_LINE": "outline.subtle",
    "COLOR_LINE_DARK": "{neutral.4}",
    "COLOR_MOOD_CURIOUS_BG": "{green.10}",
    "COLOR_MOOD_CURIOUS_FG": "{green.6}",
    "COLOR_MOOD_DISLIKE_BG": "{red.9}",
    "COLOR_MOOD_EXPLORE_BG": "{green.4}",
    "COLOR_MOOD_EXPLORE_FG": "{green.11}",
    "COLOR_MOOD_LIKE_BG": "{green.11}",
    "COLOR_MOOD_LIKE_FG": "{green.8}",
    "COLOR_MOOD_NOTFORME_BG": "{red.8}",
    "COLOR_MOOD_NOTFORME_FG": "{red.10}",
    "COLOR_MOOD_TRASH_BG": "{red.5}",
    "COLOR_MOOD_WATCH_BG": "{blue.4}",
    "COLOR_MUTED": "{neutral.10}",
    "COLOR_MUTED_2": "{neutral.8}",
    "COLOR_NOTIFY_ERR_BG": "{red.2}",
    "COLOR_NOTIFY_ERR_BORDER": "{red.11}",
    "COLOR_NOTIFY_INFO_BG": "{indigo.2}",
    "COLOR_NOTIFY_OK_BG": "{green.3}",
    "COLOR_NOTIFY_OK_BORDER": "{green.12}",
    "COLOR_NOTIFY_WARN_BG": "{amber.3}",
    "COLOR_NOTIFY_WARN_BORDER": "{amber.12}",
    "COLOR_OK": "state.ok",
    "COLOR_ON_ACCENT": "primary.on",
    "COLOR_PPV_ACCENT": "{orange.10}",
    "COLOR_PREF_NUDGE": "{green.11}",
    "COLOR_QUALITY_FHD": "quality.fhd",
    "COLOR_QUALITY_HD": "quality.hd",
    "COLOR_QUALITY_LIVE": "quality.live",
    "COLOR_QUALITY_OUTLINE_FHD": "quality.fhd",
    "COLOR_QUALITY_OUTLINE_HD": "quality.hd",
    "COLOR_QUALITY_OUTLINE_LIVE": "quality.live",
    "COLOR_QUALITY_OUTLINE_RAW": "quality.raw",
    "COLOR_QUALITY_OUTLINE_UHD": "quality.uhd",
    "COLOR_QUALITY_RAW": "quality.raw",
    "COLOR_QUALITY_UHD": "quality.uhd",
    "COLOR_RECIPE_BG": "{indigo.1}",
    "COLOR_RECIPE_MUTED": "{neutral.11}",
    "COLOR_RECIPE_MUTED_2": "{indigo.5}",
    "COLOR_RECIPE_PANEL_BG": "{indigo.1}",
    "COLOR_RECIPE_TEXT": "{neutral.12}",
    "COLOR_RED_BRIGHT": "{red.11}",
    "COLOR_SURFACE_LIGHT": "surface.container",
    "COLOR_SURFACE_LIGHT_2": "surface.container-high",
    "COLOR_SURFACE_LIGHT_3": "surface.container-max",
    "COLOR_TEXT": "on-surface.default",
    "COLOR_TEXT_2": "on-surface.default",
    "COLOR_TEXT_HI": "on-surface.strong",
    "COLOR_TEXT_LOW": "on-surface.default",
    "COLOR_WARN": "state.warn",
    "OVERLAY_03": "{neutralA.2}",
    "OVERLAY_04": "{neutralA.2}",
    "OVERLAY_05": "{neutralA.2}",
    "OVERLAY_08": "{neutralA.3}",
    "OVERLAY_10": "{neutralA.4}",
    "OVERLAY_15": "{neutralA.5}",
    "OVERLAY_18": "{neutralA.6}",
    "OVERLAY_40": "{neutralA.9}",
    "OVERLAY_55": "{neutralA.10}",
    "OVERLAY_ACCENT_35": "{primaryA.7}",
    "OVERLAY_ACCENT_50": "{primaryA.8}",
    "OVERLAY_BLACK_30": "{neutralA.8}",
    "OVERLAY_BLACK_55": "{neutralA.10}",
    "OVERLAY_BLACK_60": "{neutralA.11}",
    "OVERLAY_BLACK_65": "{neutralA.11}",
    "OVERLAY_BLUE_10": "{primaryA.3}",
    "OVERLAY_BLUE_15": "{indigoA.2}",
    "OVERLAY_BLUE_20": "{indigoA.3}",
    "OVERLAY_BLUE_25": "{indigoA.3}",
    "OVERLAY_BLUE_40": "{indigoA.5}",
    "OVERLAY_BLUE_60": "{indigoA.7}",
    "OVERLAY_BLUE_LT_25": "{indigoA.3}",
    "OVERLAY_BROWN_08": "{amberA.2}",
    "OVERLAY_ERR": "{redA.3}",
    "OVERLAY_ERR2_15": "{redA.3}",
    "OVERLAY_ERR_15": "{redA.3}",
    "OVERLAY_EXCLUSIONS_10": "{tealA.3}",
    "OVERLAY_EXCLUSIONS_18": "{tealA.4}",
    "OVERLAY_GREEN_15": "{greenA.4}",
    "OVERLAY_GREEN_40": "{greenA.7}",
    "OVERLAY_ORANGE_10": "{amberA.3}",
    "OVERLAY_ORANGE_12": "{amberA.3}",
    "OVERLAY_ORANGE_18": "{amberA.4}",
    "OVERLAY_PLATFORM_BADGE": "{blueA.6}",
    "OVERLAY_POPUP": "{indigoA.11}",
    "OVERLAY_RECIPE_SELECTED": "{amberA.2}",
    "OVERLAY_SELECTION": "{primaryA.5}",
    "OVERLAY_TEAL_15": "{greenA.4}",
    "OVERLAY_WARN_06": "{amberA.2}",
}
