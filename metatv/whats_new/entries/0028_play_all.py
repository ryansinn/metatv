from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=28,
    version="0.7.5",
    date="2026-06-22",
    title="Multi-select Play All",
    items=(
        "Select multiple channels (Shift/Ctrl+click) in the channel list, then "
        "right-click → 'Play All (N)' to play the first and queue the rest in "
        "selection order. The queue follows the same watch-progress capture as "
        "auto-play season episodes, so each item gets its own watch record.",
        "Select multiple episodes in the series tree, then right-click → "
        "'Play All Selected (N)' to play the first and queue the rest in tree order.",
        "Both surfaces use the same shared helper — play first, queue the rest, "
        "register the full playlist in watch-tracking so playback health and "
        "progress capture follow each item as mpv advances.",
        "Series channels are skipped in channel-list Play All (they have no direct "
        "stream URL); selecting a mix of movies, live, and series will play the "
        "non-series items and skip the series ones with a log note.",
    ),
)
