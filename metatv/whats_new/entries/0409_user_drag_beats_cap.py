from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=409,
    version="0.53.0",
    date="2026-08-28",
    title="Sidebar sections can be dragged taller again",
    items=(
        "A sidebar section will not take more height than its contents can "
        "fill, so an empty list does not sit in a tall box of nothing.",
        "That limit was also being applied to you. Dragging a divider moved the "
        "numbers the app tracks while the sections themselves stayed exactly "
        "where they were - the cursor changed, nothing else did.",
        "It was worst with little content, which is when you are most likely to "
        "be rearranging things: with short lists every section was pinned just "
        "below the height it already had.",
        "The limit now applies only to space the app hands out on its own. A "
        "height you drag to is yours and is kept.",
        "Dragging a section down to its header still collapses it rather than "
        "being remembered as a preferred size.",
    ),
    test_steps=(
        "Drag the divider between two sidebar sections. The sections should "
        "resize and stay where you put them.",
        "Try it on a section with a short list - it should still grow, even "
        "past the length of its contents.",
        "Restart the app and confirm the sizes you set are still there.",
        "Drag a section down onto its header and confirm it collapses.",
        "Confirm a section you have not dragged still sizes itself to its "
        "content rather than padding empty space.",
    ),
)
