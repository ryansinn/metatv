from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=21,
    version="0.7.2",
    date="2026-06-22",
    title="Episode watch tracking & per-episode mpv title",
    items=(
        "Episodes now show three-state watch indicators in the series view: ✓ (completed), "
        "◐ (in-progress / partially watched), or ▶ (unwatched).",
        "Episode watch progress and completion are now captured automatically — the same "
        "periodic checkpoint used for movies records each episode's resume position and marks "
        "it completed once you watch past the configured threshold.",
        "The mpv window title now updates correctly as each queued episode starts playing, "
        "rather than staying stuck on the first episode's title.",
        "Fixed: episode play now correctly threads the source provider ID through to mpv, "
        "ensuring Split Streams (one window per source) works as expected for series.",
    ),
)
