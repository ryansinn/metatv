from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=709,
    version="0.149.0",
    date="2026-10-10",
    title="Cast, directors and alternate titles are indexed — and browsable",
    items=(
        "Cast, directing credits and alternate titles are now indexed once per name "
        "(a background task converts your existing library on first launch). "
        "Searching finds a title by any of its names, and people searches are faster.",
        "The tag cloud browser gains Cast and Directing, showing the most common names.",
        "Details lists alternate titles as 'Alternate title' rows with their source; "
        "the Cast section's 'Director' row now reads 'Directing' — sources list their "
        "whole directing department, assistant directors included.",
    ),
    test_steps=(
        "Launch — a background task 'Indexing cast, directors and titles' runs once.",
        "Open the Recipe / tag cloud browser — Cast and Directing tiles appear with the "
        "most common names; click a name — titles with that person are listed.",
        "Search 'Oskyldigt' — Innocent Blood is found (after opening it once so its "
        "alternate title is fetched).",
        "Filter panel opens as quickly as before (people and titles are not listed there).",
    ),
)
