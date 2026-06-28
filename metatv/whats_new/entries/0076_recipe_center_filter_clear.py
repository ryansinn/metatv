from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=76,
    version="0.8.0",
    date="2026-06-28",
    title="Recipe Builder: center facet filter now has a clear affordance",
    items=(
        "The center facet-value filter box (Genre, Language, etc.) now shows"
        " an inline × button to clear it in one click.",
        "Clicking '× Clear' under YIELDS now also resets the center filter text"
        " so all facet values reappear.",
    ),
    test_steps=(
        "Open the Recipe Builder (✦ chip) → select Genre from The Pantry"
        " → type a few letters in the center 'Filter…' box"
        " → an inline × appears inside the field; click it"
        " → the filter clears and all Genre values reappear.",
        "Type text in the center facet filter, then click '× Clear' under YIELDS"
        " → the center filter text is also cleared and all facet values are restored.",
    ),
)
