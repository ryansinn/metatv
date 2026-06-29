from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=110,
    version="0.9.0",
    date="2026-06-28",
    title="Group channel results by type (opt-in)",
    items=(
        "A new 'Group by type' checkbox in the channel-list header groups your "
        "results into collapsible Movies / Series / Live sections, each with a "
        "live count in its header.",
        "It's opt-in: the flat list stays the default. Your choice is remembered "
        "across restarts, and so is which sections you've collapsed.",
        "Click a section header (or double-click it) to collapse/expand just that "
        "group — the rows inside keep all their usual behaviour: playback "
        "indicator (·/▶/✓), favorite star, rating, and the watched dimming.",
    ),
    test_steps=(
        "With grouping OFF (default), confirm the channel list is a single flat "
        "list with no section headers.",
        "Tick the 'Group by type' checkbox in the header: the results regroup "
        "under Movies / Series / Live headers, each showing a count like "
        "'Movies (123)'.",
        "Click the Movies header: its rows collapse to just the header and the "
        "arrow flips to the expand glyph; click again to expand them back.",
        "Restart the app: 'Group by type' is still ticked and any section you "
        "left collapsed is still collapsed.",
        "Partially watch a movie, then find it under the Movies section: its row "
        "still shows the orange ▶ playback indicator (the #264 badge survives "
        "grouping).",
        "Untick 'Group by type': the list returns to the flat single list.",
    ),
)
