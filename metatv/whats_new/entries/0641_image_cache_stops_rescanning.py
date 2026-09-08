from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=641,
    version="0.105.0",
    date="2026-09-08",
    title="Image cache stops stat-storm on every download",
    items=(
        "The image cache now tracks its size incrementally instead of rescanning the entire directory on every download.",
        "Loading poster-heavy views (Discover, Browse) no longer causes main-thread stalls during concurrent image downloads.",
        "LRU cleanup still works exactly the same way; the only change is performance.",
    ),
    test_steps=(
        "Open Discover and scroll through several shelves loading poster images — no UI stalls or choppiness.",
        "Open a collection with many titles — posters load smoothly without blocking channel-list interaction.",
        "Download the app, wait for the image cache to fill, then reload Discover — old images are cleaned up as needed without performance impact.",
    ),
)
