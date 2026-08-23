from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=326,
    version="0.40.0",
    date="2026-08-22",
    title="The view buttons follow your theme",
    items=(
        "Search, EPG, Recommended, Discover and Recipe had their icons baked "
        "into the button text as emoji. Emoji cannot take a colour, so those "
        "five were the one part of the interface that never changed with the "
        "theme — and they looked different on every machine.",
        "They are now real icons that repaint with the palette, and that dim "
        "or brighten depending on whether the view is the active one.",
    ),
    test_steps=(
        "Look at the five view buttons along the bottom — each has a crisp "
        "monochrome icon rather than a coloured emoji.",
        "Open Settings → Style and switch between Midnight, Graphite and "
        "Daylight → the button icons change colour with the theme instead of "
        "staying the same.",
        "Click between Search and Discover → the active button's icon is "
        "clearly legible against its filled background, and the inactive ones "
        "sit quieter.",
    ),
)
