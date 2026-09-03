from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=573,
    version="0.90.0",
    date="2026-09-03",
    title="Sidebar list selections stay readable too, in every theme",
    items=(
        "The readability fix for selected rows (channel list, series tree) "
        "didn't reach the sidebar's own lists — History, Favorites, "
        "Downloads, Watch Alerts and its sub-lists, Recordings, the Watch "
        "Queue, and Recommended. They composed the selection styling "
        "directly instead of going through the same fix, so selecting a row "
        "there still painted near-invisible text in Gruvbox and most themes.",
        "All nine sidebar lists now route through the same shared styling "
        "as the main channel list, so selected text stays legible on the "
        "tint everywhere a row can be selected.",
    ),
    test_steps=(
        "Switch to the Gruvbox theme, select a row in History or the Watch "
        "Queue → the text stays clearly readable on the selection tint, "
        "matching the main list.",
        "Select a row in Watch Alerts (including a nested sub-list) → same "
        "readable result.",
    ),
)
