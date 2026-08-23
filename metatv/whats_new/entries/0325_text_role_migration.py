from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=325,
    version="0.40.0",
    date="2026-08-22",
    title="Secondary text is legible everywhere",
    items=(
        "Small grey text — section hints, item counts, empty-state labels, row "
        "metadata — was below the WCAG AA contrast floor in every theme. It now "
        "uses the palette's real text role and clears the floor in all three.",
        "The three legacy greys it used to draw with (faint / muted / dim) were "
        "left over from before the token system and could not pass on any "
        "surface. They now only paint borders and backgrounds, where the "
        "contrast floor does not apply.",
        "Deliberately dimmed states — watched rows, degraded rows — keep their "
        "dimming; that is a signal, not an accident.",
    ),
    test_steps=(
        "Open Settings → Style and switch to Daylight → small grey text in the "
        "sidebar (section counts, 'Continue Watching', empty-state notes) is "
        "clearly readable rather than washed out.",
        "Switch to Midnight, then Graphite → the same text stays readable in "
        "both, and nothing has turned white-on-white or black-on-black.",
        "Find a watched row in the channel list → its title is still visibly "
        "dimmer than an unwatched one.",
        "Hover the 'More Categories' button in Discover → the label stays "
        "readable against the hover tint.",
    ),
)
