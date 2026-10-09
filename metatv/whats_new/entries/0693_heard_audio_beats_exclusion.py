from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=693,
    version="0.138.0",
    date="2026-10-09",
    title="A verified language beats a prefix exclusion",
    items=(
        "If you globally exclude a prefix like SE, a copy under it that has been "
        "played or probed and measured as English is no longer hidden — the "
        "stream proved it isn't Swedish.",
    ),
    test_steps=(
        "With SE in Global Exclusions, play or 'Get stream details' on an SE copy "
        "that is really English — it now appears in the channel list and in "
        "'Available in' (not in the filtered bucket).",
        "Unmeasured SE copies stay hidden, as before.",
    ),
)
