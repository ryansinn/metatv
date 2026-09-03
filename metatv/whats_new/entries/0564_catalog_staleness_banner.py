from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=564,
    version="0.86.0",
    date="2026-09-03",
    title="The Sports view says when the catalog was last refreshed",
    items=(
        "A slim banner appears above the sport/league chips whenever your "
        "sources haven't been refreshed in over 6 hours: \"Catalog last "
        "refreshed N hours ago — fixture times and titles may be outdated.\"",
        "Click \"Refresh sources\" in the banner to refresh every stale source "
        "through the same queue the Sources view's Refresh All uses — no need "
        "to leave Sports.",
        "The banner hides itself while a refresh is already running, and "
        "disappears once your sources are fresh again.",
    ),
    test_steps=(
        "Open Sports with a source that hasn't refreshed in over 6 hours → the "
        "staleness banner appears above the lane chips, naming how long ago.",
        "Click \"Refresh sources\" on the banner → the refresh queue runs for "
        "your stale sources (same toast as Sources → Refresh All).",
        "After the refresh completes, reopen or stay on Sports → the banner "
        "disappears.",
    ),
)
