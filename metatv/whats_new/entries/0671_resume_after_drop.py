from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=671,
    version="0.122.0",
    date="2026-09-11",
    title="A stream that drops mid-film resumes where it died",
    items=(
        "When a source drops the connection mid-play and the player runs out "
        "of buffer, the window used to close as if the film had ended — no "
        "message, no resume. It now resumes from a few seconds before the "
        "cut after a short wait, up to three times per play, and tells you "
        "when it stops trying.",
        "Live streams and a film that genuinely reaches its end are "
        "untouched — this only fires when a play that was clearly advancing "
        "ends well short of its own known duration.",
    ),
    test_steps=(
        "Play a VOD title, then cut the network for ~90s mid-play — the "
        "player closes when the buffer runs out, the status bar says "
        "\"the stream dropped at M:SS — resuming in 20s\", and it resumes "
        "near that spot.",
        "Let a short title play to the end — it closes normally with no "
        "resume.",
        "Close the player yourself mid-film — nothing resumes.",
    ),
)
