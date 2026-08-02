from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=229,
    version="0.19.0",
    date="2026-08-01",
    title="'Clear Watched' now removes only genuinely finished content",
    items=(
        "Previously, 'Clear Watched' removed any item that had ever been played "
        "(a series after playing just 1 episode, a movie that was started but "
        "not finished). The fix now keeps partially-watched items: remove only "
        "series with ALL episodes watched, movies/live with the watch_completed "
        "flag set, and episodes marked as watched. Partial progress is preserved.",
    ),
    test_steps=(
        "Queue a series → play episode 1 of 3 → 'Clear Watched' → the series "
        "stays in queue. Mark all 3 episodes as watched → 'Clear Watched' → "
        "the series is removed. Queue a movie → play partway but don't finish → "
        "'Clear Watched' → the movie stays with its resume point.",
    ),
)
