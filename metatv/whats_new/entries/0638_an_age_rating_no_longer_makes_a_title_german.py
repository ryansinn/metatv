from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=638,
    version="0.103.0",
    date="2026-09-08",
    title="An age rating no longer makes a title German",
    items=(
        "A title shaped \"18+ - Truly Naked (2026)\" was being filed under a "
        "country it has nothing to do with — German, Polish, French, Spanish — "
        "and picked up the matching language along with it. \"18+\" is an age "
        "rating, not a country code, so the title had no region of its own and "
        "quietly inherited whichever region its same-title siblings happened to "
        "use most.",
        "An age rating now blocks that inheritance outright, the same way a "
        "title that states its own language already did. No region is shown "
        "instead of a wrong one.",
        "The regions already stored are cleared on the next launch, together "
        "with the region and language tags derived from them. Titles that name "
        "a region themselves — \"DE - Truly Naked (2026)\" — are untouched.",
    ),
    test_steps=(
        "Find an \"18+ -\" title with English audio that previously showed a "
        "German (or Polish, French, Spanish) region — after this update its "
        "details pane shows no region at all.",
        "Check that same title's tags → the German (or Polish, French …) "
        "language tag derived from that region is gone.",
        "Open a \"DE - \" title → it still shows DE, and still carries its "
        "German language tag.",
        "Open the filter panel's region list → the counts for the affected "
        "regions have dropped by the number of age-rated titles that were "
        "wrongly filed there.",
    ),
)
