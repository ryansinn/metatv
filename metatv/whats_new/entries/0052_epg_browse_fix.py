from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=52,
    version="0.9.0",
    date="2026-06-24",
    title="EPG Browse works again — schedule shows without a search",
    items=(
        "The EPG 'Browse' tab is a date/time schedule browser again: pick a day "
        "and time slot and it lists every programme in that window — no search "
        "term required. A regression had made it show only its placeholder unless "
        "you typed a search, leaving the date/time controls dead.",
        "Typing in the search box still narrows Browse to matching upcoming "
        "programmes, as before.",
        "When a day/slot (or search) has no programmes, Browse shows a clear "
        "empty-state message instead of a blank list, and tells you when there "
        "are no EPG sources to browse.",
    ),
    test_steps=(
        "Open EPG → Browse tab (with at least one EPG source enabled) → the schedule for Today populates immediately, no search needed.",
        "Change the date dropdown (e.g. Tomorrow) or the time slot (e.g. Prime Time) → the list reloads to that window.",
        "Type a show name in the search box → the list narrows to matching upcoming programmes; clear it → the full schedule returns.",
        "Double-click a row → the channel plays; right-click a row → the context menu (Play / Favorite / Track show) works.",
        "Pick a day/slot with nothing scheduled → a 'No programmes for the selected day and time' message appears instead of a blank list.",
    ),
)
