from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=495,
    version="0.64.0",
    date="2026-09-01",
    title="Clicking an already-highlighted row did nothing",
    items=(
        "If a row was already highlighted, clicking it would not open it. With "
        "a single search result — highlighted automatically — there was no way "
        "to get its details at all, and the panel could sit showing something "
        "else entirely.",
        "The same applied in History, the Watch Queue, Favorites, "
        "Recommendations, Discover, the EPG lists and Preferences: the row you "
        "wanted was often the one already selected.",
        "A click now always opens the row it lands on, everywhere.",
        "Closing a part-watched film also refreshes its details, so Resume "
        "appears straight away instead of after visiting it from another list.",
    ),
    test_steps=(
        ("Search for something with exactly one result and click it — the "
         "details panel must show that item.", "view:list"),
        ("Click the already-highlighted row in History, then the same row "
         "again, and confirm the panel updates both times.", "view:history"),
        "Watch part of a film, close the player, and confirm the details panel "
        "offers Resume without navigating away and back.",
    ),
)
