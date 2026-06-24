from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=49,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe 'Show all' — keeps loading past the first 500",
    items=(
        "The Recipe builder's 'Show all' browse page now pages through the FULL match set as you scroll — the old hard 500-card limit is gone, so a genre with thousands of matches is fully browsable.",
        "Opening 'Show all' is instant: it reuses the cards already on screen for page one and does no extra work up front, then fetches a screenful at a time only as you scroll near the bottom.",
        "Continuous loading works in BOTH grid and list view, so scrolling either one keeps pulling in more results toward the full match count.",
    ),
    test_steps=(
        "Open the Recipe chip → build a recipe (e.g. a broad Genre) with thousands of matches → click 'Show all'.",
        "Confirm it opens instantly showing about a screenful of cards (not a 500-card spike).",
        "Scroll down in GRID view → more cards load in continuously, well past 500, toward the full match count shown in the title.",
        "Switch to LIST view and keep scrolling → the list also keeps loading more rows past 500.",
        "Change the recipe (add/remove a tag) while the browse page is open → the grid resets to the new recipe and paging continues against it.",
    ),
)
