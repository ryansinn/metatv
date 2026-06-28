from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=82,
    version="0.9.0",
    date="2026-06-28",
    title="Bulk 'Mark as Watched' now toggles — unmark all works too",
    items=(
        "Selecting multiple already-watched movies or series and right-clicking now shows "
        "'Mark as Unwatched' and unmarks them all — the action is a true toggle that "
        "mirrors the single-item behavior.",
        "When a mix of watched and unwatched items is selected the bulk action marks them "
        "all as watched (same as before).",
    ),
    test_steps=(
        "Mark two or more movies as watched individually (right-click → Mark as Watched). "
        "Select both of them, right-click — the menu should read 'Mark as Unwatched' "
        "(not 'Mark as Watched').",
        "Click 'Mark as Unwatched' — confirm both items are now unmarked "
        "(watch glyph disappears, no full list reload).",
        "Select a mix of watched and unwatched movies, right-click — menu must read "
        "'Mark as Watched'. Trigger it — all items become watched.",
        "With 'Hide watched' ON, select several unwatched items → right-click → "
        "'Mark as Watched' — rows should vanish immediately from the list.",
    ),
)
