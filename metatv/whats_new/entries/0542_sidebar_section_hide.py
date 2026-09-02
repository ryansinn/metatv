from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=542,
    version="0.81.0",
    date="2026-09-02",
    title="Right-click a sidebar section to hide it",
    items=(
        "Every sidebar section header (Favorites, History, Watch Queue, "
        "Movies & Series, Recommended, Sources) now has a right-click menu "
        "with two items: 'Hide {section}' and 'Sidebar settings…'.",
        "Hiding a section shows a toast with an Undo action, and the toast "
        "names Settings → Sidebar as the permanent home for show/hide + "
        "reorder — the menu is a shortcut over that existing mechanism, not "
        "a new way to hide sections.",
        "'Sidebar settings…' jumps straight to the Sidebar tab in Settings.",
    ),
    test_steps=(
        "Right-click the Favorites section header and choose Hide Favorites: "
        "the section disappears immediately and a toast offers Undo and "
        "points to Settings → Sidebar.",
        "Click Undo on that toast: the section returns in its original "
        "position.",
        ("Right-click a section header and choose 'Sidebar settings…': "
         "Settings opens on the Sidebar page.", "settings:Sidebar"),
        "Hide a section, restart the app: it stays hidden; re-enable it in "
        "Settings → Sidebar and it returns with a usable height.",
    ),
)
