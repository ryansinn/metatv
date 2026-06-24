from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=61,
    version="0.9.0",
    date="2026-06-24",
    title="Discover shelves + Other Versions collapse on stored content identity",
    items=(
        "Discover shelves now deduplicate on the stored content_key (computed once at "
        "ingestion) rather than re-deriving a title+year pair at display time — the same "
        "identity that Recipe / Show-All / tag results use.",
        "A shelf card's ×N variant badge and the details-pane 'Other Versions / Other "
        "Sources' section now use the same identity key, so the counts always agree.",
        "Details-pane Other Versions for movies and series use an indexed content_key "
        "SQL lookup instead of a Python-side normalize_title scan — faster for large "
        "libraries.",
        "Null-key rows (pre-backfill channels) fall back to the previous normalize_title "
        "matching so nothing breaks before the background backfill finishes.",
        "Similar Titles and Recommendations are deliberately unchanged — they use a richer "
        "runtime fingerprint that will be updated in a later wave.",
    ),
    test_steps=(
        "Open Discover (🧭 chip) and find a shelf where the same movie or series appears "
        "from two or more sources — previously they showed as separate cards. Confirm they "
        "now appear as ONE card with a ×N badge showing the number of sources.",
        "Click the collapsed card to open the details pane. In the 'Other Versions / Other "
        "Sources' section, confirm the count of listed sources matches the ×N number shown "
        "on the card.",
        "Confirm a same-named but clearly different production (e.g. a 2024 reboot vs the "
        "original 1994 film — both present in your library) is NOT wrongly merged into one "
        "card (they have different content_keys that encode the year).",
        "With a source disabled in Settings → Sources, open Discover and confirm variants "
        "from that disabled source are no longer counted in the ×N badge or listed in Other "
        "Versions.",
    ),
)
