from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=371,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar sections scroll their own content",
    items=(
        "Every sidebar section now scrolls internally when it holds more than "
        "it can show. Groups no longer draw on top of each other, and nothing "
        "is hidden without a way to reach it.",
        "Collapsing a group and expanding it again brings its rows back. It "
        "used to replace the whole group with a \"See all N more\" link that "
        "opened the manage dialog instead.",
        "Selecting a row uses the theme highlight again. A stylesheet applied "
        "after the selection colours was replacing them, so the sidebar fell "
        "back to a hard blue with unreadable text on it.",
        "Progress bars start at the right fill. They used to render nearly "
        "empty and jump to the correct amount up to thirty seconds later.",
    ),
    test_steps=(
        "Open a section with more entries than fit - it scrolls inside itself, "
        "and no heading or row is drawn over another.",
        "Collapse a group, then expand it - the rows come back.",
        "Click a row - the highlight is the theme accent and the row text stays "
        "readable. Check this in each theme.",
        "Open Watch Alerts while something is airing - the bar shows how far "
        "through the programme is immediately, not after a delay.",
    ),
)
