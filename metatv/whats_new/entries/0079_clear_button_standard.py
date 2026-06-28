from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=79,
    version="0.9.0",
    date="2026-06-28",
    title="Inline × clear button standardized on all filter/search boxes",
    items=(
        "All filter and search text boxes now show a built-in × button (inline, "
        "appears only when there is text) — no more separate external × button next to the field.",
        "Affected boxes: channel-list search, EPG Browse search, EPG On-Now search, "
        "Discover Browse filter, Recipe Pantry filter.",
    ),
    test_steps=(
        "Open the Recipe chip → type a word in the Pantry 'Filter…' box → an inline × "
        "appears inside the right edge of the box → clicking it clears the box and "
        "restores all facets.",
        "Type text into the main channel-list search bar → inline × appears → click it "
        "→ channel list resets to unfiltered.",
        "Open the EPG view → Browse tab → type in 'Search programmes…' → inline × "
        "appears → click it → programme list resets.",
        "Open the EPG view → On Now tab → type in 'Search On Now…' → inline × appears "
        "→ clicking it clears the search.",
        "Open Discover → Browse a shelf → type in the 'Filter…' box → inline × appears "
        "→ clicking it clears the filter.",
    ),
)
