from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=81,
    version="0.9.0",
    date="2026-06-28",
    title="Hide Watched filter + targeted mark-watched update",
    items=(
        "New 'Hide watched' toggle in the filter panel — when on, movies and series you "
        "have already watched are excluded from the channel list. Off by default.",
        "The stats label shows how many items are hidden because they're watched "
        "('N watched hidden') when the filter is active.",
        "Marking a single item (or bulk) as watched no longer triggers a full list "
        "reload — the row's watch indicator updates in place. When 'Hide watched' is ON, "
        "the row disappears immediately without a jarring refresh.",
    ),
    test_steps=(
        "Open the filter panel. Confirm 'Hide watched' checkbox exists and is OFF by default.",
        "Right-click a movie or series → Mark as Watched. Verify only that row's watch "
        "glyph updates (✓ appears) and the list does NOT jump/reload.",
        "Check 'Hide watched' in the filter panel. Confirm the just-watched item "
        "disappears and the stats label shows 'N watched hidden'.",
        "With 'Hide watched' ON, right-click another item → Mark as Watched. Confirm it "
        "vanishes from the list immediately and the hidden count increments by 1.",
        "Uncheck 'Hide watched'. Confirm all watched items reappear.",
        "Restart the app. Confirm 'Hide watched' restores to the state you left it in.",
    ),
)
