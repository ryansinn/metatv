from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=449,
    version="0.56.0",
    date="2026-08-29",
    title="The log's first line now says which build wrote it",
    items=(
        "Startup logged \"MetaTV starting...\" and nothing about which MetaTV.",
        "It now reads \"MetaTV (main 6e60fd9) starting - v0.56.0\", or the "
        "stamped build id in a packaged app.",
        "This matters more than it used to. Every push ships to you, so a "
        "version number alone no longer separates two builds a week apart - a "
        "log pasted into a report has to name the commit that produced it.",
        "It reuses the same identity the title bar shows, so the window and the "
        "log cannot disagree about what is running.",
    ),
    test_steps=(
        "Launch from a terminal and confirm the first MetaTV line names the "
        "version and the branch/commit.",
        "Confirm it matches what the title bar and Help > About report.",
    ),
)
