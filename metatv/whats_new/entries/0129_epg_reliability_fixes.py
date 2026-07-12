from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=129,
    version="0.9.0",
    date="2026-07-11",
    title="EPG guide: accurate times and more reliable refresh",
    items=(
        "EPG guide data now refreshes one source at a time, avoiding a 'database "
        "is locked' error that could make a source's guide fail to update when two "
        "sources refreshed at once.",
        "Program times in the Discover 'upcoming matches' rows and the EPG status "
        "line now show in your local timezone — previously they could be off by your "
        "UTC offset (or a day, near midnight).",
        "Channels with blank or placeholder names no longer accidentally borrow an "
        "unrelated channel's guide.",
        "Watchlist 'starting soon' alerts now fire for sources configured with a "
        "custom EPG URL (not just auto-built ones).",
    ),
    test_steps=(
        "With two sources that have EPG, trigger a guide refresh (or relaunch): both "
        "sources' guides populate without a 'database is locked' error in the logs.",
        "Open Discover with an upcoming watchlist match: the time shown on the match "
        "row matches the program's real local start time (not shifted by your UTC "
        "offset).",
        "Open the EPG view and check the 'data through <day> <time>' status line: the "
        "day and time are in your local timezone.",
    ),
)
