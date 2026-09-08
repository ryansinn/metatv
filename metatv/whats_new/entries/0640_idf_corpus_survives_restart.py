from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=640,
    version="0.105.0",
    date="2026-09-08",
    title="Launch no longer rebuilds your whole taste profile every time",
    items=(
        "Every cold launch was rebuilding a recommendation lookup table "
        "(the plot-keyword weights behind ▲/▼ markers, Discover and the "
        "trail map) from scratch over 130,000+ stored plot summaries — a "
        "multi-second, CPU-heavy pass that competed with the UI thread for "
        "Python's lock and was a repeat cause of the app freezing at "
        "startup, up to 16 seconds in one measured case.",
        "That table is now saved to disk after it's built and reused on "
        "the next launch as long as your library hasn't changed, so most "
        "launches skip the rebuild entirely. It still rebuilds "
        "automatically the moment new or refreshed metadata actually "
        "changes the underlying plot corpus.",
        "A missing, unreadable, or corrupted cache file is harmless — it "
        "just falls back to rebuilding normally, the same as before this "
        "change.",
    ),
    test_steps=(
        "Launch the app once and let it fully load, then quit and launch "
        "it again → the log's second launch shows an 'IDF corpus disk "
        "cache hit' line instead of '(rebuilt)', and the app reaches its "
        "usable state noticeably faster with fewer/no launch-time freezes.",
        "Let metadata enrichment run (or manually refresh a source's "
        "metadata) between two launches → the next launch's log shows "
        "'(rebuilt)' again, proving the cache still invalidates when the "
        "corpus actually changes.",
        "Delete ~/.cache/metatv/idf_corpus.json (or leave it absent on a "
        "fresh profile) and launch → the app starts normally with a "
        "'(rebuilt)' log line and no crash or error dialog.",
    ),
)
