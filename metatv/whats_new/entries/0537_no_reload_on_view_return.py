from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=537,
    version="0.77.0",
    date="2026-09-02",
    title="Coming back to your search no longer re-runs it",
    items=(
        "Switching to Discover and back re-ran the whole search from scratch — "
        "785,551 rows re-filtered for a query you had not touched. Every trip "
        "away and back cost a full reload.",
        "The results are now kept when they still answer the query in the box. "
        "Change the search, or arrive with nothing loaded, and it queries as "
        "before.",
        "Nothing goes stale: adding, refreshing or removing a source already "
        "reloads the list wherever you are, changing a filter reloads it at "
        "the moment you change it, and likes, favourites and hides are applied "
        "to the row in place.",
    ),
    test_steps=(
        ("Search for something, switch to Discover, switch back. The results "
         "must still be there and must NOT flicker through a reload.",
         "view:list"),
        ("Now change the search term, switch away and back, and confirm the "
         "results match the new term.", "view:list"),
        ("Clear the search, switch away and back — you should get the full "
         "list, not the previous search's results.", "view:list"),
        ("Refresh a source from the sidebar while on another view, then return "
         "to the list and confirm the new content is there.", "view:list"),
    ),
)
