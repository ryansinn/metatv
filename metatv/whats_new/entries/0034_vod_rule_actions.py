from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=34,
    version="0.8.0",
    date="2026-06-22",
    title="Interactive VOD Watch-For Rules",
    items=(
        "Click any 'Watching for' rule in the Alerts sidebar to instantly search for "
        "matching content — the main channel list populates with results for that keyword.",
        "Right-click a rule row for a context menu: 'View matches' (search), 'Remove rule' "
        "(delete without opening Manage), and 'Manage rules…' (open the full dialog).",
        "In the Manage Rules dialog, each rule now has a 'View' button that searches for "
        "matches and closes the dialog in one click.",
    ),
)
