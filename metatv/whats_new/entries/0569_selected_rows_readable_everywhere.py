from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=569,
    version="0.88.0",
    date="2026-09-03",
    title="Selected rows stay readable on the tinted selection, in every theme",
    items=(
        "Selecting a row in a coloured list or tree (the channel list, the "
        "series episode tree, the sidebar section list) used to paint its "
        "text with the app's solid-accent-fill colour, even though the "
        "selection itself is a soft translucent tint, not a fill. In "
        "Gruvbox that put near-black text on a pale, barely-tinted "
        "background — effectively invisible.",
        "Selected text now uses the surface's own bright-text colour, which "
        "is legible on the tint in every theme, and the tree's branch/indent "
        "strip (previously an opaque solid block) now paints the same tint "
        "as the row.",
        "Switching themes while a row is selected updates both immediately "
        "— no lingering unreadable selection from before the switch.",
    ),
    test_steps=(
        "Switch to the Gruvbox theme, open a series and select an episode "
        "row → the title stays clearly readable on the selection tint, and "
        "the indent strip beside it is tinted, not a solid block.",
        "With a row selected, switch to a different theme (e.g. Daylight) → "
        "the row is still clearly readable, and the selection style is not "
        "doubled or stacked.",
    ),
)
