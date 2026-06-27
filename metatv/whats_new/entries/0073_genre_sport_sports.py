from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=73,
    version="0.9.0",
    date="2026-06-27",
    title="Fixed dead 'Sport' genre facet — now folds into 'Sports'",
    items=(
        "The singular 'Sport' genre entry (which could show 450+ count in the filter "
        "panel or recipe builder) has been eliminated. Both 'Sport' and 'Sports' raw "
        "provider values now fold into a single 'Sports' facet, consistent with how "
        "the category and platform sections already used the plural form.",
        "Existing data is automatically updated on next launch — no manual refresh "
        "needed. Only machine-generated tags are rewritten; any user-curated tags "
        "are never touched.",
    ),
    test_steps=(
        "Open the filter panel Genre section — only 'Sports' (plural) appears for "
        "sports content; the old singular 'Sport' entry is gone.",
        "Select 'Sports' in the Genre filter — sports movies/series appear in the "
        "channel list (non-zero results).",
        "Open the Recipe builder and find the Genre facet cloud — 'Sports' shows a "
        "count; no separate 'Sport' entry appears alongside it.",
        "Click 'Sports' in the recipe builder — matching channels populate 'Now "
        "Plating' with sports content.",
    ),
)
