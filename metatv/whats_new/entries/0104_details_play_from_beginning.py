from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=104,
    version="0.9.0",
    date="2026-06-28",
    title="Details: the Play button starts from the beginning again",
    items=(
        "Fixed a regression where the details-pane ▶ Play button resumed from your "
        "last position instead of starting over — it had been wired to the "
        "resume-aware play path. Play now always starts from the beginning; "
        "⏩ Resume continues where you left off.",
    ),
    test_steps=(
        "Open a partially-watched movie's details and click ▶ Play — it must start "
        "from the beginning (00:00), NOT resume.",
        "Click ⏩ Resume on the same title — it must continue from your saved "
        "position. The two buttons must behave differently.",
    ),
)
