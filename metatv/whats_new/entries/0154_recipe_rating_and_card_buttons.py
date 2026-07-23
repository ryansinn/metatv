from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=154,
    version="0.10.0",
    date="2026-07-22",
    title="Recipe: filter by rating, plus a slimmer recipe card",
    items=(
        "The Recipe builder gains its first non-tag ingredient: a RATING range "
        "slider in The Pantry. Drag the two handles to set a min–max band on the "
        "0–10 scale, or click the bar to set a floor in one move. Now Plating and "
        "the Yields count update live as you adjust it.",
        "Unrated content is handled sensibly: a minimum of 0 (full-left) keeps "
        "unrated titles in the results; raising the minimum above 0 hides them, so "
        "\"at least 7\" shows only genuinely-rated 7+ content.",
        "When a rating band is active it appears as a RATING line on the "
        "\"Tonight's Recipe\" card (e.g. \"RATING ≥ 7.0\" or \"RATING 6.0 – 8.0\"), "
        "right alongside the tag ingredients.",
        "Saved recipes now remember the rating band too — save a recipe, come back "
        "later, and its rating filter loads exactly as you left it. (Older saved "
        "recipes without a rating simply load as \"any rating\".)",
        "The \"Tonight's Recipe\" card was slimmed down: the × Clear control moved "
        "up beside the title and Save Recipe now sits alone at its natural width, "
        "so the recipe column no longer has to be as wide.",
    ),
    test_steps=(
        "Open the ✦ Recipe view → column 1 shows a RATING slider under The Pantry, "
        "and the \"Tonight's Recipe\" card has \"× Clear\" beside its title (not in "
        "a bottom button row) with \"Save Recipe\" alone at the bottom.",
        "Pick a tag ingredient (e.g. a genre), then drag the rating slider's left "
        "handle rightward → Now Plating narrows and the Yields count drops live as "
        "the minimum rises.",
        "Click the rating bar near 7 → the band becomes \"at least 7\" (min 7, max "
        "10) and the card shows a \"RATING ≥ 7.0\" line; results include only "
        "rated-7+ titles.",
        "Drag the minimum fully left to 0 → unrated titles reappear in the results "
        "(a floor of 0 includes unrated content), and the RATING line disappears "
        "when the band is the full 0–10 span.",
        "With a rating band and a tag set, click \"Save Recipe\" → it appears under "
        "SAVED RECIPES in The Pantry.",
        "Click \"× Clear\" (band resets to Any), then click the saved recipe → the "
        "ingredients AND the rating band load back exactly as saved.",
    ),
)
