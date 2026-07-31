from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=183,
    version="0.14.2",
    date="2026-07-31",
    title="EPG source status + Refresh now sit on the programmes-count line",
    items=(
        "The EPG source-freshness status text and the Refresh button no longer "
        "sit in the tab header — they now sit right-aligned on the same "
        "\"###,### EPG programmes\" line at the bottom of the window, so the "
        "count, the source status and Refresh read as one status strip.",
        "They appear only while the EPG view is open, and the whole header width "
        "now belongs to the tab bar (no more ‹ › overflow-scroll hiding tabs).",
    ),
    test_steps=(
        "Open the EPG view → the '###,### EPG programmes' line shows the source "
        "status text (e.g. 'TREX Shared · Updated 18h ago') and a Refresh button "
        "right-aligned on that SAME line — not on a separate bar, and not in the "
        "tab header.",
        "Switch between EPG tabs (Watchlist, On Now, Browse, …) → the status text "
        "and Refresh button stay on that bottom count line for every tab.",
        "Leave the EPG view (click another sidebar view) → the EPG status text and "
        "Refresh button disappear from the stats line; return to EPG → they reappear.",
        "Click Refresh on the stats line → EPG data refreshes for the active "
        "sources and the status text updates (same behaviour as before).",
    ),
)
