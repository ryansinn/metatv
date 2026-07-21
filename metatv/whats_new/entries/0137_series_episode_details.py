from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=137,
    version="0.9.0",
    date="2026-07-21",
    title="Series 'Browse' button + click an episode for its details",
    items=(
        "A series' primary details button now reads '🗂 Browse' (it opens the "
        "seasons/episodes view) instead of the misleading '▶ Play'.",
        "Single-clicking an episode in the seasons/episodes view now fills the "
        "details pane with that episode — its (cleaned) title in a byline under the "
        "series title, the series poster/plot as fallback, and a "
        "'▶ Play Episode: S##E##' button showing the season/episode coordinate.",
        "Selecting a season (or the series row) reverts the pane to the series' own "
        "details.  Double-click still plays; the right-click menu is unchanged.",
    ),
    test_steps=(
        "Open a SERIES in the details pane → the primary button reads '🗂 Browse' "
        "(not 'Play'), tooltip 'Browse seasons & episodes'.",
        "Click Browse → the middle panel switches to the seasons/episodes view.",
        "Single-click an episode → the details pane shows the episode: its cleaned "
        "title in a byline (matching the tree row, not the raw 'Series - SxxExx -' "
        "form), and the primary button reads '▶ Play Episode: S##E##' with that "
        "episode's coordinate.",
        "Pick an episode with a long title → the byline WRAPS; nothing clips off the "
        "right edge and the pane column does not widen.",
        "Click 'Play Episode' → that episode starts playing.",
        "Select a season row → the pane reverts to the series' own details "
        "(button reads '🗂 Browse' again).",
    ),
)
