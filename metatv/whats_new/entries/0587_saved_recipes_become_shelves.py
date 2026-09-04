from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=587,
    version="0.95.0",
    date="2026-09-04",
    title="Saved recipes become live Discover shelves",
    items=(
        "Every saved recipe now appears as its own live Discover shelf — "
        "marked with a ✦ and pinned to the top by default — with new "
        "matching content flowing in automatically as sources refresh.",
        "A recipe shelf is fully reorder/hide-able like any other Discover "
        "shelf: pin, collapse, or hide it through the same Manage dialog.",
        "An ✎ on the shelf opens the recipe editor for that recipe.",
        "A per-recipe \"Show in Discover\" toggle on the Saved tab is the "
        "master switch — off means no shelf at all, on restores it.",
    ),
    test_steps=(
        "Save a recipe → open Discover → a ✦-marked shelf with its "
        "matches appears pinned at the top.",
        "On the Saved tab, toggle \"Show in Discover\" off for that recipe "
        "→ the shelf disappears from Discover.",
        "Click the ✎ icon on a recipe shelf → the Recipe editor opens "
        "with that recipe loaded.",
    ),
)
