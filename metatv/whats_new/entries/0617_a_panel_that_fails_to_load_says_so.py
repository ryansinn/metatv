from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=617,
    version="0.101.0",
    date="2026-09-07",
    title="A panel that fails to load says so",
    items=(
        "Source Analytics, Missing TMDb, Reconnect and Enrichment panels show "
        "a visible \"couldn't load\" row instead of a spinner that never ends.",
        "A favorite or rating that fails to save now says so in the status "
        "bar instead of silently keeping the old state.",
    ),
    test_steps=(
        "Open Source Analytics with the database locked by a refresh — each "
        "panel shows the couldn't-load row rather than Loading… forever.",
        "Like a title while a refresh holds the database — either the star "
        "lands or the status bar says it could not save.",
    ),
)
