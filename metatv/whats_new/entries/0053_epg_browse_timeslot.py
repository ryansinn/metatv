from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=53,
    version="0.9.0",
    date="2026-06-24",
    title="EPG Browse: evening slots and Tomorrow now show programmes",
    items=(
        "Fixed a timezone bug that caused 'Prime Time' and 'Late Night' to return "
        "nothing for users west of UTC (e.g. CST/MDT/PDT): EPG rows for evening "
        "shows cross the UTC date boundary, and the date window was originally "
        "anchored to UTC midnight rather than local midnight. The fix uses "
        "local_day_window() so the window covers the correct local calendar day.",
        "Picking 'Tomorrow' now returns that day's schedule regardless of timezone.",
        "The search-box clear button now uses the standard icon and size (matching "
        "the main channel-list search bar) and has a 'Clear search' tooltip.",
    ),
    test_steps=(
        "Open EPG -> Browse tab. Set date to Today and time slot to 'Prime Time 6-11' "
        "-> evening programmes (6 PM - 11 PM local time) appear in the list.",
        "Set date to Tomorrow -> tomorrow's schedule loads, not today's evening shows.",
        "Verify the clear button next to the search box has an 'x' icon, tooltip "
        "'Clear search', and is the same size as the main search-bar clear button. "
        "Click it -> the search box empties and the full schedule returns.",
        "Type a show name in the search box, then click the clear button -> "
        "the search is cleared and the schedule reloads.",
    ),
)
