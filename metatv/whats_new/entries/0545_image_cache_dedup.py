from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=545,
    version="0.82.0",
    date="2026-09-02",
    title="Image cache: no more duplicate downloads",
    items=(
        "Posters and channel art no longer download twice when several "
        "views ask for the same image at once.",
        "A queued fetch that finally runs after sitting behind a busy "
        "download queue now checks disk first — if the file already "
        "landed there, it skips the network instead of re-downloading it.",
        "An unreachable image host is now remembered for ten minutes "
        "instead of being re-timed-out every few seconds — a dead host "
        "was eating about 15 seconds of image-loading time at every "
        "launch.",
    ),
    test_steps=(
        "Cold-launch with a library whose provider has a dead image host: "
        "poster loading no longer stalls repeatedly on it — the log shows "
        "one timeout per host, then 'cooldown: skipping' lines.",
        "Open a view that shows the same poster in several places at "
        "once: the log shows a single download for that URL, not two or "
        "three.",
    ),
)
