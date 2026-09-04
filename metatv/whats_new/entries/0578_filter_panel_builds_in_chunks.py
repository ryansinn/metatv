from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=578,
    version="0.93.0",
    date="2026-09-03",
    title="The filter sidebar no longer freezes the app while it builds",
    items=(
        "The Includes filter panel used to build all nine of its facet "
        "sections (Language, Region, Platform, Quality, Category, Genre, "
        "Subtitle, Dub, Audio Format) in one synchronous pass — measured a "
        "2,037ms main-thread stall at launch. Each section now builds on its "
        "own turn of the event loop, the same chunked-build mechanism "
        "already used by the Watch Queue and Discover shelves.",
        "A fast source refresh that arrives while the panel is still "
        "populating cancels the in-flight build cleanly instead of leaving "
        "stale or duplicated rows behind.",
    ),
    test_steps=(
        "Launch the app with a large library and scroll/click around the "
        "channel list while the filter panel is populating → no "
        "multi-second freeze, the UI stays responsive.",
        "Restart the app after saving some filter selections (e.g. only a "
        "few languages/genres checked) → once the filter panel finishes "
        "populating, those selections are still restored correctly.",
    ),
)
