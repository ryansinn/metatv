from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=48,
    version="0.9.0",
    date="2026-06-24",
    title="Recipe Builder — 'Show all' for the full match list",
    items=(
        "The Recipe builder's 'Now Plating' teaser now has a 'Show all →' link next to the match count — click it to open a full-results browse page (mirrors Discover's 'See all →').",
        "The browse page reuses Discover's grid: lazy poster loading on scroll, a grid/list toggle, and a filter box — so you can sift the whole match set, not just the first 60.",
        "Clicking a card opens its details, double-click plays it, and the Recipe chip always brings you straight back to building your recipe.",
    ),
    test_steps=(
        "Open the Recipe chip → add a tag so 'Now Plating' shows matches → a 'Show all →' link appears next to the count.",
        "Click 'Show all →' → the full browse grid loads with more than 60 cards (it shows the recipe name + total match count as the title).",
        "Scroll the browse grid → more cards and poster images load in as you go.",
        "Use the grid/list toggle and type in the filter box → the view switches modes and narrows to titles matching your text.",
        "Single-click a card → its details open; double-click a card → it starts playing.",
        "Click the Recipe chip again (or the browse 'Back' link) → you land back on the recipe constructor, not the browse page.",
    ),
)
