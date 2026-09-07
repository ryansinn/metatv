from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=618,
    version="0.101.0",
    date="2026-09-07",
    title="Excluded categories leave every Discover shelf",
    items=(
        "A category you exclude under Global Exclusions is now absent from "
        "Recently Added, Top Rated, genre, decade, actor and collection "
        "shelves too, not only from the categories list.",
    ),
    test_steps=(
        "Exclude a user category that holds recent titles → Discover's "
        "Recently Added no longer shows them.",
        "Un-exclude it → they return.",
    ),
)
