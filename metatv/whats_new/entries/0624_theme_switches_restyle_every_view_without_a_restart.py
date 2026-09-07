from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=624,
    version="0.103.0",
    date="2026-09-07",
    title="Theme switches restyle every view without a restart",
    items=(
        "Switching theme now re-themes whatever is already on screen — "
        "Recipes, Discover, Preferences, the EPG, the Sources manager and "
        "the provider editor all follow the new palette in place.",
        "The filter panel's section headers, accent stripes, row labels and "
        "checkboxes change with it, including sections built after the app "
        "started.",
        "Behind this: every widget now registers its style when it is built, "
        "so a switch reaches it automatically. The old hand-maintained list "
        "of what to restyle could only ever cover what someone remembered to "
        "add to it, which is why a few corners kept needing a restart.",
    ),
    test_steps=(
        "Open Settings → Appearance and switch theme from Midnight to "
        "Daylight → the channel list, sidebar and details pane all change "
        "immediately, with no restart.",
        "Open Recipes (both the Recipe and Saved tabs), switch theme → the "
        "tab pills, the recipe bar, the tag cloud header and the saved-recipe "
        "panel all take the new palette; the active tab pill still reads as "
        "active.",
        "Open Discover, switch theme → the header, Manage button and the "
        "'See all' drill-down chrome re-theme in place.",
        "Open the EPG (Watchlist, On Now, Browse and Events tabs), switch "
        "theme → every label, notice and stats footer follows; the Events "
        "tab's Timeline/By Network toggle keeps the right button highlighted.",
        "Open Preferences/Recommended, switch theme → the Mix caption and the "
        "Excluded / Version Preferences toggles re-theme in place.",
        "Open Sources, select a source to show the provider editor, switch "
        "theme → the Add button, the footer, Save/Delete and the icon picker "
        "(open its palette popup) all re-theme in place.",
        "Open the filter panel, expand a facet section, switch theme → the "
        "section header background, its coloured left stripe, the row labels "
        "and the 'Only' buttons all change with no restart.",
        "Switch theme from the Style menu instead of Settings → the same "
        "result, and re-picking the theme that is already active does "
        "nothing.",
    ),
)
