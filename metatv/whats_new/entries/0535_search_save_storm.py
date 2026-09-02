from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=535,
    version="0.75.0",
    date="2026-09-02",
    title="Typing in the search box no longer rewrites your whole config on every keystroke",
    items=(
        "Each keystroke in the search box wrote the entire 129 KB settings "
        "file to disk — backing the old one up first — to remember what you "
        "were searching for. Six full writes in thirteen seconds of ordinary "
        "typing, on a machine where each one costs up to 90 ms.",
        "The search itself was already careful about this: it waits for you to "
        "stop typing before it queries. The disk write was not, so the cheaper "
        "of the two was the one being protected.",
        "The write now waits for the burst to settle, and there is exactly one "
        "of it. What you searched for is still remembered — the value updates "
        "immediately and any pending write is flushed when you close the app.",
    ),
    test_steps=(
        ("Type a search term, then close and reopen the app. Your search must "
         "still be there — this is the behaviour the write exists for.",
         "view:list"),
        ("Type a longer phrase and confirm the list still filters as you type "
         "with no new stutter.", "view:list"),
        ("Clear the search, close and reopen: it must come back cleared, not "
         "showing the old term.", "view:list"),
    ),
)
