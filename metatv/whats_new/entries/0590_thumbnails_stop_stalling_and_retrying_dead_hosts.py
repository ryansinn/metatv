from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=590,
    version="0.95.0",
    date="2026-09-04",
    title="Thumbnails stop stalling, and stop retrying dead hosts",
    items=(
        "Requesting a poster no longer reads the disk on the interface "
        "thread — a 3-second stall seen on Discover cards is gone.",
        "An image host that would not connect is remembered across "
        "relaunches for a few hours, instead of costing a fresh 5-second "
        "timeout per row every single launch.",
        "Thumbnail connections give up after about 3 seconds instead of 5.",
    ),
    test_steps=(
        "Open Discover with many un-cached posters → the view stays "
        "responsive while they fill in.",
        "With a source whose image host is down, note the log's "
        "'cooldown: skipping' lines, then relaunch → the host is skipped "
        "immediately, with no new connect timeouts for it.",
    ),
)
