from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=385,
    version="0.41.0",
    date="2026-08-26",
    title="Reorder the sidebar, and headers that are just their names",
    items=(
        "Every sidebar section's ... menu now has Move up and Move down. The "
        "order you choose is remembered, and a section skips over any "
        "neighbour you have hidden rather than spending a click going nowhere.",
        "The icons beside the section names are gone. They repeated what the "
        "name already said, and the one job left for them - being a drag "
        "handle - went to the menu instead.",
        "Watch Alerts' status dot went with them. The filled +N chip in the "
        "same header says the same thing with a number in it.",
        "On History rows, the play-next-episode button now sits inside the "
        "time rather than outside it, so the times line up down the list.",
    ),
    test_steps=(
        "Open any sidebar section's ... menu - it should offer Move up and/or "
        "Move down. Recommended's refresh button keeps working as a direct "
        "click; right-click it for the move entries.",
        "Move a section down, then open its menu again - it must now offer "
        "Move up as well.",
        "The topmost section must not offer Move up, and the bottom one must "
        "not offer Move down.",
        "Hide a section in the middle, then move the one above it down - it "
        "should jump past the hidden one, not appear to do nothing.",
        "Restart the app - your order is restored.",
        "Check every section header: the name only, no icon beside it. Watch "
        "Alerts keeps its +N chip when something is new.",
        "Find a series episode in History with a play-next button - the time "
        "must be the rightmost thing on the row, and times should form a "
        "straight column down the list.",
    ),
)
