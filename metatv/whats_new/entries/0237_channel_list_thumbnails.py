from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=237,
    version="0.20.0",
    date="2026-08-02",
    title="Channel list: poster thumbnails (Comfy/Comfy+)",
    items=(
        "Comfy and Comfy+ channel-list rows now show a small poster thumbnail "
        "on the left, before the media icon. Compact density never shows one. "
        "Titles without a cached poster show a muted placeholder tile with "
        "their first letter instead of a blank gap.",
        "Thumbnails are lazy and viewport-only — only the rows currently on "
        "screen ever download an image; scrolling never queues the rest of "
        "the list.",
        "New setting: Settings → Interface → Channel List → 'Show thumbnails "
        "in lists' (on by default). Turning it off removes the reserved "
        "thumbnail space entirely and applies immediately.",
    ),
    test_steps=(
        "With Row density on 'Comfy' or 'Comfy+' and thumbnails on (default), "
        "scroll the channel list → titles with a cached/available poster show "
        "a small 2:3 thumbnail on the left; titles without one show a muted "
        "tile with their first letter, never a blank gap.",
        "Scroll quickly through a long list, then stop → only the rows you "
        "stopped on load thumbnails (no burst of requests for rows you flew "
        "past).",
        "Switch Row density to 'Compact', click Apply → thumbnails disappear "
        "entirely, even though the setting is still on.",
        "Open Settings → Interface → Channel List, uncheck 'Show thumbnails "
        "in lists', click OK → every row (Comfy/Comfy+) loses its thumbnail "
        "column immediately and rows shrink back to text-only height.",
    ),
)
