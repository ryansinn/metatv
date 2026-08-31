from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=471,
    version="0.60.0",
    date="2026-08-31",
    title="Collapsible rows can be opened from the keyboard",
    items=(
        "Some rows that expand when clicked — a filter group in Global "
        "Exclusions, a row in the trail map, the \"N matches\" line in the EPG "
        "watchlist — could only be opened with the mouse. They can now be "
        "reached with Tab and opened with Space or Enter.",
        "The rest of the app is unchanged: buttons already worked this way, "
        "and clickable posters and chips deliberately stay off the Tab route "
        "so the tab order remains short enough to be useful.",
    ),
    test_steps=(
        ("Open Global Exclusions, press Tab until a filter group header is "
         "focused, then press Space — the group should expand.",
         "settings:interface"),
        "Press Space again on the same header and confirm it collapses.",
        ("In the EPG watchlist, Tab to a \"N matches\" line and press Enter — "
         "the matches should expand.", "view:epg"),
        "Confirm clicking those same rows with the mouse still works exactly "
        "as before.",
        "Tab through the channel list and confirm posters and chips are not "
        "now tab stops — the tab order should not have grown.",
    ),
)
