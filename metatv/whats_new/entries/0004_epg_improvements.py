from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=4,
    version="0.1.0",
    date="2026-06-19",
    title="EPG improvements",
    items=(
        "'On Now' now shows channels from your active sources only — no more entries from disabled ones.",
        "Channel categories load instantly (no more stuck 'Loading categories…' on live channels).",
        "'On Now' columns remember the order you arrange them in.",
        "EPG Discover: '+ Channel' adds the channel to My Channels, plus a Play button and an expandable list of upcoming matches.",
    ),
)
