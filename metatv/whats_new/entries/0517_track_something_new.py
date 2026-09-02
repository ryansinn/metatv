from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=517,
    version="0.68.0",
    date="2026-09-02",
    title="Track Something New",
    items=(
        "The watchlist's one-line text box has been replaced by a "
        "\"Track Something New\" panel. A watchlist entry can now carry a "
        "match mode, several terms, exclusions and a search scope, and a "
        "single box could not express any of that.",
        "It is the same panel you get from Edit on an existing entry, so what "
        "you fill in when you add something is what you come back to when you "
        "change it.",
        "Match is now three visible choices — Phrase, All words, Any word — "
        "rather than a dropdown, and Look in shows Title and Description side "
        "by side. You can see what a entry is set to without opening anything.",
    ),
    test_steps=(
        ("Open EPG ▸ Watchlist and confirm the old text box is gone and a "
         "\"Track Something New\" button is in its place.", "view:epg"),
        ("Click it, fill in Include with two comma-separated terms, pick "
         "\"Any word\", add an exclusion, and click Track It. Confirm the "
         "entry appears with those settings.", "view:epg"),
        ("Click Edit on that entry and confirm the panel shows exactly the "
         "settings you chose.", "view:epg"),
        ("Click the already-selected Match option again and confirm it stays "
         "selected rather than turning off.", "view:epg"),
        ("Click Cancel on a half-filled panel and confirm it closes and is "
         "empty the next time you open it.", "view:epg"),
    ),
)
