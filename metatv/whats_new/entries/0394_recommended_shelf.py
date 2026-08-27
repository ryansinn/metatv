from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=394,
    version="0.51.0",
    date="2026-08-27",
    title="Discover gains a Recommended shelf, and two surfaces start obeying your adult filter",
    items=(
        "Discover now opens with a 'Recommended for You' shelf, matching the "
        "Recommended section in the sidebar. It appears once you have rated or "
        "watched enough for the engine to have an opinion.",
        "Building it turned up a live bug. The Recommendations dashboard and "
        "the Explore trail map were not applying your adult filter at all - "
        "not a weakened version of it, none of it - so adult titles could "
        "appear in both with the filter switched on.",
        "They were also ignoring your excluded content types (the AI-content "
        "layer), and the trail map was ignoring per-prefix exclusions. The "
        "sidebar was fixed for this in an earlier release; these two surfaces "
        "were missed.",
        "All four surfaces now resolve their exclusions in one shared place, "
        "so an exclusion added in future applies everywhere at once instead of "
        "reaching whichever surfaces someone remembered.",
    ),
    test_steps=(
        "Open Discover - 'Recommended for You' should be the first shelf, with "
        "cards matching what the Recommended sidebar section shows.",
        "Turn the adult filter ON in Settings, then open the Recommendations "
        "dashboard - no adult titles should appear. This is the bug: before "
        "this change they did.",
        "With the filter still on, open a title's Explore trail map and check "
        "its recommendations for the same thing.",
        "Exclude a prefix in Global Exclusions, then check the trail map's "
        "recommendations no longer include titles carrying it.",
        "Exclude a content type (e.g. AI) and confirm it disappears from the "
        "Discover shelf, the dashboard and the sidebar alike.",
        "Click 'See all' on the Recommended shelf - the drill-down should "
        "apply the same exclusions as the shelf itself.",
    ),
)
