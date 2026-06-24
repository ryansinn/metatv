from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=50,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe 'Show all' browses alphabetically",
    items=(
        "The Recipe 'Show all' grid (and the 'Now Plating' teaser) now lists "
        "matches alphabetically by title, so the full set is easy to scan and "
        "pages A→Z instead of in an opaque internal order.",
        "Side effect: quality/language variants of the same title (e.g. "
        "'Loki (US)' / 'Loki (2021)') now sit next to each other.",
    ),
    test_steps=(
        "Open the Recipe chip → add a Genre tag with lots of matches → 'Show all' → the grid is ordered A→Z by title.",
        "Scroll down → paging continues in alphabetical order with no repeats or gaps.",
        "Switch to List view → it shows the same alphabetical order.",
    ),
)
