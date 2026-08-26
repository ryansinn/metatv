from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=370,
    version="0.41.0",
    date="2026-08-26",
    title="Sidebar section headers have a header again",
    items=(
        "Every sidebar section's header band was invisible — the tint it has "
        "always specified was never actually painted, so the header ran "
        "straight into the content below it. It sits on its own band now, in "
        "History, Favorites, Watch Queue and Watch Alerts alike.",
        "A section with something new shows a filled green pill in its header "
        "instead of turning its whole title green. Watch Alerts was the only "
        "section doing the latter, and it read as a different section every "
        "time something arrived.",
    ),
    test_steps=(
        "Look at any sidebar section - its title sits on a band slightly "
        "lighter than the content below, with a clear edge between them.",
        "Compare History, Favorites, Watch Queue and Watch Alerts - all four "
        "headers look the same.",
        "Trigger a new watch-alert match - the Watch Alerts title stays white "
        "and a green pill appears beside it, rather than the title going "
        "green with a bracketed count after it.",
        "Switch themes - the band and the pill follow the palette.",
    ),
)
