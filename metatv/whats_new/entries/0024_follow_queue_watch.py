from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=24,
    version="0.9.0",
    date="2026-06-22",
    title="Auto-queued episodes now track correctly",
    items=(
        "Watch progress is now recorded against the episode actually playing — not always the first one.",
        "Episodes auto-advanced by mpv (E1 → E2 → E3) are each marked completed as the playlist moves on.",
        "The started episode is recorded as 'manual'; auto-advanced episodes are recorded as 'queue'.",
    ),
)
