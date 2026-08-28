from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=407,
    version="0.53.0",
    date="2026-08-28",
    title="Discover shelves show a way to reach the rest of the row",
    items=(
        "Each shelf in Discover scrolls sideways through more titles than fit "
        "on screen. The only sign of that was a scrollbar.",
        "On macOS scrollbars only appear while you are scrolling and then fade "
        "away, so a shelf sat there looking like it held six titles when it "
        "held forty.",
        "Shelves now have a chevron at each end. They appear only when there is "
        "more to see in that direction, and each one moves the row by a "
        "screenful.",
        "They are a real control rather than a styled scrollbar, so they look "
        "and behave the same on every platform.",
    ),
    test_steps=(
        "Open Discover and find a shelf with more titles than fit across the "
        "window. A chevron should sit at the right edge of the row.",
        "Click it - the row should move by about one screenful, and a matching "
        "chevron should appear on the left.",
        "Scroll to the end of the row and confirm the right chevron disappears "
        "rather than offering to scroll past the last title.",
        "Find a shelf whose titles all fit and confirm it shows no chevrons.",
        "Change the Discover zoom and confirm the chevrons stay centred and "
        "still move a screenful.",
    ),
)
