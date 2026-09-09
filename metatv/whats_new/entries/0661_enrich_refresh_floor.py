from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=661,
    version="0.119.0",
    date="2026-09-09",
    title="Discover stops rebuilding itself every forty seconds while you are reading it",
    items=(
        "Background TMDb enrichment finishes a batch roughly every half-minute "
        "while you browse, and each one was running the app's heaviest refresh "
        "cascade — which tears Discover down to \"Loading…\" and rebuilds every "
        "shelf, reloads the channel list, and re-counts the filter facets. "
        "There was already a one-minute debounce for exactly this; the "
        "end-of-batch signal was firing straight through it.",
        "Those refreshes now honour the debounce: the first one after a quiet "
        "spell still lands promptly, and any that would follow too soon is held "
        "until the window is up rather than run immediately. Nothing is "
        "dropped — a held refresh still happens, just once.",
    ),
    test_steps=(
        "Open Discover and leave it on screen for several minutes while "
        "background enrichment is running (browse some movies first to give it "
        "work). The shelves should not flash back to \"Loading…\" every ~40 "
        "seconds the way they did.",
        "Confirm Discover does still pick up changes: assign a channel to a "
        "category, or toggle a source off in Sources, and Discover reflects it.",
        "Check the log for metatv.gui.main_window_channels \"Loading N channels\" "
        "lines — during idle browsing these should be at least a minute apart, "
        "not ~40 seconds.",
    ),
)
