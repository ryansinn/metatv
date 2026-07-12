from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=131,
    version="0.9.0",
    date="2026-07-11",
    title="Your data and views stay correct",
    items=(
        "Removing a source no longer erases your watch progress or watched marks "
        "for episodes of a series you've favorited, played, or queued — that history "
        "is preserved.",
        "The Watch Later queue keeps a stable order after you remove items from the "
        "middle.",
        "The 'N hidden because watched' count now matches the actual filtered view "
        "(it used to over-count when a Quality / Language / genre filter was active).",
        "The details pane no longer briefly flips back to a previous title when that "
        "title's info finishes loading a moment late.",
        "Under Split Streams, quickly launching episodes from different sources no "
        "longer sends one to the wrong player window, and the 'now playing' indicator "
        "no longer clears for a title still playing in another window.",
        "Cleaner detected data: a parenthetical quality like '(SD)' is treated as "
        "quality rather than a region, and placeholder junk like 'N/A' is no longer "
        "added as a genre.",
        "Titles from metadata are shown exactly as provided (no accidental trimming "
        "of a title that ends in a parenthetical or year).",
        "The Recipe and EPG views refresh when you toggle a source on or off.",
    ),
    test_steps=(
        "Add several items to Watch Later, remove one from the middle, then add "
        "another: the list keeps a sensible order (no item jumps or duplicates a slot).",
        "Turn on 'Hide watched' while a Quality or Language filter is active: the "
        "'N watched hidden' number matches how many items are actually removed from "
        "the visible list.",
        "Click one channel, then immediately click another: the details pane stays on "
        "the second channel (it doesn't flip back to the first when its info loads).",
        "Toggle a source off in the sidebar while the Recipe view is open: its shelves "
        "update to drop that source's cards (they don't linger until you navigate away).",
    ),
)
