from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=649,
    version="0.111.0",
    date="2026-09-08",
    title="Playing a finished download no longer blocks a new download from the same source",
    items=(
        "Playing a finished download into the same window a live stream was using "
        "left that provider's one connection slot charged to the local file — a "
        "provider limited to one stream would then refuse a NEW download from "
        "itself, even though nothing was actually talking to it any more. "
        "play_local_file() now releases the stale slot (and forgets the stale "
        "stream URL) whenever it takes over a window that was still tracking a "
        "provider connection.",
    ),
    test_steps=(
        "Play a live channel from a one-connection source, then play a finished "
        "download from that same source into the same window — start a new "
        "download from that source right after: it starts instead of being "
        "refused as 'connection limit reached'.",
    ),
)
