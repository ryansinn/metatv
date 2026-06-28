from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=95,
    version="0.9.0",
    date="2026-06-28",
    title="Genre/Pantry filter fixes confirmed — re-test the three flagged items",
    items=(
        "The dead singular 'Sport' genre facet (it could show 450+ count but return "
        "nothing on filter) is gone — both 'Sport' and 'Sports' raw provider values now "
        "fold into one canonical 'Sports' facet, so the count and the filter always "
        "agree. Existing data is re-tagged automatically on launch; user-curated tags "
        "are never touched.",
        "The Recipe Builder's center facet-value list (Genre, Language, etc. — which can "
        "hold 400+ values) has a search box with an inline × clear button to narrow the "
        "visible values live as you type.",
        "The Recipe Builder's Pantry sidebar filter (which narrows the facet list — "
        "Genre/Region/etc.) has an inline × clear button, and the recipe 'Clear' button "
        "now also empties that Pantry filter text so the full facet list reappears.",
    ),
    test_steps=(
        "Open the filter panel Genre section and confirm only 'Sports' (plural) appears — "
        "the old singular 'Sport' entry is gone; select 'Sports' and confirm sports "
        "channels appear (non-zero results, count matches filter).",
        "Open the Recipe Builder (✦ chip), select Genre from The Pantry, type a few "
        "letters in the center 'Filter…' box and confirm the genre value list narrows "
        "live; click the inline × and confirm all values reappear.",
        "In the Recipe Builder Pantry sidebar, type 'lang' in the filter box and confirm "
        "only matching facets remain; click the inline × and confirm all facets reappear.",
        "With text in the Pantry filter box, click the recipe 'Clear' button and confirm "
        "the Pantry filter text is emptied and every Pantry facet row is visible again.",
    ),
    addresses=(
        "flagged:c9c90e3a-e685-481c-844d-d4b7b82e8acb",
        "flagged:ac64cd01-ebc1-4ed4-9c55-6ee178bb637b",
        "flagged:4510b6eb-9e0e-4164-8ad6-641bdc4850bb",
    ),
)
