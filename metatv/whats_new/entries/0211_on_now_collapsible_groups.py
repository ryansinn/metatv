from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=211,
    version="0.18.0",
    date="2026-08-01",
    title="EPG On Now: collapsible category groups",
    items=(
        "On Now channels are now grouped under a \"{Category} (count)\" header "
        "row per prefix instead of one long flat list — click the arrow to "
        "collapse or expand a group.",
        "Groups default to expanded and remember whichever you've collapsed, "
        "across restarts.",
        "The Category dropdown still works the same way — it now hides whole "
        "groups instead of individual rows scattered through the list.",
        "Hiding a show/channel, playing, and right-click actions all still "
        "work exactly the same on the rows inside a group.",
    ),
    test_steps=(
        ("Open the On Now tab in EPG — channels are grouped under "
         "\"{Category} (count)\" header rows instead of one flat list.",
         "view:epg"),
        "Click a group's expand/collapse arrow — its rows hide/show; restart "
        "the app and reopen On Now — the group is still collapsed.",
        "Double-click a channel row inside a group — it plays normally; "
        "right-click it — the usual context menu (Hide, Play, Favorite, etc.) "
        "still appears.",
    ),
)
