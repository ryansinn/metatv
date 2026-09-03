from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=567,
    version="0.89.0",
    date="2026-09-03",
    title="The Sports staleness banner now refreshes just the live catalog",
    items=(
        "\"Refresh sources\" on the Sports staleness banner used to run the "
        "full multi-minute catalog refresh (live + VOD + series). Measured on "
        "real sources, the live catalog alone (fixtures and channels) is a "
        "single request that returns in a few seconds — the banner now "
        "fetches only that, so clicking it is fast.",
        "VOD and series are untouched by this refresh; they still update on a "
        "regular source refresh (Sources → Refresh, or Settings → Content's "
        "own \"Auto-refresh\" schedule).",
        "The banner's staleness age and tooltip now describe the live catalog "
        "specifically, so it's clear what \"Refresh sources\" is and isn't "
        "doing.",
        "A source currently streaming is still always skipped and retried "
        "later — this never interrupts playback.",
    ),
    test_steps=(
        "Open Sports with a source that hasn't refreshed in over 6 hours → the "
        "staleness banner appears, now reading \"Live catalog last refreshed "
        "N hours ago\"; hover it for the tooltip explaining it's live channels "
        "and fixtures only, usually a few seconds per source.",
        "Click \"Refresh sources\" on the banner → the refresh completes in "
        "seconds rather than minutes, and the banner disappears once the "
        "sources are fresh again.",
        "Check the source's VOD/series content before and after clicking the "
        "banner's refresh → unchanged, proving VOD/series were not re-fetched.",
    ),
)
