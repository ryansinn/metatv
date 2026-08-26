from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=361,
    version="0.41.0",
    date="2026-08-26",
    title="\"Show N more\" makes the section taller instead of leaving it",
    items=(
        "The \"+ N more →\" row at the bottom of a sidebar section opened the "
        "Explore view — which is exactly what the → button in that section's "
        "header already does. Two controls, one action, and the arrow made it "
        "look like the only way to see the rest was to leave.",
        "It now grows the section so the hidden rows appear in place. Those "
        "rows were never cut off, only unallocated: dragging a section taller "
        "has always revealed more, and now the row does that for you.",
        "Space comes from whichever neighbouring sections have the most to "
        "spare, and never shrinks one below its own useful minimum. If there "
        "is genuinely no room left, the row opens the full view as before.",
        "The header's Explore → keeps its own job: leaving for the full view.",
    ),
    test_steps=(
        "Find a sidebar section ending in \"Show N more\" → click it. The "
        "section grows and the hidden rows appear; you stay in the sidebar.",
        "Watch the neighbouring sections as you click → they give up space, "
        "and none of them collapses to nothing.",
        "Shrink every other section to its minimum first, then click \"Show N "
        "more\" → with no room to take, it opens the full view instead of "
        "doing nothing.",
        "Click the → in a section header → it still opens Explore, unchanged.",
        "Restart the app after growing a section → the new sizes are still "
        "there.",
    ),
)
