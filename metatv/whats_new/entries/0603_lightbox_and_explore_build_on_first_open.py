from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=603,
    version="0.99.0",
    date="2026-09-05",
    title="The Similar-titles preview and Explore build on first open, not at launch",
    items=(
        "The Similar-titles preview and the Explore map are now built the "
        "first time you open them instead of at every launch, trimming "
        "startup time.",
    ),
    test_steps=(
        "Launch the app — the window appears with no change in what is "
        "shown.",
        "Open Similar on a title, then Explore — both open and work as "
        "before.",
    ),
)
