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
