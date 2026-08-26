from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=376,
    version="0.41.0",
    date="2026-08-26",
    title="Watch Alerts rows now elide like every other list",
    items=(
        "Long titles in Watch Alerts no longer run off the edge. They shorten "
        "in the middle with a \"...\" and show the full name on hover - the "
        "same way History, Favorites and the Watch Queue have always done it.",
        "Watch Alerts rows are now built by the same shared builder every "
        "other sidebar section uses, so chips, spacing and alignment match "
        "exactly - and its chips no longer keep the old colours after you "
        "switch themes.",
        "No visible change otherwise: row heights, the left marker column, "
        "the quality chip beside the title, the progress bars and the group "
        "counts all render as before.",
    ),
    test_steps=(
        "Open Watch Alerts with a long programme or channel name - the title "
        "shortens in the MIDDLE with a \"...\" rather than being cut off at "
        "the panel edge.",
        "Hover that title - a tooltip shows the full name.",
        "Do the same with a long keyword rule under Movies - it elides too.",
        "Check a live programme's airings - the quality chip still sits right "
        "after the channel name and the progress bar still sits at the right.",
        "Hover a live row - the play triangle appears in the left column and "
        "nothing else on the row moves.",
        "Switch theme (Settings - Interface - Theme) with Watch Alerts open - "
        "every chip repaints in the new palette, including the green \"+N\" "
        "pill on a series with new episodes.",
        "Collapse and expand EPG, Movies, Series and Stream Monitoring - each "
        "group keeps its count and its rows.",
        "Right-click a keyword rule and a monitored series - both context "
        "menus still open with their full set of actions.",
    ),
)
