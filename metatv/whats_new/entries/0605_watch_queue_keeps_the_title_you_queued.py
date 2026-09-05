from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=605,
    version="0.99.0",
    date="2026-09-05",
    title="The Watch Queue keeps the title you queued",
    items=(
        "A queue row whose stream id was reused by a different title keeps "
        "showing (and searching for) the title you queued.",
        "A re-keyed queue row can only re-attach to a channel from its own "
        "source.",
    ),
    test_steps=(
        "Queue a title, then have its source refresh with a renewed account "
        "that recycles stream ids — the row still shows the original title.",
        "Right-click the row → Search finds the original title, not the "
        "recycled one.",
    ),
)
