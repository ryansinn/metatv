from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=591,
    version="0.95.0",
    date="2026-09-04",
    title="Declared indexes reach existing libraries",
    items=(
        "Every index the data model declares is now built on existing "
        "libraries automatically on the next launch — about eighteen were "
        "missing on long-lived libraries, which is why some list and shelf "
        "queries stayed slow after an update.",
        "The one-time 'library update' wait on the next launch after this "
        "update covers building them.",
    ),
    test_steps=(
        "Launch on an existing library → the log shows the index task "
        "creating the missing indexes once, and a second launch creates none.",
        "The channel list and Discover shelves load no slower than before "
        "(faster on a large library).",
    ),
)
