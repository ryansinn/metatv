from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=611,
    version="0.99.0",
    date="2026-09-05",
    title="Dead event channels can hide themselves",
    items=(
        "The \"hide dead events\" setting now works: a live channel the signal "
        "check has found dead N times in a row (N is the streak setting) leaves "
        "the channel list, search, Discover and recommendations until it comes "
        "back. Favourites, history and the queue still show it.",
    ),
    test_steps=(
        "Settings: turn on hide dead events with a streak of 1 — a channel the "
        "log shows probed dead disappears from the channel list and Discover.",
        "Turn it off — the channel returns.",
    ),
)
