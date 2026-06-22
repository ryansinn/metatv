from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=37,
    version="0.8.0",
    date="2026-06-22",
    title="Open-Ended Buffer Mode",
    items=(
        "Right-click any channel and choose \"Play with open-ended buffer\" to build "
        "a large buffer lead — mpv caches as far ahead as the stream allows (disk-backed, "
        "up to 2 GiB / 3600 s readahead) instead of the bounded configured profile.",
        "Useful for riding out unstable streams: start buffering, wait for the lead to "
        "build, then watch without interruptions even if the connection drops briefly.",
        "The normal Play action and your default buffer profile are unchanged — this is "
        "a per-play variant that always opens a fresh mpv window so the large cache "
        "settings take effect from the start.",
    ),
)
