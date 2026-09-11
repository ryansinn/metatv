from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=672,
    version="0.122.0",
    date="2026-09-11",
    title="The search box says what it searches",
    items=(
        "The header search box read \"Search titles\", which undersold it: a "
        "search matches titles, categories and cast/crew. It now reads "
        "\"Search content — name, category, cast…\" on the Search view and "
        "\"Search content — press Enter to search\" everywhere else, with a "
        "tooltip that lists what it covers.",
    ),
    test_steps=(
        "On the Search view the box reads \"Search content — name, category, cast…\"; "
        "switch to Discover and it reads \"Search content — press Enter to search\".",
        "Hover the box: the tooltip names titles, categories, cast and crew.",
        "Type an actor's name and press Enter from Discover — results include "
        "titles matched on cast, under their own heading.",
    ),
)
