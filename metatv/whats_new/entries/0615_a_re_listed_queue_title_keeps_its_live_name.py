from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=615,
    version="0.100.0",
    date="2026-09-06",
    title="A re-listed queue title keeps its live name",
    items=(
        "A queued title that the source re-lists with more detail — a year, a "
        "region or a cast suffix added — shows and searches by its live name "
        "again; only a stream id taken over by a different title keeps the "
        "name you queued.",
        "That take-over is logged once per title, not on every sidebar refresh.",
    ),
    test_steps=(
        "Queue a title, then have its source re-list it as the same title with "
        "a suffix — the Watch Queue row shows the cleaned live title.",
        "A row whose stream id now serves a different title still shows the "
        "title you queued, and the log carries one STREAM-ID REUSE line for it.",
    ),
)
