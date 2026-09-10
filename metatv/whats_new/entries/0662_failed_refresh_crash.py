from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=662,
    version="0.119.0",
    date="2026-09-09",
    title="Fixed a crash when a sidebar list refreshed while it was still drawing",
    items=(
        "The Watch Queue builds its rows in small batches so a long queue does "
        "not freeze the window. If a refresh arrived while a build was still "
        "running AND that refresh's own database query failed, the list was "
        "emptied but the half-finished build kept going — and finished by "
        "reaching for rows that no longer existed, which took the whole app "
        "down.",
        "Any refresh now stops an in-progress build before it clears the list, "
        "whether the refresh succeeded or failed. Database contention during "
        "background enrichment made the failing-query half of this quite "
        "reachable.",
    ),
    test_steps=(
        "Open the sidebar with a large Watch Queue (hundreds of entries) and "
        "let background enrichment run; switch views and back repeatedly so the "
        "queue re-refreshes while it is still drawing. The app must not exit.",
        "Confirm the queue still fills in normally and the find-in-queue filter "
        "box still hides non-matching rows after a refresh completes.",
        "Confirm a queue that fails to load still shows its \"Couldn't load "
        "watch queue\" row rather than an empty list.",
    ),
)
