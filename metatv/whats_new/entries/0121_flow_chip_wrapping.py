from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=121,
    version="0.9.0",
    date="2026-06-29",
    title="Genre & version chips wrap instead of spilling off the edge",
    items=(
        "In the details pane, the genre chips, the 'Also available as' / filtered "
        "version chips, and the media-type row now WRAP onto multiple rows and stay "
        "inside the panel — they no longer lay out in a single row that clips off the "
        "right edge on titles with many genres (e.g. Cowboy Bebop).",
        "Root cause: these chip rows are nested inside vertical layouts, which only "
        "honour a wrapping flow layout when the container's size policy opts into "
        "height-for-width — which nothing did. The opt-in now lives in the flow-layout "
        "constructor itself, so every current and future nested chip row wraps for free.",
    ),
    test_steps=(
        "Open a movie/series with many genres (e.g. Cowboy Bebop) in the details pane "
        "and narrow the pane: the genre chips WRAP onto multiple rows and every chip "
        "stays inside the panel — none is cut off at the right edge.",
        "On a title with several alternate versions, confirm the 'Also available as' "
        "chips also wrap onto multiple rows instead of clipping.",
        "Widen the pane and confirm the chips reflow back onto fewer rows (the row "
        "count tracks the available width).",
    ),
)
