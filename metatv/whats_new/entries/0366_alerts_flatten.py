from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=366,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts is one flat list of groups",
    items=(
        "Watch Alerts had headings at two different levels drawn two different "
        "ways — collapsible buttons with carets for EPG, Movies & Series and "
        "Stream Monitoring, and a different style again for the groups inside "
        "them. They all look and behave the same now.",
        "The \"Movies & Series\" heading is gone. It sat above \"Watching "
        "for\" and \"Series\" while looking exactly like them, so a container "
        "read as a peer of its own contents. Those two groups are now "
        "top-level, giving four: EPG, Watching for, Series, Stream Monitoring.",
        "Every heading collapses when you click its title, and shows its count "
        "in the same style. No carets — the heading is the control.",
        "The busy indicator for series checks moved to the section header, "
        "beside Manage and +, since it reports on the whole section.",
    ),
    test_steps=(
        "Open Watch Alerts → four group headings at one level: EPG, Watching "
        "for, Series, Stream Monitoring. No carets, no parentheses, all the "
        "same size and colour, each with its count.",
        "Click each heading's title → its group collapses and expands. The "
        "count stays visible while collapsed.",
        "Start the app with monitored series → the spinner appears on the "
        "Watch Alerts header next to Manage and +, not on a group heading.",
        "Check no heading shows \"(N)\" in parentheses or a ⌄ / › caret.",
    ),
)
