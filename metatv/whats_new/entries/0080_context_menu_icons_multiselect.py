from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=80,
    version="0.8.0",
    date="2026-06-28",
    title="Context menus: icon column on action rows + bulk actions for multi-select",
    items=(
        "Channel context menu action rows (Play, Favorites, Queue, Mark as Watched,"
        " Hide) now show a glyph icon in Qt's reserved icon column, giving the menu"
        " a scannable visual anchor. Admin/rare rows (EPG watch, Track keyword, etc.)"
        " stay blank in that column, signalling a different tier.",
        "When multiple channels are selected, the context menu now includes bulk"
        " actions: Add to Favorites, Add to Queue, Mark as Watched, and Hide Selected"
        " — each applying to all selected channels at once.",
        "The source-variant chip right-click menu (details pane 'Also available as:')"
        " follows the same icon pattern: Play and Show Details get icons, admin rows"
        " (Filter out / Hide category / Edit Category Name) stay icon-less.",
    ),
    test_steps=(
        "Right-click any channel in the channel list → confirm Play, Favorites, Queue,"
        " Mark as Watched, and Hide rows each show a small glyph icon to their left;"
        " EPG Watch / Track keyword rows should have a blank icon column (no glyph).",
        "Right-click the same channel menu and confirm no icon glyph appears in the"
        " action label text itself (icon is in the Qt icon column, not the label).",
        "Select 2+ channels (Ctrl+click or Shift+click in search results) and"
        " right-click → confirm 'Add to Favorites', 'Add to Queue', 'Mark as Watched',"
        " and 'Hide Selected' are present in the multi-select menu.",
        "In the multi-select menu, click 'Mark as Watched' → all selected channels"
        " should show the ✓ watch glyph in the list and their watch state persists"
        " after closing and reopening the app.",
        "Open a channel with variant chips (details pane 'Also available as:') and"
        " right-click a chip → Play/Show Details have icons; Filter out / Hide"
        " category / Edit Category Name have no icon (blank column).",
    ),
)
