from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=482,
    version="0.64.0",
    date="2026-08-31",
    title="A stream that fails to open no longer takes the app with it",
    items=(
        "When a channel failed to start, MetaTV wrote a note about it so it "
        "could retry later — and wrote that note in the worst possible place: "
        "on the thread drawing the window, while something else was busy with "
        "the database. When those collided the app closed itself.",
        "That note is now written in the background. If it cannot be written "
        "at all, the note is lost and nothing else happens — remembering that "
        "a stream failed is not worth losing what you were doing.",
        "The same applies to removing or clearing entries in the retry list.",
    ),
    test_steps=(
        ("Play a channel you know is broken; you should get the failure "
         "notice and the app should stay open.", "view:list"),
        "Do it several times in a row while a refresh or enrichment is running "
        "in the background — still no crash.",
        "Open the retry list in the sidebar and confirm the failed channel is "
        "listed.",
        "Remove an entry and clear the list; both should work without freezing.",
    ),
)
