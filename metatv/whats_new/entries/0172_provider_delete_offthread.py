from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=172,
    version="0.13.0",
    date="2026-07-31",
    title="Deleting a source no longer freezes the app",
    items=(
        "Removing a source used to lock the whole window ('Not Responding') for "
        "a minute or more on a large library, because the cleanup ran on the UI "
        "thread. It now runs in the background: you get a 'Deleting source…' "
        "toast, the app stays responsive, and the views refresh when it finishes.",
        "The cleanup itself is dramatically faster — it now removes a source's "
        "content with a handful of set-based database deletes instead of hundreds "
        "of tiny batches, collapsing the lock contention that stretched a "
        "~13-second purge into a multi-minute freeze.",
        "Fixed a data leak: a source's tag links (content_tags) were never cleaned "
        "up when it was deleted, so they piled up invisibly. Deletes now remove "
        "them, and a one-time cleanup on startup clears the existing backlog.",
        "Your engaged content is still protected: favorited, watched, and queued "
        "channels (and their tags/history) survive a source delete exactly as "
        "before — they stay in Favorites / History / Watch Queue.",
    ),
    test_steps=(
        "Open a source in the editor and click Delete → confirm: a 'Deleting "
        "source…' toast appears and the app stays responsive (no 'Not "
        "Responding'); when it clears, the source is gone from the sidebar and the "
        "channel list refreshes.",
        "Before deleting, favorite one channel from that source and note a watched "
        "channel; after the delete, open Favorites / History and confirm those "
        "engaged channels are still listed (marked unavailable).",
        "Delete a source that has many channels and confirm it completes in a few "
        "seconds, not minutes.",
    ),
)
