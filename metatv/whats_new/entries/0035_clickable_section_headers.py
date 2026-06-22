from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=35,
    version="0.8.0",
    date="2026-06-22",
    title="Click anywhere on a sidebar header to collapse/expand",
    items=(
        "Sidebar section headers (Sources, Favorites, Recommended, Alerts, New Episodes, "
        "Favorites, History, Queue) are now fully clickable — tap the title or any empty "
        "header area to toggle collapse, not just the small arrow button.",
        "Action buttons ('+', refresh, sort arrows) inside headers still perform their own "
        "actions as before — only background clicks on the header toggle the section.",
        "A pointing-hand cursor appears when hovering the header to signal it's interactive.",
    ),
)
