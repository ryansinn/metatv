from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=20,
    version="0.7.1",
    date="2026-06-21",
    title="Discover shelf pinning & zone fixes",
    items=(
        "Pinning a shelf now always expands it — a pinned shelf is never collapsed or blank.",
        "Pinning a collapsed shelf immediately fetches and shows its content.",
        "Recently Added, Top Rated Movies, and Top Rated Series are now expanded by default on first launch.",
        "Fixed a config inconsistency where a shelf could appear in two zones simultaneously, causing inverted expand/collapse behaviour.",
        "Un-pinning a shelf returns it to the active (expanded) zone rather than collapsing it.",
    ),
)
