from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=157,
    version="0.10.0",
    date="2026-07-30",
    title="Cross-language movie & series variants now share one card (TMDb id)",
    items=(
        "When your provider tags a movie or series with a TMDb id, MetaTV now "
        "uses it to recognise the same production across languages, sources and "
        "qualities — so the Spanish, English and 4K copies collapse onto a single "
        "card instead of cluttering the grid with near-duplicates.",
        "The card's \"×N\" badge and the details-pane \"Other Versions\" list both "
        "count every variant that shares the id, so you can still reach each "
        "language/quality copy from one place.",
        "Searching still finds every copy by its own on-screen title — a variant "
        "that got folded into another card is never hidden from search.",
        "Movies and series that happen to share the same TMDb number stay "
        "separate (TMDb numbers films and TV independently), so unrelated titles "
        "never merge by accident.",
    ),
    test_steps=(
        "Open Browse/Discover on a source whose movies carry TMDb ids: a title "
        "available in several languages (e.g. an ES and an EN copy) now appears as "
        "ONE card with a \"×2\" (or higher) badge instead of separate cards.",
        "Click that card → details pane → \"Other Versions\": every language/quality "
        "variant that shares the id is listed there.",
        "Type one variant's on-screen title into search (e.g. the Spanish name), "
        "then the other's (the English name): each search still returns the title — "
        "the folded variant is never lost from search.",
        "Confirm a movie and a series that share the same TMDb number remain two "
        "distinct cards (they are never merged together).",
    ),
)
