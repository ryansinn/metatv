from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=122,
    version="0.9.0",
    date="2026-06-29",
    title="Details: genres/cast/version chips finally stop clipping off the right edge",
    items=(
        "The real fix for the long-standing 'Cowboy Bebop' bug where the genre chips, "
        "the cast list, and the 'Also available as' version chips were cut off at the "
        "right edge of the details pane (and the version chips wrapped at a width wider "
        "than the panel). They now stay inside the pane and wrap correctly.",
        "Root cause (missed by earlier attempts that only touched the genre row): the "
        "POSTER was forcing it. A poster image label reports its minimum width as the "
        "image's pixel width, which — inside the width-resizable, no-horizontal-scrollbar "
        "details pane — stretched the WHOLE content column wider than the visible panel, "
        "so every section below was laid out past the right edge.",
        "The poster now subordinates to the pane width instead of driving it, and "
        "re-fits itself to whatever width the pane is given — so it still fills the "
        "poster area cleanly and the panel never grows wider than what you can see.",
    ),
    test_steps=(
        "Open a series/movie with MANY genres and several alternate versions (e.g. "
        "Cowboy Bebop) in the details pane.",
        "Confirm the genre chips (Action_Adventure, Animation, Crime, Drama, …) WRAP "
        "onto multiple rows and every chip is fully visible — none is cut off at the "
        "right edge.",
        "Confirm the 'Also available as' version chips and the Cast & Crew names are "
        "also fully visible (not clipped) and wrap within the panel.",
        "Drag the details pane / splitter narrower and wider: the poster re-fits to the "
        "new width (no clipping, no giant empty gap) and the chips reflow to track the "
        "available width.",
        "Open a LIVE channel that has a logo: the logo still fills the poster area and "
        "re-fits on resize the same way.",
    ),
)
