from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=612,
    version="0.101.0",
    date="2026-09-06",
    title="A refresh re-reads a title whose listing changed",
    items=(
        "When a source renames a title or moves it to another category, its "
        "detected title, genre and other derived fields now follow on the "
        "next refresh instead of keeping the old reading.",
    ),
    test_steps=(
        "Note a title's genre chip; have the source re-list it under another "
        "category and refresh — the chip follows.",
        "Refresh again with nothing changed — the log reports zero rows "
        "recomputed.",
    ),
)
