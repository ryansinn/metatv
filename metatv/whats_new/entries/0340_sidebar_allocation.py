from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=340,
    version="0.41.0",
    date="2026-08-23",
    title="Sidebar sections stop scrolling inside themselves",
    items=(
        "Sections had their own scrollbars inside the sidebar's scrollbar. "
        "Watch Alerts split its height four ways, each sub-group scrolling in "
        "about 35 pixels — a window too small to read through.",
        "A section now shows the rows that fit and ends with '+ N more →', "
        "which opens its full view. That is a consequence of how tall the "
        "section is, never a cap: drag it taller and it renders more rows.",
        "A section holding something new gets a little extra room, so Watch "
        "Alerts widens exactly when it has something to say and relaxes again "
        "when it does not.",
        "Section headers now show what CHANGED rather than what you own. "
        "'2 new' beats '13' — a count is inventory, and only one of those is "
        "worth a glance. When there is no news the count comes back.",
    ),
    test_steps=(
        "Open the sidebar and shrink Watch Alerts with the splitter → it "
        "shows the rows that fit and ends with '+ N more →'; no scrollbar "
        "appears inside the section.",
        "Drag that same section taller → more rows appear and the '+ N more' "
        "count drops. Drag it tall enough and the row disappears entirely.",
        "Click '+ N more →' → the section's full view opens in the centre "
        "panel, the same as its → arrow.",
        "Click an ordinary row in the same list → it acts on that row and "
        "does NOT open the full view.",
        "With unviewed alert matches present, check the Watch Alerts header → "
        "it reads 'N new' in the accent colour instead of a plain count, and "
        "the section is slightly taller than when it has no news.",
        "Clear those matches → the header goes back to a plain count and the "
        "section relaxes to its normal height.",
        "Collapse a section that has news → the header still tells you what "
        "is new without expanding it.",
        "Check History and Favorites → they show plain counts (nothing about "
        "them is ever 'new').",
    ),
)
