from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=608,
    version="0.99.0",
    date="2026-09-05",
    title="Leftovers from removed sources are cleaned up whenever they appear",
    items=(
        "Content left behind by a removed source is now cleaned up by the "
        "Migration Center whenever it is found, not just once per library. "
        "Favorites, history, ratings, and queued titles from a removed source "
        "are always kept.",
    ),
    test_steps=(
        "Remove a source — on the next launch the Migration Center reports "
        "the cleanup and finishes.",
        "A favorite from that source is still in Favorites afterwards.",
    ),
)
