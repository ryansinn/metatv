from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=474,
    version="0.63.0",
    date="2026-08-31",
    title="Your watch list is kept in the database",
    items=(
        "Watch-list keywords lived in the settings text file. They now live in "
        "the database alongside your favourites, ratings and queue, which is "
        "where the rest of what you have chosen already lives.",
        "Your existing keywords move across on the next launch. The settings "
        "file keeps its copy as a backup — nothing is deleted.",
        "Adding a keyword now ignores case, so \"NRL\" and \"nrl\" are one rule "
        "rather than two that fire on the same programme. Blank entries and "
        "duplicates are ignored instead of being added.",
        "If the database is briefly unavailable the watch list shows as empty "
        "and recovers on the next read, rather than taking the EPG view down "
        "with it.",
    ),
    test_steps=(
        ("Open the EPG watchlist and confirm the keywords you had are still "
         "there after the update.", "view:epg"),
        "Add a keyword, restart the app, and confirm it is still there.",
        "Try adding the same keyword again in different capitalisation — it "
        "should be refused as a duplicate.",
        "Remove a keyword and confirm it disappears from both the EPG "
        "watchlist and the Watch Alerts sidebar section.",
        "Add a programme to the watch list from the details pane bell and "
        "confirm it appears in the watchlist tab.",
    ),
)
