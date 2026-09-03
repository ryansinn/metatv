from metatv.whats_new import WhatsNewEntry

ENTRY = WhatsNewEntry(
    id=562,
    version="0.86.0",
    date="2026-09-03",
    title="The Sports search box says what it does",
    items=(
        "The Sports view's search box now reads \"Filter results…\" instead "
        "of \"Search fixtures…\" — it narrows the rows already on screen "
        "within the active lane and chips, and \"fixture\" is jargon most "
        "people don't use.",
    ),
    test_steps=(
        "Open the Sports view → the search box placeholder reads "
        "\"Filter results…\".",
        "Type a team name with a lane and sport chip active → the list "
        "narrows within that lane, exactly as before.",
    ),
)
