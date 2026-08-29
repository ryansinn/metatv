from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=413,
    version="0.53.0",
    date="2026-08-28",
    title="Playing something no longer rebuilds lists it is not in",
    items=(
        "Starting playback rebuilt the whole Watch Queue and the whole "
        "Favorites list every time - re-reading both from the database and "
        "recreating every row.",
        "It did that whether or not the thing you played was in either of them, "
        "so switching between titles that are in neither still rebuilt both.",
        "Each list is now asked whether it is showing that title before it is "
        "rebuilt. If it is not, nothing happens.",
        "History still updates every time, because playing something is what "
        "adds it there.",
    ),
    test_steps=(
        "With a long Watch Queue, play something that is NOT in it. The queue "
        "should not flicker or reload.",
        "Play something that IS in the queue and confirm its row updates.",
        "Do the same with Favorites - unrelated playback should leave it alone.",
        "Confirm History still gains the title you just played.",
    ),
)
