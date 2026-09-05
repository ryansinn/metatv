from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=600,
    version="0.98.0",
    date="2026-09-05",
    title="A queued download starts after you close the player",
    items=(
        "A queued download now starts on its own after you close the "
        "player — the source's connection was still counted as in use "
        "until your next play, so the queue sat silent.",
        "The log now says once why a download is waiting and when it got "
        "the connection.",
    ),
    test_steps=(
        "Queue a download on a one-connection source while a stream plays, "
        "close the player — within about 15 seconds the download starts on "
        "its own.",
        "The log shows one \"waiting\" line and one \"granted\" line, not a "
        "line every two seconds.",
    ),
)
