from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=94,
    version="0.9.0",
    date="2026-06-28",
    title="Context menus: recipe cards, queued-variant labels, and queue Mark-as-Watched",
    items=(
        "Right-clicking a card in the Recipe view's 'Now Plating' (and 'Show all') "
        "results now opens the standard channel context menu — the same one Discover "
        "cards use (Play, Favorite, Add to Queue, rate, hide, …).",
        "The details-pane 'Also available as' version-chip menu now labels its queue "
        "action by state: it reads 'Remove from Queue' when that variant is already "
        "queued (clock icon) and 'Add to Queue' otherwise.",
        "Watch Queue items now have a 'Mark as Watched' action in their right-click "
        "menu (it flips to 'Mark as Unwatched' once watched), matching the main "
        "channel list.",
    ),
    test_steps=(
        "Open the Recipe view (✦), build a recipe so 'Now Plating' shows result "
        "cards, then right-click a card — confirm the standard channel context menu "
        "appears with Play / Favorite / Add to Queue. Click 'Show all →' and "
        "right-click a card there too; confirm the same menu appears.",
        "Open a movie/series in the details pane that has alternate versions. "
        "Right-click a chip under 'Also available as' for a variant that is NOT "
        "queued — confirm the menu says 'Add to Queue'. Click it, then right-click "
        "the same chip again — confirm it now reads 'Remove from Queue' and the chip "
        "shows the queue (clock) icon.",
        "Add a movie to the Watch Queue, open the Queue, and right-click the item — "
        "confirm a 'Mark as Watched' action is present. Click it and confirm the "
        "item is marked watched; right-click again and confirm the action now reads "
        "'Mark as Unwatched'.",
        "Right-click a LIVE channel in the Watch Queue and confirm 'Mark as Watched' "
        "is NOT shown (it applies to movies/series only).",
    ),
    addresses=(
        "flagged:32663cdd-bc49-44bc-9ee1-74401439847c",
        "flagged:02bb5b62-f1b6-44af-bf3b-c43fb99ded3e",
    ),
)
