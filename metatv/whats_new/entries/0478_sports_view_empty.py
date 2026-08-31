from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=478,
    version="0.64.0",
    date="2026-08-31",
    title="The Sports view shows its fixtures again",
    items=(
        "Opening Sports showed the sport chips and the counts along the top — "
        "On now, Upcoming, Channels — and then nothing underneath. The list "
        "was empty every single time it was opened.",
        "The fixtures were always there and were always found; they were being "
        "thrown away between the database and the screen. The view asked for "
        "the rows and the counts at the same moment, and asking for the counts "
        "cancelled the request for the rows.",
        "It looked unescapable because clicking the lane that was already "
        "selected does nothing by design, so the only way out was to click a "
        "different lane — which asked for rows on their own and worked.",
    ),
    test_steps=(
        ("Open Sports. The list should fill with fixtures straight away, "
         "without you clicking anything.", "view:sports"),
        "Click through On now, Upcoming, Channels and Finished — each should "
        "show its rows, and the counts on the tabs should stay put.",
        "Pick a sport chip, then switch lanes; the list should follow the "
        "filter rather than emptying.",
        "Leave Sports for another view and come back — it should still show "
        "rows, not an empty list.",
    ),
)
