from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=381,
    version="0.41.0",
    date="2026-08-26",
    title="The What's New card reads as one heading, not two",
    items=(
        "An entry's title and its bullets are each a step smaller. The title "
        "was the same weight as the dialog's own What's New banner directly "
        "above it, so the card looked like a second header rather than the "
        "thing the header introduces.",
        "The bullets now sit at the app's normal body size, which is what they "
        "are - still above the legibility floor, just no longer oversized.",
        "The What's New banner itself is unchanged.",
    ),
    test_steps=(
        "Open Help > What's New. The banner at the top is clearly the largest "
        "text on screen; the entry's title below it is visibly smaller.",
        "Read a bullet - it should match the size of ordinary text elsewhere "
        "in the app, not be noticeably larger.",
        "The version and date line stays the smallest text in the card.",
        "Step back through a few entries with the arrows - every card sizes "
        "the same way, and long titles still wrap without clipping.",
    ),
)
