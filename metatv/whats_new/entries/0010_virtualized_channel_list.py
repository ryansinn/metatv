from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=10,
    version="0.6.0",
    date="2026-06-20",
    title="Channel list now virtualized — no more cap at 5,000 / 10,000",
    items=(
        "The channel list now loads pages incrementally as you scroll, "
        "so categories with 100,000+ entries work just as smoothly as small ones.",
        "The previous caps (5,000 SQL rows / 10,000 rendered rows) are gone.",
    ),
)
