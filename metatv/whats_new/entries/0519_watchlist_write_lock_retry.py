from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=519,
    version="0.69.0",
    date="2026-09-02",
    title="Removing a watchlist entry no longer fails while the guide is busy",
    items=(
        "Adding, editing or removing a watchlist entry while an EPG pass is "
        "writing used to fail outright — the entry stayed in the list and you "
        "got an error saying it could not be removed. The write now waits for "
        "the database and goes through.",
        "It waits on the background thread, so nothing about the app is "
        "slower, and quitting still does not wait for it.",
        "A genuine failure is still reported immediately rather than retried, "
        "so a real problem does not turn into a silent delay.",
    ),
    test_steps=(
        ("Open EPG ▸ Watchlist while a guide refresh is running and remove an "
         "entry. Confirm the entry disappears and no \"could not be removed\" "
         "message appears.", "view:epg"),
        ("Add an entry during the same window and confirm it appears and is "
         "still there after restarting the app.", "view:epg"),
        ("With nothing else running, remove an entry and confirm it is still "
         "instant — the retry must not have added a delay to the normal case.",
         "view:epg"),
    ),
)
