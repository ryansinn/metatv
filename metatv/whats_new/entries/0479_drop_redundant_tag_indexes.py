from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=479,
    version="0.64.0",
    date="2026-08-31",
    title="About 220 MB back, and nothing lost",
    items=(
        "The tag store kept two extra copies of information it already had. "
        "Each was a narrower version of a bigger index sitting right beside it, "
        "so every question they could answer was already answered — they just "
        "took up room and slowed down every tag write.",
        "On this library that is roughly 220 MB. Nothing is removed from what "
        "you can search or filter by; the same lookups run the same way.",
        "The space comes back the next time the database compacts rather than "
        "the instant you update.",
    ),
    test_steps=(
        ("Open Browse and use the tag filters — genres, languages, quality. "
         "Everything should filter exactly as before, at the same speed.",
         "view:browse"),
        "Open a title's details and confirm its tags still show.",
        "Restart the app and confirm it starts normally — the change is applied "
        "once during startup.",
    ),
)
