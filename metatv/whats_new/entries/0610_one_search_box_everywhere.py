from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=610,
    version="0.99.0",
    date="2026-09-05",
    title="One search box, everywhere",
    items=(
        "Every filter and search box in the app is now the same control — "
        "clear button, Escape to clear, the same typing behaviour — with "
        "each surface keeping its own hint text.",
    ),
    test_steps=(
        "Type into the Watch Queue filter, Discover \"Filter shelves\", On "
        "Now \"Search On Now\" and the header search — each narrows as "
        "before and the ✕ clears it.",
        "Escape in the queue filter clears and hides it; Escape in the "
        "others clears.",
    ),
)
