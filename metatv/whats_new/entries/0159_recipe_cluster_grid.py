from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=159,
    version="0.10.0",
    date="2026-07-30",
    title="Recipe builder, redesigned — browse every facet at a glance, then save the recipe",
    items=(
        "The Recipe builder (✦ chip) now opens on a masonry grid of mini tag-clouds "
        "— one tile per browse facet (Genre, Region, Language, Decade, Collection, "
        "Quality, Platform, Subtitle) — packed to fill the space, so you can build a "
        "filter across facets without clicking through them one at a time.",
        "Click any tag to add it to your recipe and stay on the grid; click a facet's "
        "heading to drill into its full cloud. The Decade tile reads as a "
        "chronological strip (oldest → newest).",
        "Your recipe is now a slim one-line \"sentence\" between the grid and the "
        "results — the ingredient chips, the live title count, and Save / Clear — "
        "instead of a tall side column.",
        "\"Matching Content\" is a Discover-style horizontal shelf of what your recipe "
        "matches, with a \"Show all →\" button that opens the full results grid.",
        "New \"Saved\" tab: click ✦ Save to keep a recipe, give it a name, and it "
        "reappears as a card (with a live match count) that reloads into the builder "
        "in one click — or delete it. Saved recipes persist across restarts.",
    ),
    test_steps=(
        "Open the ✦ Recipe chip: the center is a masonry grid of mini tag-clouds — "
        "one tile per browse facet (Genre, Region, Language, Decade, Collection, "
        "Quality, Platform, Subtitle) — packed with no gaps and NO 'More facets' "
        "collapse. There is no Audio Format tile.",
        "Confirm the Decade tile reads oldest → newest (e.g. 1980s before 2020s), and "
        "Region chips are CODES (ES/US/DE), not country names.",
        "Click a tag in the Genre tile, then one in the Region tile: both appear as "
        "chips in the one-line 'RECIPE' bar below the grid, the '→ N titles' count "
        "updates, and the view stays on the grid.",
        "The 'MATCHING CONTENT' shelf below fills with result cards; click 'Show all "
        "→' → the full-results grid takes over; the 'Build recipe' link returns to "
        "the builder with your ingredients intact.",
        "Click '✦ Save' → the Saved tab opens showing a card with your recipe's name, "
        "a live title count, and its ingredient tags. Rename it inline.",
        "Switch back to Recipe, click Clear, then open Saved and click the card → it "
        "reloads your ingredients into the builder. Delete the card → it disappears. "
        "Restart the app and open Saved → your remaining saved recipes are still there.",
    ),
)
