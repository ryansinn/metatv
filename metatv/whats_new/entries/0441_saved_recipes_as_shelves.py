from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=441,
    version="0.55.0",
    date="2026-08-29",
    title="Saved recipes now appear as Discover shelves",
    items=(
        "A recipe you save is a named search you built and kept. It only "
        "existed on the Recipe screen's Saved tab.",
        "Each saved recipe is now also a shelf in Discover, listed with your "
        "own categories before the catalogue's own shelves.",
        "They behave like any other shelf: pin them to the top, collapse them, "
        "hide them, reorder them, or open See All.",
        "A recipe shelf shows exactly what the Recipe screen shows for the "
        "same recipe - same query, same exclusions - so it cannot drift.",
        "Rename or delete a recipe and its shelf follows. A recipe with no "
        "ingredients does not become a shelf containing your whole library.",
    ),
    test_steps=(
        "Save a recipe on the Recipe screen, then open Discover and confirm a "
        "shelf named 'Recipe: <your name>' appears.",
        "Confirm the titles on that shelf match what the Recipe screen shows "
        "for the same recipe.",
        "Pin the recipe shelf, reload Discover, and confirm it stays pinned.",
        "Turn off a source that contributed titles to the recipe and confirm "
        "they disappear from the shelf.",
        "Delete the recipe and confirm the shelf is gone on the next reload.",
    ),
)
