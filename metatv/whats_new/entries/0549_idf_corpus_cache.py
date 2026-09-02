from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=549,
    version="0.83.0",
    date="2026-09-02",
    title="Recommendation term weights are built once, not once per screen",
    items=(
        "The recommendation engine's term-weight table (built from 130,000+ "
        "plot summaries) is now computed once and shared by every consumer "
        "instead of rebuilt on every refresh — one settings change was "
        "building it twice within two seconds, each build freezing the UI "
        "for a couple of seconds.",
        "It rebuilds automatically whenever enrichment changes the "
        "underlying metadata corpus, so it never goes stale.",
    ),
    test_steps=(
        "Apply Global Exclusions or open Discover twice in a row and check "
        "the log: one 'IDF corpus ... (rebuilt)' line followed by 'cache "
        "hit' lines, not repeated multi-second rebuilds.",
    ),
)
