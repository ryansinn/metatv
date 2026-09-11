from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=670,
    version="0.121.0",
    date="2026-09-11",
    title="\"Building channel indexes\" no longer runs on every launch",
    items=(
        "Since the index diet two days ago, every start dropped and rebuilt "
        "23 channel indexes and re-analysed the whole table — 12-15 seconds "
        "of disk work and the progress banner, on every single launch.",
        "The drop now only fires for an index still in its old shape, so it "
        "happens once per upgrade instead of every time the app opens.",
    ),
    test_steps=(
        "Launch the app twice in a row — the second launch must not show "
        "\"Building channel indexes\", and the log has no "
        "\"QueryIndexTask: creating\" lines on that second start.",
        "The channel list still loads and filters (by type, favorites, "
        "hidden) exactly as before.",
    ),
)
