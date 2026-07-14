from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=134,
    version="0.9.0",
    date="2026-07-14",
    title="Consistent movie interaction everywhere — middle-click + full right-click menu",
    items=(
        "Middle-clicking a movie now plays your configured middle-click action "
        "(Settings → Interaction: Resume from saved position, or Play with endless "
        "buffer) on EVERY surface — Discover shelves and 'See all', the Recipe "
        "'Now Plating' results, and the Recommended / Watch Queue / Favorites "
        "sidebar sections — not just the main channel list.",
        "Right-clicking a movie in the Discover-family surfaces now shows the FULL "
        "standard movie menu: Play with open-ended buffer, Mark as Watched, and "
        "Add to Category joined the menu that Discover, Recipe, Recommended and the "
        "Preferences dashboard all share.",
        "The Favorites and Watch Queue right-click menus gained the same standard "
        "actions (Mark as Watched / Add to Category / Play with open-ended buffer) "
        "so the menu you get is the same no matter where you clicked the title.",
    ),
    test_steps=(
        "Settings → Interaction: set the middle-click action to 'Resume from saved "
        "position'. Open the Discover chip and MIDDLE-click a movie card — it starts "
        "playing (resuming if it has a saved position), same as middle-clicking it in "
        "the main channel list.",
        "In Discover, RIGHT-click a movie card: the menu now includes 'Play with "
        "open-ended buffer', 'Mark as Watched', and 'Add to Category…' — the full "
        "standard movie menu.",
        "Open the Recommended sidebar section (or the Recipe 'Now Plating' results) and "
        "MIDDLE-click a movie row/card — it plays the configured action.",
        "Right-click a title in Favorites and in the Watch Queue: each menu now shows "
        "'Mark as Watched' and 'Add to Category…' (Queue also shows 'Play with "
        "open-ended buffer').",
    ),
)
