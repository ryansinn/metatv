from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=374,
    version="0.41.0",
    date="2026-08-26",
    title="A real Midnight theme, and the old one is now called Slate",
    items=(
        "Midnight is rebuilt from the design document: a genuinely dark, cool "
        "blue-grey rather than the neutral grey it had drifted into. Lists sit "
        "deeper, the chrome around them is clearly separate, and the accents "
        "are softer.",
        "The theme that used to be called Midnight is now Slate. It has not "
        "changed - only its name, which now matches what it actually is. If "
        "you were using it, pick Slate.",
        "Midnight, Slate and Graphite are three distinct dark themes now. "
        "Midnight and Graphite had drifted close enough to be hard to tell "
        "apart.",
    ),
    test_steps=(
        "Settings - Interface - Theme - pick Midnight. The whole app is "
        "noticeably darker and cooler than before, with a blue cast.",
        "Look at a sidebar list against the panel around it - the list is "
        "clearly recessed, not the same shade.",
        "Pick Slate - this is the theme that used to be called Midnight, "
        "unchanged.",
        "Cycle Midnight, Slate and Graphite - all three are obviously "
        "different.",
        "Check chips and badges in Midnight - quality, language and new-count "
        "colours are softer than in Slate but still tell each other apart.",
    ),
)
