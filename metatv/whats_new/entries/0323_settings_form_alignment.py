"""What's New entry: the Settings pages now line up — one control column and
one checkbox edge per page — and the sidebar-section list no longer reserves
double the space it needs."""
from __future__ import annotations

from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=323,
    title="Settings pages line up now",
    items=(
        "Controls in Settings sat at three different left edges on the same "
        "page. Checkboxes in one group were flush with the group, checkboxes "
        "in the next were indented halfway across it, and the dropdowns moved "
        "left and right depending on how long the label above them happened "
        "to be. Every page now has one column for labels and one edge for "
        "checkboxes.",
        "The sidebar-section list on the Interface page reserved room for "
        "about eleven rows and only ever holds five, leaving a large empty "
        "box under the last one. It is sized to its contents now, which also "
        "makes the page noticeably shorter.",
        "Nothing moved that you choose — this is purely where things sit.",
    ),
    version="0.32.0",
    date="2026-08-22",
    test_steps=(
        "Open Settings → Interface and read down the page — \"Theme\", \"Row "
        "density\" and \"Platform names\" dropdowns all start at the same "
        "left edge, where before Theme's started further left than the other "
        "two.",
        "On the same page, check the checkboxes (\"Remember last search\", "
        "\"Show thumbnails in lists\", \"Refresh inactive sources…\", "
        "\"Automatically check for updates\") — they all share one left edge "
        "instead of three.",
        "Scroll to the Sidebar group — the list of sections ends just below "
        "\"History\" rather than leaving a tall empty box, and the Move "
        "Up/Move Down buttons sit right under it.",
        "Open Settings → Playback and confirm the same thing there: one "
        "column for the dropdowns and spin boxes, one edge for the "
        "checkboxes.",
    ),
)
