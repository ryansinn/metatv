from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=329,
    version="0.40.0",
    date="2026-08-22",
    title="Sidebar headings get real icons",
    items=(
        "History, Favorites, Sources and Recommended showed an emoji next to "
        "their heading. An emoji cannot be given a colour, so those four were "
        "stuck looking the same whichever theme you picked, and they were "
        "drawn differently depending on the machine.",
        "They are now proper icons that take the theme's colour, matching the "
        "view buttons along the bottom.",
        "The Favorites star was meant to be gold and never actually was — the "
        "colour was being applied to an emoji, which ignores it. It is gold "
        "now.",
        "Watch Alerts is unchanged: its heading already used a colour-changing "
        "status dot rather than an emoji.",
    ),
    test_steps=(
        "Look at the sidebar headings for History, Favorites, Sources and "
        "Recommended — each shows a crisp icon rather than an emoji.",
        "Check the Favorites heading specifically — its star is gold, not the "
        "same grey as the other headings.",
        "Open Settings → Style and switch between Midnight, Graphite and "
        "Daylight → the History, Sources and Recommended icons change colour "
        "with the theme instead of staying fixed.",
        "Switch to Daylight and confirm the heading icons are dark enough to "
        "read against the light background.",
        "Confirm the Watch Alerts heading still shows its status dot, and "
        "that the dot still turns green with a count when a new match "
        "arrives.",
    ),
)
