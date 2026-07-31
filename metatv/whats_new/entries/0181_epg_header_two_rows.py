from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=181,
    version="0.14.1",
    date="2026-07-31",
    title="EPG tabs now get the full width — all of them fit",
    items=(
        "The EPG header is now two stacked rows. The tab bar (Watchlist, My "
        "Channels, Discover, On Now, Browse, Manage, Events) gets the whole "
        "header width on the top row, so every tab is visible at once.",
        "The source-freshness status text and the Refresh button moved to a slim "
        "right-aligned line just beneath the tabs — they no longer crowd the tab "
        "row and force it into a ‹ › scrolling state where tabs were hidden.",
    ),
    test_steps=(
        "Open the EPG view and check the header: all seven tabs (Watchlist, My "
        "Channels, Discover, On Now, Browse, Manage, Events) are visible on one "
        "row with no ‹ › overflow-scroll arrows.",
        "Confirm the status text (e.g. 'TREX Shared · Updated 18h ago…') and the "
        "Refresh button now sit on a second, right-aligned line directly below "
        "the tabs.",
        "Click Refresh on that second line → EPG data refreshes for the active "
        "sources (same behaviour as before) and the status line updates.",
    ),
)
