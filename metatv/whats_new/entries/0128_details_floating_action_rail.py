from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=128,
    version="0.9.0",
    date="2026-07-11",
    title="Details poster fills the panel with a floating action rail",
    items=(
        "The slim action rail (favorite, alert, hide, and the like / not-interested / "
        "dislike icons) now floats over the LEFT edge of the poster instead of taking its "
        "own column — so the gray poster card fills the full width of the details panel.",
        "The rail icons sit on a subtle dark scrim and read as frosted chips, so they stay "
        "legible over bright posters.",
        "The poster is a bit shorter and hugs the left edge, so the floating rail always "
        "sits over the poster itself rather than the gray margin; the Watched badge now "
        "lands on the poster's lower-right corner instead of out in the padding.",
        "Tightened the right gutter for a more symmetric inset; the details panel stays "
        "drag-resizable between 300 and 500px.",
    ),
    test_steps=(
        "Open a VOD title with a poster: the gray poster card spans the full panel width, "
        "and the icon rail floats over the poster's left edge (not in a separate column, "
        "and not over the gray margin).",
        "Hover the poster: the Watched badge appears on the poster's lower-right CORNER — "
        "on the image itself, not out in the gray padding beside it.",
        "Drag the details panel divider left and right: the panel resizes between 300 and "
        "500px (the divider is not inert), and the poster height stays fixed while the Play "
        "/ Watch Later buttons below it stay put.",
        "Open a LIVE channel that has a logo: the logo shows in the same poster area with "
        "the rail floating over its left edge.",
    ),
)
