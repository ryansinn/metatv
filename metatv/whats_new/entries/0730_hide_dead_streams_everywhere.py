from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=730,
    version="0.167.0",
    date="2026-10-19",
    title="\"Hide events with no signal\" now reaches filter counts and recipes",
    items=("With Settings → Signal checking → \"Hide events with no signal\" on, a live channel that keeps failing its "
           "signal check already disappeared from the list, Discover, Recommendations and "
           "Similar. It still counted in the filter panel's numbers and in Recipes, and could "
           "be picked for a recipe shelf. Those now leave it out too, so the counts match "
           "what you can actually open.",),
    test_steps=("Turn on Settings → Signal checking → \"Hide events with no signal\". In Recipes, pick a category your dead "
                "channels belong to (e.g. Sports) — the count and the results no longer include "
                "channels the list hides as dead; turn the setting off and the count goes back up.",),
)
