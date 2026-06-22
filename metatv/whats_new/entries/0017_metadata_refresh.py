from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=17,
    version="0.7.0",
    date="2026-06-21",
    title="Correct posters and details after a source refresh",
    items=(
        "IPTV providers sometimes reuse stream IDs for different content — MetaTV now detects this and "
        "refreshes the poster, plot, and rating for the new content automatically.",
        "A one-time background scan fixes any stale posters already in your library from past refreshes.",
    ),
)
