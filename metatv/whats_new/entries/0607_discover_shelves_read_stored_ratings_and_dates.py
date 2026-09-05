from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=607,
    version="0.99.0",
    date="2026-09-05",
    title="Discover shelves read stored ratings and dates",
    items=(
        "The top-rated and recently-added shelves no longer parse every "
        "title's provider payload on each open — the rating and date are "
        "stored and indexed at refresh, with a one-time library update "
        "filling them for titles already in the library.",
    ),
    test_steps=(
        "After upgrading, the Migration Center runs one \"raw field\" pass "
        "and finishes.",
        "Open Discover — the top-rated and recently-added shelves show the "
        "same titles as before, faster.",
    ),
)
