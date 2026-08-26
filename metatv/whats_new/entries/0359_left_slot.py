from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=359,
    version="0.41.0",
    date="2026-08-26",
    title="The play button moves left, and stops shoving the row around",
    items=(
        "Hovering a Watch Alerts row used to make a play button appear at the "
        "right-hand edge, which pushed the progress bar sideways every time "
        "your pointer crossed a row. It now lives in a fixed column at the far "
        "left, so nothing moves.",
        "That column is one place for everything a row has to say about "
        "itself: the play triangle, and a dot when the item is new. Only one "
        "shows at a time — what is playing now outranks an offer to start it, "
        "which outranks a note that something arrived.",
        "A row that is playing right now shows its triangle in green.",
        "Upcoming programmes no longer offer a play button. They have not "
        "aired yet, so there was nothing for it to do.",
    ),
    test_steps=(
        "Hover across several Watch Alerts rows → a play triangle appears at "
        "the far LEFT of each, and the progress bars do not shift by even a "
        "pixel as you move between rows.",
        "Click the triangle → the channel plays. Click the row's title instead "
        "→ it selects without playing.",
        "While something is playing, find its row → its triangle is green and "
        "stays visible when you move the mouse away.",
        "Hover an UPCOMING row → no play triangle appears at all.",
        "Find an upcoming row marked as new → it still shows its green dot in "
        "that same left column.",
    ),
)
