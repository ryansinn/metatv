from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=390,
    version="0.41.0",
    date="2026-08-27",
    title="The 'hidden by filters' count told you the wrong number",
    items=(
        "The gold bar above the channel list reports how many results each "
        "filter layer is hiding. The figure for the tag filters counted rows "
        "that a language, region, quality or platform filter had already "
        "removed, so it read higher than the truth - three where the answer "
        "was one, in the case now covered by a test.",
        "It works by re-running the same query with one filter lifted and "
        "subtracting. That only means something if every OTHER filter is held "
        "equal, and the comparison query had been hand-copied from the main "
        "one with nine of its filters left out.",
        "All four queries now share one set of filters and change exactly one "
        "of them, and a test reads the code to make sure it stays that way.",
    ),
    test_steps=(
        "Open the channel list and apply a language filter (Global Exclusions "
        "or the filter panel's language section).",
        "With that still on, apply a tag filter from the filter panel - the "
        "gold bar should appear with a 'hidden by filters' count.",
        "Click the reveal on that segment. The number of results that appear "
        "must match the number the bar reported. Before this fix the bar "
        "over-reported, so more was promised than appeared.",
        "Remove the language filter and repeat with the tag filter alone - the "
        "count should be the same as the number revealed.",
        "Repeat with a region, quality or platform filter in place of the "
        "language one; each was affected the same way.",
        "Check the 'unavailable' and 'hidden by keyword' segments still count "
        "and reveal correctly - they share the same query now.",
    ),
)
