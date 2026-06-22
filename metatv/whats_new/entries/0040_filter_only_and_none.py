from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=40,
    version="0.9.0",
    date="2026-06-22",
    title="Filter panel: 'Only' action + reliable none-persistence",
    items=(
        "Each filter row now has an 'Only ◎' button (and a right-click 'Only …' menu item): one click clears every other filter group across all sections and shows just that group's channels — e.g. 'Only Netflix' hides everything else instantly.",
        "Selecting none in a filter section (Language, Region, Platform, Quality, Genre) is now faithfully saved and restored. Previously, an all-unchecked section would silently revert to all-selected on relaunch; now 'explicitly none' is remembered correctly.",
        "Existing configs upgrade automatically: old empty-list settings are treated as 'never configured' (all-selected default), so no one sees a surprise empty list on first update.",
    ),
)
