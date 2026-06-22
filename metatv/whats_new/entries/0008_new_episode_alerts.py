from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=8,
    version="0.1.0",
    date="2026-06-20",
    title="Get alerts for new episodes",
    items=(
        "Right-click any series → 'Alert me to new episodes' to start.",
        "When new episodes are detected after a source refresh or on startup, a toast notification appears.",
        "A new 'New Episodes' sidebar section lists every series you're alerting on with unseen episodes.",
        "Click a row to open the series, or 'Mark seen' to clear the badge.",
    ),
)
