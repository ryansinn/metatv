from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=500,
    version="0.64.0",
    date="2026-09-01",
    title="Settings → Interface was twice as long as every other page",
    items=(
        "The Interface page had grown to hold seven separate groups and needed "
        "a lot of scrolling — it was nearly double the height of any other "
        "settings page, and the sidebar list inside it got taller every time a "
        "new sidebar section was added.",
        "Sidebar and Watch Alerts now have pages of their own. Interface keeps "
        "Search, Appearance, Channel List, Sources and Updates, and is now "
        "about the same size as Metadata and Recommendations.",
        "Nothing moved out of reach: every setting is where its name says it "
        "is, and the left-hand list tells you which page you are on.",
    ),
    test_steps=(
        ("Open Settings and confirm Interface fits without a long scroll.",
         "view:list"),
        "Confirm Sidebar and Watch Alerts appear as their own rows in the "
        "left-hand list, below Interface.",
        "Change a sidebar section's order on the new Sidebar page, click OK, "
        "and confirm the sidebar updates.",
        "Change the watchlist recheck interval on the Watch Alerts page, "
        "reopen Settings, and confirm it kept the value.",
    ),
)
