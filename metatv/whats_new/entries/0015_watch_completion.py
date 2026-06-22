from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=15,
    version="0.7.0",
    date="2026-06-21",
    title="Watch completion — see what you've watched",
    items=(
        "Movies you've finished show a ✓ badge in the Discover cards and a ✓ symbol in the channel list.",
        "Partially-watched movies show a thin orange progress bar at the bottom of the Discover card.",
        "The details pane shows '✓ Watched' or 'Resume at M:SS' for any movie.",
        "Configure the completion threshold in Settings → Playback → 'Mark as watched at' (default 90%).",
    ),
)
