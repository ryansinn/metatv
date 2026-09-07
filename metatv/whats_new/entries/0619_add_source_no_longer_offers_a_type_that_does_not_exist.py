from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=619,
    version="0.101.0",
    date="2026-09-07",
    title="Add Source no longer offers a type that does not exist",
    items=(
        "The \"M3U (coming soon)\" choice is gone from Add Source's type "
        "list until an M3U source actually works.",
    ),
    test_steps=(
        "Sources ▸ Add → the type list shows Xtream only.",
    ),
)
