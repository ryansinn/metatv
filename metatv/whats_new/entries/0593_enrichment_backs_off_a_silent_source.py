from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=593,
    version="0.95.0",
    date="2026-09-04",
    title="Enrichment backs off a silent source",
    items=(
        "When a source answers three enrichment batches in a row with "
        "nothing, it is rested for fifteen minutes while other sources keep "
        "going, so a slow, silent host no longer stretches every enrichment "
        "run.",
    ),
    test_steps=(
        "With one source whose TMDb lookups return nothing and another that "
        "hits, watch the log — after three empty batches the silent source "
        "is skipped with a single \"backing off\" line and the other "
        "source's hits keep landing.",
        "Fifteen minutes later, the rested source is tried again.",
    ),
)
