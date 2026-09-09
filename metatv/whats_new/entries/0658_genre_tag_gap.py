from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=658,
    version="0.116.0",
    date="2026-09-09",
    title="Genre facets and the genre chip agree again",
    items=(
        "A recent fix taught the app to recognize a movie's genre from more "
        "provider categories (case-insensitive matching plus several new "
        "aliases) and re-derived every channel's stored genre from it — but "
        "the genre facets shown in Browse and the genre chip in the details "
        "pane read a separate, already-computed tag index that was never "
        "rebuilt from the same fix, so the two disagreed. Roughly 12,300 "
        "movies (plus a handful of series) had a genre on file that neither "
        "surface could see. Those channels are now re-indexed the next time "
        "the app opens, targeted at just the affected rows so it finishes in "
        "seconds rather than minutes.",
    ),
    test_steps=(
        "Relaunch the app once after updating — a brief 'Building content "
        "tags' migration step may appear and finishes quickly.",
        "Open Browse and expand a genre shelf, e.g. Documentary or Comedy — "
        "more movies now appear under it than before the update.",
        "Open a movie that previously showed a genre in its details pane but "
        "didn't appear under that genre in Browse — it now shows up under "
        "the matching genre facet/shelf too.",
    ),
)
