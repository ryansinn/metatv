from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=387,
    version="0.41.0",
    date="2026-08-27",
    title="Recommendations obey your exclusions",
    items=(
        "The Recommended rail was applying only some of your Global "
        "Exclusions. It now applies all of them, the same way the channel "
        "list, Discover and the tag counts already did.",
        "Most importantly the adult filter: it was never applied to "
        "Recommendations at all, so adult titles could appear there even with "
        "the filter on. Sources marked as entirely adult are excluded too.",
        "Also now applied: excluded content types (the AI-content layer), and "
        "the per-prefix exclusions - the rail was applying your excluded "
        "categories but not your excluded prefixes.",
    ),
    test_steps=(
        "Set Settings > Filtering to hide adult content, then open the "
        "Recommended sidebar section - no adult titles should appear.",
        "Mark a source as entirely adult and refresh Recommended - nothing "
        "from that source should be recommended.",
        "Exclude a language or prefix in Global Exclusions, then refresh "
        "Recommended - titles with that prefix must disappear from the rail.",
        "Exclude a content type (e.g. AI) and refresh - matching titles go.",
        "Clear the exclusions and refresh - the titles come back, so the rail "
        "is filtering rather than simply having fewer candidates.",
        "Compare the Recommended rail with Discover for the same exclusions - "
        "neither should show something the other hides.",
    ),
)
