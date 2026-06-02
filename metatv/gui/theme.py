"""Shared Qt stylesheet constants.

Import from here — never define inline duplicates. If you need a variant,
add a new constant here rather than copy-pasting a string.
"""

PLAY_BTN = (
    "QPushButton { background: transparent; border: none; color: #2288dd;"
    " font-size: 13px; padding: 0 2px; }"
    "QPushButton:hover { color: #55aaff; }"
)

PLAY_BTN_SMALL = (
    "QPushButton { background: transparent; border: none; color: #2288dd;"
    " font-size: 12px; padding: 0; }"
    "QPushButton:hover { color: #55aaff; }"
)

CHANNEL_NAME = "font-size: 11px;"
CHANNEL_NAME_LIVE = "color: #ccc; font-size: 11px;"
CHANNEL_NAME_UPCOMING = "color: #999; font-size: 11px;"
CHANNEL_NAME_DIM = "color: #888; font-size: 11px;"

TIME_LABEL = "color: #aaa; font-size: 11px;"
TIME_LABEL_UPCOMING = "color: #777; font-size: 11px;"

SECTION_HDR = (
    "font-size: 10px; font-weight: bold; color: #666;"
    " letter-spacing: 1px; padding: 6px 4px 4px 4px;"
)

CARD_BG = "QWidget { background: rgba(255,255,255,0.03); border-radius: 6px; }"

SEPARATOR_LINE = "background: #333; margin-top: 4px; margin-bottom: 2px;"
SEPARATOR_H = "border: none; border-top: 1px solid #333; margin: 8px 0;"

EMPTY_LABEL = "color: #555; font-size: 13px; padding: 20px;"
LABEL_MUTED = "color: #666; font-size: 11px;"
LIST_TITLE = "font-weight: bold; font-size: 13px;"

SECTION_HDR_LG = (
    "font-size: 11px; font-weight: bold; color: #666;"
    " letter-spacing: 1px; padding: 4px 0;"
)
SECTION_HINT = "color: #555; font-size: 11px; padding: 2px 0 6px 0;"
SECTION_ITEM = "color: #555; font-size: 11px; padding: 4px 0;"

CLEAR_BTN = "border: none; color: #777; font-size: 10px;"
CLOSE_BTN = "color: #666; border: none; background: transparent; font-size: 14px;"
EYE_BTN = "border: none; padding: 0; color: #aaa;"

HINT_XS = "color: #888; font-size: 10px;"
LABEL_XS = "color: #666; font-size: 9px;"
FIELD_LABEL = "font-weight: 600;"
TEXT_SM = "font-size: 12px;"
STATUS_OK = "color: #4CAF50; font-size: 12px; font-weight: 600;"
STATUS_ERR = "color: #F44336; font-size: 12px; font-weight: 600;"

SEP_DARK = "color: #444; margin-top: 4px; margin-bottom: 4px;"
SECTION_TITLE_SM = "font-size: 12px; font-weight: bold; padding-top: 4px;"
LABEL_MUTED_MD = "color: #888; font-size: 12px; padding-left: 4px; padding-top: 4px;"

BG_TRANSPARENT = "background: transparent;"
RATING_BTN = (
    "QPushButton { border: none; border-radius: 3px; padding: 2px 6px;"
    " font-size: 13px; color: #888; }"
    "QPushButton:checked { background: rgba(255,255,255,0.18); color: #fff; }"
    "QPushButton:hover { background: rgba(255,255,255,0.10); color: #ccc; }"
)
