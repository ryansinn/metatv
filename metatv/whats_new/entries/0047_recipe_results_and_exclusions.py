from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=47,
    version="0.9.0",
    date="2026-06-23",
    title="Recipe Builder — real results & your exclusions",
    items=(
        "'Now Plating' now shows real poster cards instead of dead text chips — single-click a card to open its details, double-click (or use the play affordance) to watch it.",
        "The Recipe builder now honors your Global Exclusions everywhere — the Pantry counts, the tag cloud, YIELDS, and the results shelf all hide content you've globally banished (and show it again when global filtering is paused).",
    ),
    test_steps=(
        "Build a recipe and confirm 'Now Plating' shows real poster cards (not text chips).",
        "Single-click a result card → details pane opens for that item.",
        "Double-click a result card (or use play affordance) → stream starts playing.",
        "With a Global Exclusion active, build a recipe → excluded content must be absent from the Pantry counts, tag cloud, and result cards.",
        "Pause global filtering → excluded content reappears in results.",
    ),
)
