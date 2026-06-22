from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=19,
    version="0.7.0",
    date="2026-06-21",
    title="Discover genre shelves — no more duplicates or cross-bleed",
    items=(
        "Fixed: genre strings with HTML entities (e.g. 'Action &amp; Adventure') "
        "no longer create a duplicate shelf alongside the real 'Action & Adventure' one.",
        "Fixed: the 'Science Fiction' shelf no longer pulls in 'Sci-Fi & Fantasy' titles, "
        "and 'Action' no longer bleeds into 'Action & Adventure'. "
        "Compound genres and their components stay in their own distinct shelves.",
        "Existing shelves with encoded genre names are silently migrated on first launch — "
        "your pinned, expanded, and hidden preferences are preserved.",
    ),
)
