from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=520,
    version="0.69.0",
    date="2026-09-02",
    title="Sidebar sections always show every entry now",
    items=(
        "The \"Use 'Show N more' rows instead of scrollbars\" setting is gone, "
        "along with the mode it turned on. Sidebar sections show every entry "
        "and scroll, the way every other list in the app does.",
        "It was off by default, and the reason given for keeping it — that you "
        "could reveal the hidden rows by scrolling — was not true: hidden rows "
        "were hidden, and the \"Show N more\" row was the only way to reach "
        "one. It was least useful to exactly the people it was for.",
        "Sections are still resized by dragging the handle between them.",
    ),
    test_steps=(
        ("Open Settings ▸ Interface and confirm the \"Show N more\" checkbox is "
         "gone.", "view:list"),
        ("Look at a sidebar section with more entries than fit — Watch Queue or "
         "History. Every entry should be present and the section should "
         "scroll; there should be no \"Show N more\" or \"See all N more\" row "
         "at the bottom.", "view:list"),
        ("Drag the handle between two sections and confirm resizing still "
         "works in both directions.", "view:list"),
        ("Open Watch Alerts, collapse one of its groups, and confirm it stays "
         "collapsed as the section is resized.", "view:list"),
    ),
)
