from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=41,
    version="0.9.0",
    date="2026-06-22",
    title="Open-ended buffer as default profile",
    items=(
        "A new 'Open-ended (disk-backed, max buffer)' option in Settings → Playback → Buffering sets the open-ended disk-backed cache as the default for all playback — not just the per-play context-menu action.",
        "When active, mpv buffers as far ahead as the stream allows (up to 2 GiB on disk, 1-hour readahead window), giving the largest possible lead time on unstable or high-latency streams.",
        "The per-play 'Play with open-ended buffer' context action is unchanged and still works alongside whichever default profile is configured.",
    ),
)
