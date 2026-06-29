from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=109,
    version="0.9.0",
    date="2026-06-28",
    title="Cleaner, monotone channel right-click menu",
    items=(
        "The channel right-click menu is now one consistent monochrome (gray) "
        "icon set — every action has its own unique glyph and the colourful "
        "platform emoji no longer clash. The single splash of colour is reserved "
        "for resuming: the only orange item is the one that picks up where you "
        "left off.",
        "Resume reads at a glance: when a partially-watched movie would resume on "
        "click, the Play item turns orange and relabels to 'Play from M:SS' — the "
        "same orange used by the channel-list ▶ indicator and the details Resume "
        "button. 'Play from Beginning' is now plainly gray (it no longer looked "
        "like the resume action).",
        "Distinct, sensible glyphs: 'Play with open-ended buffer' now uses an "
        "infinity ∞ symbol, 'Play in New Window' uses a window-over-window symbol, "
        "and 'Add to Category' has its own shelf icon instead of borrowing the "
        "'Add to Queue' clipboard.",
    ),
    test_steps=(
        "Right-click a partially-watched movie (default Resume mode): the top "
        "item reads 'Play from M:SS' and its icon is ORANGE; 'Play from "
        "Beginning' just below it is GRAY.",
        "In Settings set playback to 'Start from beginning', then right-click the "
        "same movie: 'Play' is gray and a separate ORANGE 'Resume from M:SS' item "
        "appears.",
        "Right-click an unwatched movie: the item is just 'Play' in gray (no "
        "orange, no time).",
        "Open the same menu and eyeball the icons: 'Add to Queue' and 'Add to "
        "Category' now have clearly different icons; 'Play with open-ended buffer' "
        "shows ∞ and 'Play in New Window' shows a window-over-window glyph — all "
        "gray, none of them rendered as multicolour emoji.",
    ),
)
